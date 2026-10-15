"""POL-007: the pre-signing eth_call, against a fake RPC and a real Anvil node."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
import uuid
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from eth_abi import decode

from treasurypilot_core.domain.models import BaseUnits
from treasurypilot_core.eip712 import PAYMENT_APPROVAL_TYPE, PLAN_ATTESTATION_TYPE
from treasurypilot_core.policy import (
    REASON_CODES,
    Action,
    PlanStep,
    PolicyReasonCode,
    decode_revert,
    error_selector,
)
from treasurypilot_core.policy import PolicyReasonCode as C
from treasurypilot_worker.chain import rpc as rpc_module
from treasurypilot_worker.chain.rpc import RpcClient, RpcProvider, build_rpc_client
from treasurypilot_worker.executor.simulation import (
    SimulationContext,
    build_calldata,
    record_validation,
    simulate,
)
from treasurypilot_worker.locks import create_worker_pool

EXECUTOR = "0x" + "e1" * 20
TARGET = "0x" + "e2" * 20
WALLET = "0x" + "b2" * 20
STEP_ID = bytes.fromhex("5e" * 32)
# keccak("NotApprover()")[:4]
NOT_APPROVER = "0x65f84cc0"
APPROVAL = {
    "requestId": "0x" + "01" * 32,
    "invoiceHash": "0x" + "02" * 32,
    "fingerprint": "0x" + "03" * 32,
    "treasury": TARGET,
    "payingWallet": WALLET,
    "asset": "0x" + "a1" * 20,
    "payee": "0x" + "c1" * 20,
    "amount": 100,
    "earlyAmount": 0,
    "earlyPayBy": 0,
    "deadline": 2_000_000_000,
    "termsHash": "0x" + "04" * 32,
    "expiry": 2_000_000_000,
    "isFiat": False,
}
ATTESTATION = {
    "planHash": "0x" + "05" * 32,
    "requestId": "0x" + "01" * 32,
    "stepIds": ["0x" + STEP_ID.hex()],
    "stepAmounts": [90],
    "policyVersion": "0x" + "06" * 32,
    "executor": EXECUTOR,
    "validUntil": 2_000_000_000,
    "nonce": 7,
    "evidenceDigest": "0x" + "07" * 32,
}
CTX = SimulationContext(
    executor=EXECUTOR,
    target=TARGET,
    attestation=ATTESTATION,
    attestation_signature=b"\x11" * 65,
    policy_version=b"\x06" * 32,
    snapshot_block=42,
    approval=APPROVAL,
    approver_signature=b"\x22" * 64,
    travel_rule_clear=True,
)


def _step(action: Action) -> PlanStep:
    return PlanStep(
        seq=1,
        step_id=STEP_ID,
        action=action,
        from_wallet="0x" + "b1" * 20,
        to=WALLET,
        asset="0x" + "a1" * 20,
        amount=BaseUnits(90),
        min_out=BaseUnits(80) if action is Action.SWAP else None,
        venue="TEST_ROUTER" if action is Action.SWAP else None,
    )


class FakeNode:
    def __init__(
        self, *, error: dict[str, Any] | None = None, down: bool = False, code: str = "0x00"
    ) -> None:
        self.error, self.down, self.code = error, down, code
        self.requests: list[tuple[str, Any]] = []

    async def make_request(self, method: str, params: Any) -> dict[str, Any]:
        self.requests.append((method, params))
        if self.down:
            raise ConnectionError("refused")
        if method == "eth_getCode":
            return {"jsonrpc": "2.0", "id": 1, "result": self.code}
        return {
            "jsonrpc": "2.0",
            "id": 1,
            **({"error": self.error} if self.error else {"result": "0x"}),
        }


def _client(node: FakeNode) -> RpcClient:
    return RpcClient([RpcProvider("p", node)])


@pytest.fixture(autouse=True)
def no_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rpc_module, "RETRY_BACKOFF_SECONDS", 0)


# Function selectors from `cast sig` on PlanAttestedExecutor's signatures, not recomputed here.
@pytest.mark.parametrize(
    ("action", "selector"),
    [
        (Action.PAY, "88e7aeaf"),
        (Action.REFILL, "c6ad3596"),
        (Action.WITHDRAW, "eb371d41"),
        (Action.SUPPLY, "6453ca48"),
    ],
)
def test_calldata_targets_the_executor_function_for_the_action(
    action: Action, selector: str
) -> None:
    assert build_calldata(_step(action), CTX)[:4].hex() == selector


def test_pay_and_refill_need_their_approval() -> None:
    bare = SimulationContext(**{**CTX.__dict__, "approval": None})
    with pytest.raises(ValueError, match="approval"):
        build_calldata(_step(Action.PAY), bare)


def test_pay_calldata_carries_the_fresh_plan_amount_separately_from_the_approval_cap() -> None:
    calldata = build_calldata(_step(Action.PAY), CTX)
    approval = "(" + ",".join(field["type"] for field in PAYMENT_APPROVAL_TYPE) + ")"
    attestation = "(" + ",".join(field["type"] for field in PLAN_ATTESTATION_TYPE) + ")"
    decoded = decode([approval, "bytes", "bytes32", "uint256", attestation, "bytes"], calldata[4:])

    assert decoded[0][7] == 100  # signed approver maximum
    assert decoded[3] == 90  # amount proposed by the fresh quote


def test_an_already_approved_pay_is_blocked_until_travel_rule_preflight_clears() -> None:
    node = FakeNode()
    # The approval payload and signature are present, but do not substitute for Travel Rule clearance.
    context = replace(CTX, travel_rule_clear=False)

    decision = asyncio.run(simulate(_client(node), _step(Action.PAY), context))

    assert (decision.decision, decision.codes, decision.primary, decision.stage) == (
        "BLOCK",
        [C.DATA_MISSING],
        C.DATA_MISSING,
        "SIMULATION",
    )
    assert decision.checks[0].name == "travel_rule_clear"
    assert node.requests == []


def test_a_clean_call_is_allowed_and_runs_from_the_executor_at_latest() -> None:
    node = FakeNode()
    decision = asyncio.run(simulate(_client(node), _step(Action.REFILL), CTX))
    assert (decision.decision, decision.codes, decision.stage, decision.step_seq) == (
        "ALLOW",
        [],
        "SIMULATION",
        1,
    )
    (method, (call, block)) = node.requests[1]
    assert (method, block, call["from"], call["to"]) == ("eth_call", "latest", EXECUTOR, TARGET)
    assert call["data"] == "0x" + build_calldata(_step(Action.REFILL), CTX).hex()


def test_a_known_revert_blocks_with_the_decoded_code() -> None:
    # M08 §8.5 example 12: the approver was removed one block ago.
    node = FakeNode(error={"code": 3, "message": "execution reverted", "data": NOT_APPROVER})
    decision = asyncio.run(simulate(_client(node), _step(Action.PAY), CTX))
    assert decision.decision == "BLOCK"
    assert decision.codes == [C.SIMULATION_REVERTED, C.NOT_IN_APPROVER_SET]
    assert decision.primary == C.NOT_IN_APPROVER_SET  # catalogue precedence


def test_an_unknown_or_empty_revert_is_still_simulation_reverted() -> None:
    for error in (
        {"code": 3, "message": "execution reverted", "data": "0xdeadbeef"},
        {"code": 3, "message": "execution reverted"},
    ):
        decision = asyncio.run(simulate(_client(FakeNode(error=error)), _step(Action.PAY), CTX))
        assert (decision.decision, decision.codes) == ("BLOCK", [C.SIMULATION_REVERTED])


def test_a_revert_on_the_first_provider_is_not_failed_over_into_allow() -> None:
    reverting = FakeNode(error={"code": 3, "message": "execution reverted", "data": NOT_APPROVER})
    succeeding = FakeNode()
    client = RpcClient([RpcProvider("a", reverting), RpcProvider("b", succeeding)])
    decision = asyncio.run(simulate(client, _step(Action.PAY), CTX))
    assert decision.decision == "BLOCK"
    assert C.SIMULATION_REVERTED in decision.codes
    assert "eth_call" not in [m for m, _ in succeeding.requests]


def test_non_hex_revert_data_blocks_instead_of_crashing() -> None:
    node = FakeNode(error={"code": 3, "message": "execution reverted", "data": "0xzz"})
    decision = asyncio.run(simulate(_client(node), _step(Action.PAY), CTX))
    assert (decision.decision, decision.codes) == ("BLOCK", [C.SIMULATION_REVERTED])


def test_a_target_without_code_blocks_as_unavailable() -> None:
    decision = asyncio.run(simulate(_client(FakeNode(code="0x")), _step(Action.PAY), CTX))
    assert (decision.decision, decision.codes) == ("BLOCK", [C.SIMULATION_UNAVAILABLE])


def test_an_unreachable_rpc_blocks_as_simulation_unavailable() -> None:
    decision = asyncio.run(simulate(_client(FakeNode(down=True)), _step(Action.PAY), CTX))
    assert (decision.decision, decision.codes) == ("BLOCK", [C.SIMULATION_UNAVAILABLE])


def test_a_non_revert_rpc_error_is_unavailable_not_reverted() -> None:
    node = FakeNode(error={"code": -32005, "message": "rate limited"})
    decision = asyncio.run(simulate(_client(node), _step(Action.PAY), CTX))
    assert decision.codes == [C.SIMULATION_UNAVAILABLE]


# --- Anvil ---

API_ROOT = Path(__file__).parents[3] / "api"
MODULE_ERRORS = sorted({e for r in REASON_CODES.values() for e in r.contract_errors})


def _rpc(url: str, method: str, params: list[object]) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.load(response)
    assert "error" not in payload, payload
    return payload["result"]


@pytest.fixture(scope="module")
def anvil_url() -> Iterator[str]:
    if "TP_TEST_ANVIL_URL" in os.environ:
        yield os.environ["TP_TEST_ANVIL_URL"]
        return
    if shutil.which("anvil") is None:
        pytest.skip("anvil is required for the simulation integration test")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    process = subprocess.Popen(
        ["anvil", "--silent", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                _rpc(url, "eth_chainId", [])
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("anvil did not start")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=5)


def _install(url: str, runtime: str) -> None:
    _rpc(url, "anvil_setCode", [TARGET, "0x" + runtime])


def _reverting_with(error: str) -> str:
    # PUSH32 selector-word; PUSH0; MSTORE; PUSH1 4; PUSH0; REVERT
    return "7f" + (error_selector(error).hex() + "00" * 28) + "5f5260045ffd"


def _simulate(url: str, action: Action = Action.PAY) -> Any:
    return asyncio.run(simulate(build_rpc_client([url]), _step(action), CTX))


@pytest.mark.parametrize("error", MODULE_ERRORS)
def test_every_module_error_blocks_with_its_decoded_code(anvil_url: str, error: str) -> None:
    _install(anvil_url, _reverting_with(error))
    decision = _simulate(anvil_url)
    expected = decode_revert(error_selector(error))
    assert decision.decision == "BLOCK"
    assert tuple(decision.codes) == expected
    assert len(expected) == 2, f"{error} is not mapped to a reason code"


def test_a_succeeding_call_is_allowed_for_every_action(anvil_url: str) -> None:
    _install(anvil_url, "00")  # STOP
    for action in Action:
        assert _simulate(anvil_url, action).decision == "ALLOW"


def test_an_unreachable_node_blocks_as_unavailable() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    decision = _simulate(f"http://127.0.0.1:{port}")
    assert (decision.decision, decision.codes) == (
        "BLOCK",
        [PolicyReasonCode.SIMULATION_UNAVAILABLE],
    )


def test_the_decision_is_stored_as_an_append_only_validations_row(anvil_url: str) -> None:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required to store validations")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        _store_and_check(url, anvil_url)
    finally:
        command.downgrade(config, "base")


def _store_and_check(url: str, anvil_url: str) -> None:
    _install(anvil_url, _reverting_with("NotApprover()"))
    decision = _simulate(anvil_url)
    plan_id = uuid.uuid4()

    async def run() -> Any:
        pool = await create_worker_pool(url, min_size=1, max_size=1)
        try:
            await record_validation(pool, plan_id, decision)
            row = await pool.fetchrow("SELECT * FROM validations WHERE plan_id = $1", plan_id)
            with pytest.raises(Exception, match="append-only"):
                await pool.execute("DELETE FROM validations WHERE plan_id = $1", plan_id)
            return row
        finally:
            await pool.close()

    row = asyncio.run(run())
    assert (row["stage"], row["decision"], row["primary_code"], row["step_seq"]) == (
        "SIMULATION",
        "BLOCK",
        "NOT_IN_APPROVER_SET",
        1,
    )
    assert row["reason_codes"] == ["SIMULATION_REVERTED", "NOT_IN_APPROVER_SET"]
    assert bytes(row["policy_version"]) == CTX.policy_version and row["snapshot_block"] == 42
    assert json.loads(row["checks"])[0]["name"] == "simulation"


def test_swap_for_gas_calldata_matches_the_shared_vector() -> None:
    """The Foundry test executes this exact calldata on the real module (SwapForGasCalldata.t.sol)."""
    vector = json.loads(
        (
            Path(__file__).parents[4] / "contracts/test/vectors/swap-for-gas-calldata.json"
        ).read_text()
    )
    step = _step(Action.SWAP).model_copy(
        update={
            "step_id": bytes.fromhex(vector["stepId"][2:]),
            "amount": BaseUnits(int(vector["amountIn"])),
            "min_out": BaseUnits(int(vector["minOut"])),
        }
    )

    assert "0x" + build_calldata(step, CTX).hex() == vector["calldata"]


def test_a_swap_step_without_min_out_cannot_be_encoded() -> None:
    step = _step(Action.SWAP).model_copy(update={"min_out": None})

    with pytest.raises(ValueError, match="minOut"):
        build_calldata(step, CTX)
