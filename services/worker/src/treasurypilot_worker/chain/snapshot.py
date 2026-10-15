"""Block-consistent treasury snapshots read through Multicall3 (M06 §8.1, §15)."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import astuple, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final

import asyncpg  # type: ignore[import-untyped]
from eth_abi import decode, encode
from eth_abi.exceptions import DecodingError
from web3 import Web3

from treasurypilot_worker.chain.rpc import (
    SAFE_GUARD_SLOT,
    SAFE_SENTINEL,
    RpcClient,
    RpcError,
    build_rpc_client,
    decode_rpc_urls,
)
from treasurypilot_worker.locks import create_worker_pool

logger = logging.getLogger(__name__)

MULTICALL3: Final = "0xcA11bde05977b3631167028862bE2a173976CA11"
MAX_AGE: Final = timedelta(seconds=30)
MAX_BLOCKS_BEHIND: Final = 2
DASHBOARD_RETENTION: Final = timedelta(days=7)
_PAY, _REFILL, _SUPPLY = 1, 2, 4  # module action ids
_ZERO: Final = "0x" + "00" * 20
_AGGREGATE3: Final = bytes(Web3.keccak(text="aggregate3((address,bool,bytes)[])")[:4])
_RESERVE = (
    "(uint256,uint128,uint128,uint128,uint128,uint128,uint40,uint16,"
    "address,address,address,address,uint128,uint128,uint128)"
)
_MANDATE = (
    "(uint64,uint64,uint64,uint32,address,address,(uint128,uint128),(uint128,uint128),"
    "uint32,(uint128,uint128))"
)


class SnapshotPurpose(StrEnum):
    PLAN = "PLAN"
    PRE_STEP = "PRE_STEP"
    DASHBOARD = "DASHBOARD"
    DAILY = "DAILY"  # kept forever: reconciliation interest reads the day-boundary aToken balance
    READBACK = "READBACK"


@dataclass(frozen=True)
class SnapshotTarget:
    """The contracts of one treasury; addresses are hex strings."""

    module: str
    asset: str
    safe_t: str
    operational: tuple[str, ...]


@dataclass(frozen=True)
class SnapshotScope:
    """Extra reads for the requests a plan covers; hashes are 0x-prefixed bytes32 hex."""

    approvers: tuple[str, ...] = ()
    payees: tuple[str, ...] = ()
    request_ids: tuple[str, ...] = ()
    step_ids: tuple[str, ...] = ()
    fingerprints: tuple[str, ...] = ()


@dataclass(frozen=True)
class Snapshot:
    """Chain state of one treasury at one block. Amounts are decimal strings of base units."""

    purpose: SnapshotPurpose
    block_number: int
    block_hash: str
    block_timestamp: datetime
    provider: str
    data: dict[str, Any]
    coverage: str
    # Dotted paths into ``data`` whose sub-call failed or returned undecodable data.
    missing: tuple[str, ...]
    id: uuid.UUID = field(default_factory=uuid.uuid4, compare=False)


def is_fresh(snapshot: Snapshot, now: datetime, head: int) -> bool:
    """A plan may only use a snapshot at most 30 s and 2 blocks behind the chain (M08-D6)."""

    return (
        now - snapshot.block_timestamp <= MAX_AGE
        and head - snapshot.block_number <= MAX_BLOCKS_BEHIND
    )


def _plain(values: tuple[Any, ...]) -> Any:
    def one(value: Any) -> Any:
        if isinstance(value, bytes):
            return "0x" + value.hex()
        if isinstance(value, str):
            return value.lower()
        if isinstance(value, tuple | list):
            return [one(item) for item in value]
        return value

    return one(values[0] if len(values) == 1 else values)


def _amount(values: tuple[Any, ...]) -> str:
    return str(values[0])


def _limits(limits: tuple[int, int]) -> dict[str, str]:
    return {"per_request": str(limits[0]), "daily": str(limits[1])}


def _mandate(values: tuple[Any, ...]) -> dict[str, Any]:
    ((version, valid_from, expires_at, cooling, executor, guardian, pay, refill, age, supply),) = (
        values
    )
    return {
        "version": version,
        "valid_from": valid_from,
        "expires_at": expires_at,
        "payee_cooling_seconds": cooling,
        "executor": executor.lower(),
        "guardian": guardian.lower(),
        "pay": _limits(pay),
        "refill": _limits(refill),
        "approval_max_age": age,
        "supply": _limits(supply),
    }


def _payee(values: tuple[Any, ...]) -> dict[str, int]:
    return {"state": values[0], "active_from": values[1]}


def _exception(values: tuple[Any, ...]) -> dict[str, Any]:
    amount, expiry, version, payee, used = values
    return {
        "amount": str(amount),
        "expiry": expiry,
        "mandate_version": version,
        "payee": payee.lower(),
        "used": used,
    }


def _guard(values: tuple[Any, ...]) -> str | None:
    address = "0x" + values[0][-20:].hex()
    return None if address == _ZERO else address


@dataclass(frozen=True)
class _Read:
    path: tuple[str, ...]
    to: str
    signature: str
    outputs: tuple[str, ...]
    args: tuple[Any, ...] = ()
    shape: Callable[[tuple[Any, ...]], Any] = _plain


def _read(
    path: str, to: str, signature: str, outputs: str, *args: Any, shape: Any = _plain
) -> _Read:
    return _Read(tuple(path.split("/")), to, signature, tuple(outputs.split()), args, shape)


def _state_reads(target: SnapshotTarget, scope: SnapshotScope) -> list[_Read]:
    asset, module = target.asset, target.module
    reads = [
        _read("asset/decimals", asset, "decimals()", "uint8"),
        _read("module/mandate", module, "mandate()", _MANDATE, shape=_mandate),
        _read("module/status", module, "status()", "uint8"),
        _read(
            "module/used_today/PAY",
            module,
            "usedToday(uint8,address)",
            "uint256",
            _PAY,
            asset,
            shape=_amount,
        ),
        _read(
            "module/used_today/REFILL",
            module,
            "usedToday(uint8,address)",
            "uint256",
            _REFILL,
            asset,
            shape=_amount,
        ),
        _read(
            "module/used_today/SUPPLY",
            module,
            "usedToday(uint8,address)",
            "uint256",
            _SUPPLY,
            asset,
            shape=_amount,
        ),
    ]
    for wallet in (target.safe_t, *target.operational):
        reads += [
            _read(
                f"balances/{wallet}", asset, "balanceOf(address)", "uint256", wallet, shape=_amount
            ),
            _read(
                f"buffers/{wallet}",
                module,
                "bufferOf(address,address)",
                "uint256",
                asset,
                wallet,
                shape=_amount,
            ),
            _read(
                f"targets/{wallet}",
                module,
                "targetOf(address,address)",
                "uint256",
                asset,
                wallet,
                shape=_amount,
            ),
            _read(f"safes/{wallet}/owners", wallet, "getOwners()", "address[]"),
            _read(f"safes/{wallet}/threshold", wallet, "getThreshold()", "uint256"),
            _read(f"safes/{wallet}/nonce", wallet, "nonce()", "uint256"),
            # shortcut: one page of 50 modules, more than that already breaks coverage anyway.
            _read(
                f"safes/{wallet}/modules",
                wallet,
                "getModulesPaginated(address,uint256)",
                "address[] address",
                SAFE_SENTINEL,
                50,
                shape=lambda v: _plain(v[:1]),
            ),
            # The guard slot is read through the Safe so it stays inside the multicall.
            _read(
                f"safes/{wallet}/guard",
                wallet,
                "getStorageAt(uint256,uint256)",
                "bytes",
                int(SAFE_GUARD_SLOT, 16),
                1,
                shape=_guard,
            ),
        ]
    for approver in scope.approvers:
        reads.append(
            _read(f"module/approvers/{approver}", module, "isApprover(address)", "bool", approver)
        )
    for payee in scope.payees:
        reads.append(
            _read(
                f"payees/{payee}",
                module,
                "payeeStatus(address)",
                "uint8 uint64",
                payee,
                shape=_payee,
            )
        )
    for request in scope.request_ids:
        reads += [
            _read(f"requests/{request}/paid", module, "requestPaid(bytes32)", "bool", request),
            _read(
                f"requests/{request}/cancelled",
                module,
                "requestCancelled(bytes32)",
                "bool",
                request,
            ),
            _read(
                f"requests/{request}/exception",
                module,
                "exceptions(bytes32)",
                "uint128 uint64 uint64 address bool",
                request,
                shape=_exception,
            ),
        ]
        reads += [
            _read(
                f"requests/{request}/refilled/{wallet}",
                module,
                "refilledFor(bytes32,address)",
                "bool",
                request,
                wallet,
            )
            for wallet in target.operational
        ]
    for step in scope.step_ids:
        reads.append(_read(f"steps/{step}/used", module, "stepUsed(bytes32)", "bool", step))
    for fingerprint in scope.fingerprints:
        reads += [
            _read(
                f"fingerprints/{fingerprint}/paid",
                module,
                "fingerprintPaid(bytes32)",
                "bool",
                fingerprint,
            ),
            _read(
                f"fingerprints/{fingerprint}/allowed_for",
                module,
                "duplicateAllowedFor(bytes32)",
                "bytes32",
                fingerprint,
            ),
        ]
    return reads


def _aave_reads(target: SnapshotTarget, pool: str, a_token: str) -> list[_Read]:
    def reserve(values: tuple[Any, ...]) -> dict[str, str]:
        ((_, _, liquidity_rate, _, borrow_rate, _, _, _, token, *_),) = values
        if token.lower() != a_token:
            raise ValueError("reserve aToken differs from the module's aToken")
        return {"liquidity_rate": str(liquidity_rate), "variable_borrow_rate": str(borrow_rate)}

    def account(values: tuple[Any, ...]) -> dict[str, str]:
        collateral, debt, *_, health_factor = values
        return {
            "total_collateral_base": str(collateral),
            "total_debt_base": str(debt),
            "health_factor": str(health_factor),
        }

    return [
        _read(
            "aave/a_token_balance",
            a_token,
            "balanceOf(address)",
            "uint256",
            target.safe_t,
            shape=_amount,
        ),
        _read(
            "aave/available_liquidity",
            target.asset,
            "balanceOf(address)",
            "uint256",
            a_token,
            shape=_amount,
        ),
        _read(
            "aave/reserve", pool, "getReserveData(address)", _RESERVE, target.asset, shape=reserve
        ),
        _read(
            "aave/account",
            pool,
            "getUserAccountData(address)",
            "uint256 " * 5 + "uint256",
            target.safe_t,
            shape=account,
        ),
    ]


def _hex(raw: Any) -> str:
    return "0x" + bytes(raw).hex()


def _calldata(read: _Read) -> bytes:
    inputs = read.signature[read.signature.index("(") + 1 : -1]
    types = [t for t in inputs.split(",") if t]
    args = [
        bytes.fromhex(a[2:]) if t == "bytes32" else a for t, a in zip(types, read.args, strict=True)
    ]
    return bytes(Web3.keccak(text=read.signature)[:4]) + encode(types, args)


async def _aggregate(
    rpc: RpcClient, block: dict[str, str], reads: Sequence[_Read]
) -> tuple[str, list[tuple[bool, bytes]]]:
    calls = [(read.to.lower(), True, _calldata(read)) for read in reads]
    payload = _AGGREGATE3 + encode(["(address,bool,bytes)[]"], [calls])
    provider, raw = await rpc.call_with_provider(
        "eth_call", [{"to": MULTICALL3, "data": "0x" + payload.hex()}, block]
    )
    try:
        (results,) = decode(["(bool,bytes)[]"], bytes.fromhex(str(raw).removeprefix("0x")))
    except (DecodingError, ValueError):
        raise RpcError(f"Multicall3 is not available at {MULTICALL3}") from None
    if len(results) != len(calls):
        raise RpcError("Multicall3 returned a different number of results")
    return provider, list(results)


def _fill(
    data: dict[str, Any],
    missing: list[str],
    reads: Sequence[_Read],
    results: Sequence[tuple[bool, bytes]],
) -> None:
    for read, (ok, raw) in zip(reads, results, strict=True):
        try:
            if not ok:
                raise ValueError("call failed")
            value = read.shape(decode(list(read.outputs), raw))
        except (DecodingError, ValueError):
            # Never substitute a default: M08 blocks on DATA_MISSING.
            missing.append(".".join(read.path))
            continue
        node = data
        for key in read.path[:-1]:
            node = node.setdefault(key, {})
        node[read.path[-1]] = value


async def read_snapshot(
    rpc: RpcClient,
    target: SnapshotTarget,
    purpose: SnapshotPurpose,
    scope: SnapshotScope | None = None,
    *,
    block: int | str = "latest",
    coverage: str = "UNKNOWN",
) -> Snapshot:
    """Read the whole §8.1 set in Multicall3 calls that are all pinned to one block hash.

    ``coverage`` is the treasury's TRS-007 verdict; it degrades to UNKNOWN when a Safe read
    failed. A failed sub-call is listed in ``missing``; an unreachable RPC raises.
    """

    header = await rpc.call(
        "eth_getBlockByNumber", [block if isinstance(block, str) else hex(block), False]
    )
    if not header:
        raise RpcError(f"block {block} not found")
    # Pin by hash (EIP-1898): a failover or a reorg cannot mix two blocks into one snapshot.
    pin = {"blockHash": header["hash"]}
    target = SnapshotTarget(
        target.module.lower(),
        target.asset.lower(),
        target.safe_t.lower(),
        tuple(wallet.lower() for wallet in target.operational),
    )
    scope = SnapshotScope(
        *(tuple(item.lower() for item in group) for group in astuple(scope or SnapshotScope()))
    )
    data: dict[str, Any] = {}
    missing: list[str] = []
    reads = _state_reads(target, scope)
    provider, results = await _aggregate(rpc, pin, reads)
    _fill(data, missing, reads, results)

    # The Aave addresses are module state, so read them at the same block, then use them.
    discovery = [
        _read("aave/pool", target.module, "aavePool()", "address"),
        _read("aave/a_token", target.module, "aToken()", "address"),
    ]
    _, found = await _aggregate(rpc, pin, discovery)
    aave: dict[str, Any] = {}
    _fill(aave, missing, discovery, found)
    pool, a_token = aave.get("aave", {}).get("pool"), aave.get("aave", {}).get("a_token")
    if pool and pool != _ZERO and a_token:
        aave_reads = _aave_reads(target, pool, a_token)
        _, aave_results = await _aggregate(rpc, pin, aave_reads)
        data["aave"] = {"pool": pool, "a_token": a_token}
        _fill(data, missing, aave_reads, aave_results)

    if any(path.startswith("safes.") for path in missing):
        coverage = "UNKNOWN"
    return Snapshot(
        purpose=purpose,
        block_number=int(header["number"], 16),
        block_hash=str(header["hash"]).lower(),
        block_timestamp=datetime.fromtimestamp(int(header["timestamp"], 16), UTC),
        provider=provider,
        data=data,
        coverage=coverage,
        missing=tuple(missing),
    )


async def store_snapshot(
    connection: asyncpg.Connection, org_id: uuid.UUID, treasury_id: uuid.UUID, snapshot: Snapshot
) -> None:
    await connection.execute(
        """
        INSERT INTO snapshots
            (id, org_id, treasury_id, purpose, block_number, block_hash, block_timestamp,
             provider, data, coverage, missing)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11::jsonb)
        """,
        snapshot.id,
        org_id,
        treasury_id,
        snapshot.purpose.value,
        snapshot.block_number,
        bytes.fromhex(snapshot.block_hash.removeprefix("0x")),
        snapshot.block_timestamp,
        snapshot.provider,
        json.dumps(snapshot.data),
        snapshot.coverage,
        json.dumps(list(snapshot.missing)),
    )


async def take_snapshot(
    pool: asyncpg.Pool,
    treasury_id: uuid.UUID,
    purpose: SnapshotPurpose,
    scope: SnapshotScope | None = None,
    *,
    block: int | str = "latest",
    reader_factory: Callable[[Sequence[str]], RpcClient] = build_rpc_client,
) -> Snapshot:
    """Read and store one treasury snapshot (``snapshot()`` of M06 §6)."""

    async with pool.acquire() as connection:
        treasury = await connection.fetchrow(
            """
            SELECT t.org_id, t.coverage, t.module_address, a.address AS asset, c.rpc_urls
            FROM treasuries AS t
            JOIN assets AS a ON a.id = t.asset_id
            JOIN chains AS c ON c.chain_id = t.chain_id
            WHERE t.id = $1
            """,
            treasury_id,
        )
        if treasury is None or treasury["module_address"] is None:
            raise RpcError(f"treasury {treasury_id} has no deployed module to snapshot")
        wallets = await connection.fetch(
            "SELECT role, safe_address FROM treasury_wallets WHERE treasury_id = $1 ORDER BY id",
            treasury_id,
        )
    sources = [_hex(w["safe_address"]) for w in wallets if w["role"] == "SOURCE"]
    if len(sources) != 1:
        raise RpcError(f"treasury {treasury_id} must have exactly one source Safe")
    target = SnapshotTarget(
        module=_hex(treasury["module_address"]),
        asset=_hex(treasury["asset"]),
        safe_t=sources[0],
        operational=tuple(_hex(w["safe_address"]) for w in wallets if w["role"] != "SOURCE"),
    )
    rpc = reader_factory(decode_rpc_urls(treasury["rpc_urls"]))
    snapshot = await read_snapshot(
        rpc, target, purpose, scope, block=block, coverage=treasury["coverage"]
    )
    async with pool.acquire() as connection:
        await store_snapshot(connection, treasury["org_id"], treasury_id, snapshot)
    return snapshot


async def snapshot_dashboards(
    database_url: str,
    *,
    reader_factory: Callable[[Sequence[str]], RpcClient] = build_rpc_client,
    purpose: SnapshotPurpose = SnapshotPurpose.DASHBOARD,
) -> int:
    """Store a snapshot per live treasury; DASHBOARD runs also prune rows older than 7 days."""

    pool = await create_worker_pool(database_url)
    try:
        async with pool.acquire() as connection:
            treasuries = await connection.fetch(
                """
                SELECT t.id FROM treasuries AS t JOIN chains AS c ON c.chain_id = t.chain_id
                WHERE c.enabled AND t.status <> 'Revoked' AND t.module_address IS NOT NULL
                ORDER BY t.id
                """
            )
            if purpose is SnapshotPurpose.DASHBOARD:
                await connection.execute(
                    "DELETE FROM snapshots WHERE purpose = 'DASHBOARD' AND observed_at < $1",
                    datetime.now(UTC) - DASHBOARD_RETENTION,
                )
        stored = 0
        for row in treasuries:
            try:
                await take_snapshot(pool, row["id"], purpose, reader_factory=reader_factory)
                stored += 1
            except Exception:
                # One unreadable treasury must not starve the others; nothing is stored for it.
                logger.exception("%s snapshot failed for treasury %s", purpose.value, row["id"])
        return stored
    finally:
        await pool.close()


def snapshot_dashboards_sync(database_url: str) -> int:
    """Synchronous entrypoint for Celery's prefork worker."""

    return asyncio.run(snapshot_dashboards(database_url))


def snapshot_daily_sync(database_url: str) -> int:
    return asyncio.run(snapshot_dashboards(database_url, purpose=SnapshotPurpose.DAILY))
