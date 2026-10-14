from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from eth_abi import decode, encode
from web3 import Web3

from treasurypilot_worker.chain import rpc as rpc_module
from treasurypilot_worker.chain.rpc import RpcClient, RpcProvider, RpcUnavailable
from treasurypilot_worker.chain.snapshot import (
    MULTICALL3,
    Snapshot,
    SnapshotPurpose,
    SnapshotScope,
    SnapshotTarget,
    is_fresh,
    read_snapshot,
)

ASSET = "0x" + "a1" * 20
MODULE = "0x" + "a2" * 20
SAFE_T = "0x" + "b1" * 20
OP_1 = "0x" + "b2" * 20
OP_2 = "0x" + "b3" * 20
APPROVER = "0x" + "c1" * 20
PAYEE = "0x" + "c2" * 20
POOL = "0x" + "d1" * 20
A_TOKEN = "0x" + "d2" * 20
OWNER = "0x" + "e1" * 20
REQUEST = "0x" + "01" * 32
STEP = "0x" + "02" * 32
FINGERPRINT = "0x" + "03" * 32
BLOCK_HASH = "0x" + "ab" * 32
HEAD_HASH = "0x" + "cd" * 32
TARGET = SnapshotTarget(module=MODULE, asset=ASSET, safe_t=SAFE_T, operational=(OP_1, OP_2))
SCOPE = SnapshotScope(
    approvers=(APPROVER,),
    payees=(PAYEE,),
    request_ids=(REQUEST,),
    step_ids=(STEP,),
    fingerprints=(FINGERPRINT,),
)


def _selector(signature: str) -> bytes:
    return bytes(Web3.keccak(text=signature)[:4])


# (target, signature) -> (output types, builder of output values from decoded call arguments)
Answer = tuple[list[str], Callable[[tuple[Any, ...]], list[Any]]]


class MulticallProvider:
    """Answers eth_call to Multicall3 by running each sub-call against a table."""

    def __init__(self, answers: dict[tuple[str, str], Answer], *, head: int = 100) -> None:
        self.answers = answers
        self.head = head
        self.requests: list[tuple[str, Any]] = []
        self.signatures = {_selector(signature): signature for _, signature in answers}

    async def make_request(self, method: str, params: Any) -> dict[str, Any]:
        self.requests.append((method, params))
        if method == "eth_getBlockByNumber":
            number = self.head if params[0] == "latest" else int(params[0], 16)
            block = {"number": hex(number), "hash": BLOCK_HASH, "timestamp": hex(1_800_000_000)}
            return {"result": block}
        assert method == "eth_call"
        call, block = params
        assert call["to"] == MULTICALL3
        data = bytes.fromhex(call["data"][2:])
        assert data[:4] == _selector("aggregate3((address,bool,bytes)[])")
        ((calls,),) = [decode(["(address,bool,bytes)[]"], data[4:])]
        results = [self._run(target, payload) for target, _, payload in calls]
        return {"result": "0x" + encode(["(bool,bytes)[]"], [results]).hex()}

    def _run(self, target: str, payload: bytes) -> tuple[bool, bytes]:
        signature = self.signatures.get(payload[:4])
        answer = self.answers.get((target.lower(), signature or ""))
        if answer is None:
            return (False, b"")
        inputs = signature[signature.index("(") + 1 : -1].split(",") if signature else []
        args = decode([t for t in inputs if t], payload[4:])
        types, build = answer
        return (True, encode(types, build(args)))


def _answers() -> dict[tuple[str, str], Answer]:
    def const(*values: Any) -> Callable[[tuple[Any, ...]], list[Any]]:
        return lambda _args: list(values)

    answers: dict[tuple[str, str], Answer] = {
        (ASSET, "decimals()"): (["uint8"], const(6)),
        (ASSET, "balanceOf(address)"): (
            ["uint256"],
            lambda args: [{SAFE_T: 1000, OP_1: 110, OP_2: 5, A_TOKEN: 7777}[args[0].lower()]],
        ),
        (MODULE, "status()"): (["uint8"], const(0)),
        (MODULE, "usedToday(uint8)"): (["uint256"], lambda args: [{1: 40, 2: 15}[args[0]]]),
        (MODULE, "bufferOf(address,address)"): (["uint256"], const(10)),
        (MODULE, "targetOf(address,address)"): (["uint256"], const(100)),
        (MODULE, "isApprover(address)"): (["bool"], const(True)),
        (MODULE, "payeeStatus(address)"): (["uint8", "uint64"], const(2, 1_700_000_000)),
        (MODULE, "requestPaid(bytes32)"): (["bool"], const(False)),
        (MODULE, "requestCancelled(bytes32)"): (["bool"], const(True)),
        (MODULE, "stepUsed(bytes32)"): (["bool"], const(False)),
        (MODULE, "fingerprintPaid(bytes32)"): (["bool"], const(True)),
        (MODULE, "refilledFor(bytes32,address)"): (["bool"], const(False)),
        (MODULE, "duplicateAllowedFor(bytes32)"): (["bytes32"], const(b"\x00" * 32)),
        (MODULE, "exceptions(bytes32)"): (
            ["uint128", "uint64", "uint64", "address", "bool"],
            const(500, 1_800_000_500, 3, PAYEE, False),
        ),
        (MODULE, "mandate()"): (
            [
                "(uint64,uint64,uint64,uint32,address,address,(uint128,uint128),(uint128,uint128),uint32,(uint128,uint128))"
            ],
            const(
                (3, 1, 2_000_000_000, 86_400, OWNER, OWNER, (200, 1000), (300, 2000), 600, (0, 0))
            ),
        ),
        (MODULE, "aavePool()"): (["address"], const(POOL)),
        (MODULE, "aToken()"): (["address"], const(A_TOKEN)),
        (POOL, "getReserveData(address)"): (
            [
                "(uint256,uint128,uint128,uint128,uint128,uint128,uint40,uint16,address,address,address,address,uint128,uint128,uint128)"
            ],
            const((0, 1, 30, 1, 45, 0, 5, 1, A_TOKEN, OWNER, OWNER, OWNER, 0, 0, 0)),
        ),
        (POOL, "getUserAccountData(address)"): (
            ["uint256"] * 6,
            const(900, 100, 0, 8000, 7500, 2 * 10**18),
        ),
        (A_TOKEN, "balanceOf(address)"): (["uint256"], const(250)),
    }
    for wallet in (SAFE_T, OP_1, OP_2):
        answers[(wallet, "getOwners()")] = (["address[]"], const([OWNER]))
        answers[(wallet, "getThreshold()")] = (["uint256"], const(1))
        answers[(wallet, "nonce()")] = (["uint256"], const(9))
        answers[(wallet, "getModulesPaginated(address,uint256)")] = (
            ["address[]", "address"],
            const([MODULE], "0x" + "00" * 19 + "01"),
        )
        answers[(wallet, "getStorageAt(uint256,uint256)")] = (["bytes"], const(b"\x00" * 32))
    return answers


def sync(test: Callable[[], Coroutine[Any, Any, None]]) -> Callable[[], None]:
    @functools.wraps(test)
    def run() -> None:
        asyncio.run(test())

    return run


@pytest.fixture(autouse=True)
def no_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rpc_module, "RETRY_BACKOFF_SECONDS", 0)


def _client(provider: Any) -> RpcClient:
    return RpcClient([RpcProvider("fake", provider)])


@sync
async def test_snapshot_reads_the_full_set_at_one_pinned_block() -> None:
    provider = MulticallProvider(_answers())

    snapshot = await read_snapshot(
        _client(provider), TARGET, SnapshotPurpose.PLAN, SCOPE, coverage="COMPLETE"
    )

    assert (snapshot.block_number, snapshot.block_hash) == (100, BLOCK_HASH)
    assert snapshot.block_timestamp == datetime.fromtimestamp(1_800_000_000, UTC)
    assert snapshot.provider == "fake"
    assert (snapshot.coverage, snapshot.missing) == ("COMPLETE", ())
    data = snapshot.data
    assert data["balances"] == {SAFE_T: "1000", OP_1: "110", OP_2: "5"}
    assert data["asset"]["decimals"] == 6
    assert data["module"]["used_today"] == {"PAY": "40", "REFILL": "15"}
    assert data["module"]["mandate"]["pay"] == {"per_request": "200", "daily": "1000"}
    assert data["module"]["mandate"]["version"] == 3
    assert data["module"]["approvers"] == {APPROVER: True}
    assert data["payees"] == {PAYEE: {"state": 2, "active_from": 1_700_000_000}}
    assert data["requests"][REQUEST]["cancelled"] is True
    assert data["requests"][REQUEST]["exception"]["amount"] == "500"
    assert data["fingerprints"][FINGERPRINT]["paid"] is True
    assert data["safes"][SAFE_T] == {
        "owners": [OWNER],
        "threshold": 1,
        "nonce": 9,
        "modules": [MODULE],
        "guard": None,
    }
    assert data["aave"] == {
        "pool": POOL,
        "a_token": A_TOKEN,
        "a_token_balance": "250",
        "available_liquidity": "7777",
        "reserve": {"liquidity_rate": "30", "variable_borrow_rate": "45"},
        "account": {
            "total_collateral_base": "900",
            "total_debt_base": "100",
            "health_factor": str(2 * 10**18),
        },
    }
    # Every state read is pinned to the block header's hash (EIP-1898), never "latest".
    pins = {params[1]["blockHash"] for method, params in provider.requests if method == "eth_call"}
    assert pins == {BLOCK_HASH}


@sync
async def test_failed_subcalls_are_listed_as_missing_but_the_snapshot_is_returned() -> None:
    answers = _answers()
    del answers[(MODULE, "mandate()")]
    del answers[(OP_1, "nonce()")]
    # Out of range for uint8: undecodable data is a failed read, not a default value.
    answers[(MODULE, "status()")] = (["uint256"], lambda _args: [300])

    snapshot = await read_snapshot(
        _client(MulticallProvider(answers)), TARGET, SnapshotPurpose.PRE_STEP, SCOPE
    )

    assert set(snapshot.missing) == {
        "module.mandate",
        "module.status",
        f"safes.{OP_1}.nonce",
    }
    assert "mandate" not in snapshot.data["module"]
    assert snapshot.data["balances"][SAFE_T] == "1000"
    # A missing Safe read means the Safe configuration cannot be vouched for.
    assert snapshot.coverage == "UNKNOWN"


@sync
async def test_missing_aave_pool_skips_aave_and_a_bad_reserve_is_missing() -> None:
    answers = _answers()
    answers[(MODULE, "aavePool()")] = (["address"], lambda _args: ["0x" + "00" * 20])
    without_aave = await read_snapshot(
        _client(MulticallProvider(answers)), TARGET, SnapshotPurpose.DASHBOARD
    )
    assert "aave" not in without_aave.data
    assert without_aave.missing == ()

    answers = _answers()
    reserve = answers[(POOL, "getReserveData(address)")]
    answers[(POOL, "getReserveData(address)")] = (
        reserve[0],
        lambda _args: [(0, 1, 30, 1, 45, 0, 5, 1, "0x" + "ee" * 20, OWNER, OWNER, OWNER, 0, 0, 0)],
    )
    wrong_token = await read_snapshot(
        _client(MulticallProvider(answers)), TARGET, SnapshotPurpose.DASHBOARD
    )
    assert wrong_token.missing == ("aave.reserve",)


@sync
async def test_unreachable_rpc_raises_instead_of_returning_defaults() -> None:
    class Down:
        async def make_request(self, method: str, params: Any) -> dict[str, Any]:
            raise ConnectionError("refused")

    with pytest.raises(RpcUnavailable):
        await read_snapshot(_client(Down()), TARGET, SnapshotPurpose.PLAN)


def _snapshot(number: int, age_seconds: int, now: datetime) -> Snapshot:
    return Snapshot(
        purpose=SnapshotPurpose.PLAN,
        block_number=number,
        block_hash=BLOCK_HASH,
        block_timestamp=now - timedelta(seconds=age_seconds),
        provider="fake",
        data={},
        coverage="COMPLETE",
        missing=(),
    )


def test_is_fresh_needs_both_30_seconds_and_2_blocks() -> None:
    now = datetime(2026, 10, 15, tzinfo=UTC)
    assert is_fresh(_snapshot(100, 30, now), now, head=102)
    assert not is_fresh(_snapshot(100, 0, now), now, head=103)  # 3 blocks behind
    assert not is_fresh(_snapshot(100, 31, now), now, head=100)  # 31 s old
