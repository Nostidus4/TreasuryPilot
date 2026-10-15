"""Post-condition verification of a confirmed step (REC-001, M11 §8.1, M10-D6).

``expected`` is what the plan step implies; ``observed`` is the state at the confirmation block B
minus the state at B's parent (Multicall3, each pinned by block hash), with the ERC-20 transfers of
*other* transactions in block B removed so a concurrent in/outflow cannot cause a false DISCREPANCY.
Reorg safety: our receipt must sit in header(B), the B-1 pin is header(B).parentHash and logs are
fetched by blockHash; any mismatch raises ``RpcError`` (UNKNOWN, retried), never a DISCREPANCY.
``used_today`` is not diffed: its day key is block.timestamp / 1 days, so it only has to be >= the
step amount at B. Each verification is appended to ``verifications``; a DISCREPANCY also trips the
circuit breaker.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Final, Literal

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.policy import Action, PlanStep
from treasurypilot_worker.chain.rpc import RpcClient, RpcError
from treasurypilot_worker.chain.snapshot import _PAY, _REFILL, _aggregate, _fill, _Read, _read

logger = logging.getLogger(__name__)

Result = Literal["PASSED", "DISCREPANCY", "UNKNOWN"]
# aToken balances rebase every block. Underlying balances are checked exactly; the aToken delta may
# be up to ROUNDING wei below the expected change (index rounding) and up to ROUNDING plus
# before_atoken * RATE_NUM / RATE_DEN above it (interest of one block; 1e-6 per block is above 100%
# APR on a 12 s chain, so it is conservative). Interest never lowers the balance.
ATOKEN_ROUNDING: Final = 2
ATOKEN_RATE_NUM: Final = 1
ATOKEN_RATE_DEN: Final = 1_000_000
_TRANSFER_TOPIC: Final = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


@dataclass(frozen=True)
class Verification:
    result: Result
    block_number: int | None
    expected: dict[str, int]
    observed: dict[str, int]
    diffs: dict[str, dict[str, int]]


def _bal(wallet: str) -> str:
    return f"balance:{wallet.lower()}"


def _atoken(wallet: str) -> str:
    return f"atoken:{wallet.lower()}"


def expected_effects(step: PlanStep) -> dict[str, int]:
    """Expected change of each tracked quantity (booleans count 0 -> 1) for one step, §8.1."""

    a = int(step.amount)
    expected: dict[str, int] = {}

    def add(key: str, delta: int) -> None:
        expected[key] = expected.get(key, 0) + delta

    action = step.action
    if action in (Action.PAY, Action.REFILL):
        add(_bal(step.from_wallet), -a)
        add(_bal(step.to), a)
        add("used_today", a)
        add("request_paid" if action is Action.PAY else "refilled_for", 1)
    elif action is Action.SUPPLY:  # Safe T -> pool
        add(_bal(step.from_wallet), -a)
        add(_atoken(step.from_wallet), a)
    elif action is Action.WITHDRAW:  # pool -> Safe T
        add(_bal(step.to), a)
        add(_atoken(step.to), -a)
    else:
        raise ValueError(f"no post-condition for {action}")
    add("step_used", 1)
    return expected


def _uint(values: tuple[Any, ...]) -> int:
    return int(values[0])  # bools become 0/1


def _reads(step: PlanStep, request_id: bytes, module: str) -> list[_Read]:
    sid, rid = "0x" + step.step_id.hex(), "0x" + request_id.hex()
    reads = [_read("step_used", module, "stepUsed(bytes32)", "bool", sid, shape=_uint)]
    for key in expected_effects(step):
        if key.startswith("balance:"):
            wallet = key.split(":")[1]
            reads.append(
                _read(key, step.asset, "balanceOf(address)", "uint256", wallet, shape=_uint)
            )
    if step.action is Action.PAY:
        reads += [
            _read("used_today", module, "usedToday(uint8)", "uint256", _PAY, shape=_uint),
            _read("request_paid", module, "requestPaid(bytes32)", "bool", rid, shape=_uint),
        ]
    elif step.action is Action.REFILL:
        reads += [
            _read("used_today", module, "usedToday(uint8)", "uint256", _REFILL, shape=_uint),
            _read(
                "refilled_for",
                module,
                "refilledFor(bytes32,address)",
                "bool",
                rid,
                step.to,
                shape=_uint,
            ),
        ]
    return reads


async def _state(
    rpc: RpcClient, block_hash: str, reads: list[_Read], step: PlanStep, module: str
) -> dict[str, int]:
    pin = {"blockHash": block_hash}
    all_reads = list(reads)
    if step.action in (Action.SUPPLY, Action.WITHDRAW):
        # The aToken address is module state; read it at the same block, then its balance.
        discovery = [_read("a", module, "aToken()", "address")]
        _, found = await _aggregate(rpc, pin, discovery)
        discovered: dict[str, Any] = {}
        missing: list[str] = []
        _fill(discovered, missing, discovery, found)
        if missing:
            raise RpcError("aToken() unreadable")
        safe = step.from_wallet if step.action is Action.SUPPLY else step.to
        all_reads.append(
            _read(
                _atoken(safe),
                discovered["a"],
                "balanceOf(address)",
                "uint256",
                safe,
                shape=_uint,
            )
        )
    data: dict[str, Any] = {}
    missing = []
    _, results = await _aggregate(rpc, pin, all_reads)
    _fill(data, missing, all_reads, results)
    if missing:
        raise RpcError(f"unreadable at {block_hash}: {', '.join(missing)}")
    return {key: int(value) for key, value in data.items()}


async def _concurrent_net(
    rpc: RpcClient, block_hash: str, asset: str, own_tx: str, wallets: set[str]
) -> dict[str, int]:
    """Net transfer effect on ``wallets`` of every asset Transfer in block B outside our own tx."""

    logs = await rpc.call(
        "eth_getLogs",
        [{"blockHash": block_hash, "address": asset, "topics": [_TRANSFER_TOPIC]}],
    )
    net: dict[str, int] = {}
    for log in logs:
        if log.get("removed"):  # reorged out between our reads
            raise RpcError("log removed by a reorg")
        if str(log["transactionHash"]).lower() == own_tx.lower() or len(log["topics"]) != 3:
            continue
        sender, receiver = ("0x" + str(t)[-40:] for t in log["topics"][1:])
        value = int(log["data"], 16)
        if sender.lower() in wallets:
            net[_bal(sender)] = net.get(_bal(sender), 0) - value
        if receiver.lower() in wallets:
            net[_bal(receiver)] = net.get(_bal(receiver), 0) + value
    return net


def compare(
    expected: dict[str, int], observed: dict[str, int], before: dict[str, int]
) -> dict[str, dict[str, int]]:
    diffs = {}
    for key, want in expected.items():
        got = observed[key]
        if key == "used_today":  # observed is the value at B, a floor (see module docstring)
            bad = got < want
        elif key.startswith("atoken:"):
            interest = before[key] * ATOKEN_RATE_NUM // ATOKEN_RATE_DEN
            bad = not want - ATOKEN_ROUNDING <= got <= want + ATOKEN_ROUNDING + interest
        else:
            bad = got != want
        if bad:
            diffs[key] = {"expected": want, "observed": got}
    return diffs


async def compute(
    rpc: RpcClient, step: PlanStep, request_id: bytes, module: str, block: int, own_tx: str
) -> Verification:
    """Raises on any read failure or reorg; the caller maps that to UNKNOWN."""

    header = await rpc.call("eth_getBlockByNumber", [hex(block), False])
    receipt = await rpc.call("eth_getTransactionReceipt", [own_tx])
    if not header or not receipt:
        raise RpcError(f"block {block} or receipt of {own_tx} not found")
    if str(receipt.get("blockHash")).lower() != str(header["hash"]).lower():
        raise RpcError(f"{own_tx} is not in block {block} ({header['hash']}): reorg")
    reads = _reads(step, request_id, module)
    before = await _state(rpc, header["parentHash"], reads, step, module)
    after = await _state(rpc, header["hash"], reads, step, module)
    expected = expected_effects(step)
    wallets = {key.split(":")[1] for key in expected if key.startswith(("balance:", "atoken:"))}
    other = await _concurrent_net(rpc, header["hash"], step.asset.lower(), own_tx, wallets)
    observed = {
        key: after[key] if key == "used_today" else after[key] - before[key] - other.get(key, 0)
        for key in expected
    }
    diffs = compare(expected, observed, before)
    return Verification("DISCREPANCY" if diffs else "PASSED", block, expected, observed, diffs)


class PostConditionVerifier:
    """Verifies the confirmed operation of a plan step and persists the result."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        rpc: RpcClient,
        steps: dict[bytes, PlanStep],
        request_id: bytes,
        module: str,
    ) -> None:
        self._pool, self._rpc, self._steps = pool, rpc, steps
        self._request_id, self._module = request_id, module

    async def verify(self, step_id: bytes, operation_id: uuid.UUID) -> Result:
        """One attempt per call: a failed read stores UNKNOWN and the sequencer counts them."""

        step = self._steps[step_id]
        try:
            tx = await self._pool.fetchrow(
                "SELECT tx_hash, block_number FROM transactions WHERE operation_id = $1 "
                "AND status = 'Confirmed' ORDER BY confirmed_at DESC NULLS LAST LIMIT 1",
                operation_id,
            )
            if tx is None or tx["block_number"] is None:
                raise RpcError("no confirmed transaction")
            verification = await compute(
                self._rpc,
                step,
                self._request_id,
                self._module,
                int(tx["block_number"]),
                "0x" + bytes(tx["tx_hash"]).hex(),
            )
        except (RpcError, OSError, TimeoutError) as error:  # a failed read is never a verdict
            logger.warning("post-condition read failed: %s", error)
            verification = Verification("UNKNOWN", None, {}, {}, {})
        return await self._store(operation_id, verification)

    async def _store(self, operation_id: uuid.UUID, v: Verification) -> Result:
        """Insert once per operation for PASSED/DISCREPANCY (partial unique index); a lost race
        returns the stored verdict and raises no second breaker signal."""

        verification_id = uuid.uuid4()
        async with self._pool.acquire() as connection, connection.transaction():
            inserted = await connection.fetchval(
                "INSERT INTO verifications (id, operation_id, block_number, expected, observed, "
                "diffs, result) VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7) "
                "ON CONFLICT (operation_id) WHERE result <> 'UNKNOWN' DO NOTHING RETURNING id",
                verification_id,
                operation_id,
                v.block_number,
                json.dumps(v.expected),
                json.dumps(v.observed),
                json.dumps(v.diffs),
                v.result,
            )
            if inserted is None:
                existing: Result = await connection.fetchval(
                    "SELECT result FROM verifications WHERE operation_id = $1 "
                    "AND result <> 'UNKNOWN'",
                    operation_id,
                )
                return existing
            if v.result == "DISCREPANCY":
                await connection.execute(
                    "INSERT INTO chain_safety_signals (id, treasury_id, verification_id, "
                    "signal_type, payload) SELECT gen_random_uuid(), treasury_id, $2, "
                    "'CIRCUIT_BREAKER', $3::jsonb FROM operations WHERE id = $1",
                    operation_id,
                    verification_id,
                    json.dumps({"source": "POST_CONDITION_DISCREPANCY", "diffs": v.diffs}),
                )
        return v.result
