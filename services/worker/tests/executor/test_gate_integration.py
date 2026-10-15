"""PlanGate with the real validator, simulator and sequencer against PostgreSQL (EXE-008)."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data

from treasurypilot_core.eip712 import payment_approval_typed_data
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import (
    Action,
    ApprovalView,
    ExecutionPlan,
    PlanStep,
    RequestView,
    validate_step,
)
from treasurypilot_worker.chain.snapshot import Snapshot, SnapshotPurpose
from treasurypilot_worker.executor.gate import PlanGate
from treasurypilot_worker.executor.sequencer import PlanRun, sequence_plan
from treasurypilot_worker.executor.simulation import SimulationContext
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.planner.context import ContextInputs, build_context

_spec = importlib.util.spec_from_file_location(
    "sequencer_fixtures", Path(__file__).with_name("test_sequencer_integration.py")
)
assert _spec and _spec.loader
_seq = importlib.util.module_from_spec(_spec)
sys.modules["sequencer_fixtures"] = _seq
_spec.loader.exec_module(_seq)
database_url = _seq.database_url  # the fixture: migrated schema with the seeded treasury
_new_run, _sql, _tracker_says, FakeSigner = (
    _seq._new_run,
    _seq._sql,
    _seq._tracker_says,
    _seq.FakeSigner,
)

CHAIN = _seq.CHAIN_ID
TREASURY = "0x" + "11" * 20
SAFE_T, WALLET, PAYEE, ASSET = ("0x" + c * 20 for c in ("22", "33", "44", "55"))
EXECUTOR = "0x" + "66" * 20
APPROVER = Account.from_key("0x" + "7a" * 32)
MAKER, CHECKER = uuid.UUID(int=1), uuid.UUID(int=2)
FEES = {"maxFeePerGas": 1, "maxPriorityFeePerGas": 1, "feeCapWei": 1}


class FakeRpc:
    def __init__(self, head: int) -> None:
        self.head = head
        self.calls: list[str] = []

    async def call(self, method: str, params: Any, **_: Any) -> Any:
        self.calls.append(method)
        return {"eth_blockNumber": hex(self.head), "eth_getCode": "0x60", "eth_call": "0x"}[method]


def _snapshot(block: int, *, wallet_balance: int, refilled: bool) -> Snapshot:
    rid, fp = "0x" + "ab" * 32, "0x" + "cd" * 32
    steps = {"0x" + _STEP_IDS[i].hex(): {"used": i == 0 and refilled} for i in range(2)}
    data = {
        "module": {
            "mandate": {
                "version": 1,
                "valid_from": 0,
                "expires_at": 2**40,
                "executor": EXECUTOR,
                "pay": {"per_request": "2000", "daily": "10000"},
                "refill": {"per_request": "2500", "daily": "12000"},
                "supply": {"per_request": "1000", "daily": "10000"},
            },
            "status": 0,
            "used_today": {"PAY": "0", "REFILL": "0"},
            "approvers": {APPROVER.address.lower(): True},
        },
        "balances": {SAFE_T: "5000", WALLET: str(wallet_balance)},
        "buffers": {SAFE_T: "100", WALLET: "50"},
        "targets": {SAFE_T: "0", WALLET: "100"},
        "payees": {PAYEE: {"state": 2, "active_from": 0}},
        "requests": {
            rid: {
                "paid": False,
                "cancelled": False,
                "exception": {
                    "amount": "0",
                    "expiry": 0,
                    "mandate_version": 0,
                    "payee": PAYEE,
                    "used": False,
                },
                "refilled": {WALLET: refilled},
            }
        },
        "steps": steps,
        "fingerprints": {fp: {"paid": False, "allowed_for": "0x" + "00" * 32}},
    }
    return Snapshot(
        SnapshotPurpose.PRE_STEP,
        block,
        "0x" + "ee" * 32,
        datetime.now(UTC),
        "fake",
        data,
        "COMPLETE",
        (),
    )


_STEP_IDS: list[bytes] = []


def _inputs(request_id: bytes) -> ContextInputs:
    request = RequestView(
        request_id=request_id,
        status="Approved",
        invoice_hash=b"\x01" * 32,
        fingerprint=b"\xcd" * 32,
        terms_hash=b"\x03" * 32,
        paying_wallet=WALLET,
        payee=PAYEE,
        amount=BaseUnits(1000),
        fiat_amount_minor_units=None,
        early_amount=BaseUnits(0),
        early_pay_by=0,
        deadline=2**40,
    )
    typed = {
        "requestId": "0x" + request_id.hex(),
        "invoiceHash": "0x" + request.invoice_hash.hex(),
        "fingerprint": "0x" + request.fingerprint.hex(),
        "treasury": TREASURY,
        "payingWallet": WALLET,
        "asset": ASSET,
        "payee": PAYEE,
        "amount": 1000,
        "earlyAmount": 0,
        "earlyPayBy": 0,
        "deadline": 2**40,
        "termsHash": "0x" + request.terms_hash.hex(),
        "expiry": 2**40,
        "isFiat": False,
    }
    full = payment_approval_typed_data(typed, chain_id=CHAIN, verifying_contract=TREASURY)
    signature = bytes(APPROVER.sign_message(encode_typed_data(full_message=full)).signature)
    approval = ApprovalView(
        typed=typed,
        signature=signature,
        signer=APPROVER.address,
        approved_at=datetime.fromtimestamp(time.time() - 3600, UTC),
        created_by=MAKER,
        last_edited_by=MAKER,
        approved_by_user=CHECKER,
        acknowledged_flag_ids=(),
        solo_mode=False,
    )
    return ContextInputs(
        chain_id=CHAIN,
        safe_t=SAFE_T,
        asset=ASSET,
        executor=EXECUTOR,
        request=request,
        approval=approval,
        fingerprint=b"\xcd" * 32,
        screening_clear=True,
    )


def _simulation(inputs: ContextInputs) -> SimulationContext:
    message = {
        "planHash": "0x" + "00" * 32,
        "requestId": "0x" + "ab" * 32,
        "stepIds": [],
        "stepAmounts": [],
        "policyVersion": "0x" + "00" * 32,
        "executor": EXECUTOR,
        "validUntil": 2**40,
        "nonce": 1,
        "evidenceDigest": "0x" + "00" * 32,
    }
    assert inputs.approval
    return SimulationContext(
        EXECUTOR,
        TREASURY,
        message,
        b"\x01" * 65,
        b"\x00" * 32,
        0,
        inputs.approval.typed,
        inputs.approval.signature,
    )


def _plan(run: PlanRun) -> ExecutionPlan:
    refill, pay = run.steps
    return ExecutionPlan(
        request_id=b"\xab" * 32,
        treasury=TREASURY,
        chain_id=CHAIN,
        steps=[
            PlanStep(
                seq=0,
                step_id=refill.step_id,
                action=Action.REFILL,
                from_wallet=SAFE_T,
                to=WALLET,
                asset=ASSET,
                amount=BaseUnits(950),
            ),
            PlanStep(
                seq=1,
                step_id=pay.step_id,
                action=Action.PAY,
                from_wallet=WALLET,
                to=PAYEE,
                asset=ASSET,
                amount=BaseUnits(1000),
            ),
        ],
        planner_source="DETERMINISTIC",
        evidence_ids=[],
    )


def test_wallet_balance_change_between_refill_and_pay_is_blocked(database_url: str) -> None:
    async def scenario() -> None:
        run = await _new_run(database_url)
        _STEP_IDS[:] = [s.step_id for s in run.steps]
        plan, inputs, rpc = _plan(run), _inputs(b"\xab" * 32), FakeRpc(head=101)
        snapshots = [
            _snapshot(100, wallet_balance=100, refilled=False),  # before the refill
            # After the refill the wallet holds 1050; 150 left it before the PAY was validated.
            _snapshot(100, wallet_balance=900, refilled=True),
        ]
        pool = await create_worker_pool(database_url, min_size=1, max_size=3)

        async def snapshot_fn(scope: Any) -> Snapshot:
            assert "0x" + "ab" * 32 in scope.request_ids and PAYEE in scope.payees
            return snapshots.pop(0)

        async def no_renewal(seq: int) -> Any:
            raise AssertionError("not expired")

        gate = PlanGate(
            pool, rpc, run.plan_id, plan, inputs, _simulation(inputs), no_renewal, snapshot_fn
        )  # type: ignore[arg-type]
        signer = FakeSigner()
        try:
            assert (await sequence_plan(pool, signer, run, gate)).status == "Waiting"
            assert signer.calls == 1  # REFILL validated (ALLOW), simulated and sent
            await pool.execute(
                "UPDATE operations SET status = 'Confirmed' WHERE step_id = $1",
                run.steps[0].step_id,
            )
            result = await sequence_plan(pool, signer, run, gate)
            assert (result.status, result.code) == ("PartiallyCompleted", "BUFFER_BREACH")
            assert signer.calls == 1
            rows = await pool.fetch(
                "SELECT step_seq, stage, decision, primary_code FROM validations "
                "WHERE plan_id = $1 ORDER BY step_seq, stage",
                run.plan_id,
            )
            assert [(r["step_seq"], r["stage"], r["decision"]) for r in rows] == [
                (0, "PRE_STEP", "ALLOW"),
                (0, "SIMULATION", "ALLOW"),
                (1, "PRE_STEP", "BLOCK"),
            ]
            assert rows[2]["primary_code"] == "BUFFER_BREACH"
            assert rpc.calls.count("eth_call") == 1  # the blocked step was never simulated
        finally:
            await pool.close()

    asyncio.run(scenario())


def test_lagging_snapshot_is_stale() -> None:
    run_steps = [b"\x01" * 32, b"\x02" * 32]
    _STEP_IDS[:] = run_steps
    plan = ExecutionPlan(
        request_id=b"\xab" * 32, treasury=TREASURY, chain_id=CHAIN,
        steps=[PlanStep(seq=0, step_id=run_steps[0], action=Action.PAY, from_wallet=WALLET, to=PAYEE, asset=ASSET, amount=BaseUnits(1000))],
        planner_source="DETERMINISTIC", evidence_ids=[],
    )  # fmt: skip
    old = _snapshot(100, wallet_balance=1050, refilled=False)
    context = build_context(old, plan, _inputs(b"\xab" * 32), now=int(time.time()), head_block=105)
    decision = validate_step(plan, 0, context)
    assert decision.decision == "BLOCK" and "SNAPSHOT_STALE" in map(str, decision.codes)
