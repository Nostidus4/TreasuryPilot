"""Step sequencing against PostgreSQL with a fake signer, gate and tracker (EXE-008)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config

from treasurypilot_api.recovery.review_queue import ReviewType, route_for
from treasurypilot_core.engine.swap_quote import QuoteRejected
from treasurypilot_core.policy import Check, Decision, PolicyReasonCode
from treasurypilot_worker.executor.outbox import SignerRefused, SignerUnavailable, StepExecution
from treasurypilot_worker.executor.sequencer import PlanRun, _route, sequence_plan
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.reconcile.verify import PostConditionVerifier
from treasurypilot_worker.recovery.partial import cancel_partial, resume_partial

# Tests run in importlib mode, so the sibling module is loaded by path.
_spec = importlib.util.spec_from_file_location(
    "outbox_fixtures", Path(__file__).with_name("test_outbox_integration.py")
)
assert _spec and _spec.loader
_outbox = importlib.util.module_from_spec(_spec)
sys.modules["outbox_fixtures"] = _outbox
_spec.loader.exec_module(_outbox)
_ORG = _outbox._ORG
_PAYEE = _outbox._PAYEE
_TREASURY = _outbox._TREASURY
_VENDOR = _outbox._VENDOR
API_ROOT = _outbox.API_ROOT
CHAIN_ID = _outbox.CHAIN_ID
FakeSigner = _outbox.FakeSigner
_seed = _outbox._seed

_ASSET = "00000000-0000-7000-8000-000000000030"

_verify_spec = importlib.util.spec_from_file_location(
    "verify_fixtures", Path(__file__).parents[1] / "reconcile" / "test_verify.py"
)
assert _verify_spec and _verify_spec.loader
_verify = importlib.util.module_from_spec(_verify_spec)
sys.modules["verify_fixtures"] = _verify
_verify_spec.loader.exec_module(_verify)


def _decision(outcome: str, code: PolicyReasonCode | None = None) -> Decision:
    return Decision(
        decision=outcome,  # type: ignore[arg-type]
        primary=code,
        codes=[code] if code else [],
        warnings=[],
        checks=[Check(name="t", passed=False, code=code, expected=None, observed=None)]
        if code
        else [],
        stage="PRE_STEP",
        step_seq=1,
        policy_version=b"\x01" * 32,
        snapshot_block=1,
    )


class FakeGate:
    def __init__(self) -> None:
        self.checked: list[int] = []
        self.reattested: list[int] = []
        self.verdict = _decision("ALLOW")
        self.renewed: PlanRun | Decision | None = None

    async def pre_step(self, seq: int) -> Decision:
        self.checked.append(seq)
        return self.verdict

    async def reattest(self, seq: int) -> PlanRun | Decision:
        self.reattested.append(seq)
        assert self.renewed is not None
        return self.renewed


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for the sequencer integration tests")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed(url))
        yield url
    finally:
        command.downgrade(config, "base")


def _step(request: uuid.UUID, kind: str) -> StepExecution:
    step_id = uuid.uuid4().bytes * 2
    return StepExecution(
        treasury_id=_TREASURY,
        request_id=request,
        plan_step_id=uuid.uuid4(),
        step_id=step_id,
        kind=kind,
        chain_id=CHAIN_ID,
        sign_request={
            "treasuryId": str(_TREASURY),
            "plan": {"steps": [{"stepId": "0x" + step_id.hex()}]},
            "stepSeq": 0,
            "payload": {"to": "0x" + "33" * 20, "data": "0xdeadbeef"},
        },
    )


async def _new_run(
    url: str,
    valid_for: timedelta = timedelta(minutes=5),
    kinds: tuple[str, ...] = ("REFILL", "PAY"),
) -> PlanRun:
    pool = await create_worker_pool(url, min_size=1, max_size=1)
    request = uuid.uuid4()
    try:
        await pool.execute(
            "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, "
            "payee_id, invoice_no, issue_date, due_at, amount, asset_id, status, fingerprint) VALUES "
            "($1, $2, $3, $4, $5, $6, $7, '2026-10-01', '2026-10-31', 1000, $8, 'Preparing', $9)",
            request,
            uuid.UUID(_ORG),
            _TREASURY,
            CHAIN_ID,
            uuid.UUID(_VENDOR),
            uuid.UUID(_PAYEE),
            "SEQ-" + request.hex,
            uuid.UUID(_ASSET),
            request.bytes * 2,
        )
    finally:
        await pool.close()
    steps = tuple(_step(request, kind) for kind in kinds)
    return PlanRun(uuid.uuid4(), request, steps, datetime.now(UTC) + valid_for)


class _Passed:
    async def verify(self, step_id: bytes, operation_id: uuid.UUID) -> str:
        return "PASSED"


async def _go(url: str, signer: FakeSigner, run: PlanRun, gate: FakeGate, **kw: Any) -> Any:
    pool = await create_worker_pool(url, min_size=1, max_size=2)
    kw.setdefault("verifier", _Passed())
    try:
        return await sequence_plan(pool, signer, run, gate, **kw)
    finally:
        await pool.close()


async def _sql(url: str, query: str, *args: Any) -> list[Any]:
    pool = await create_worker_pool(url, min_size=1, max_size=1)
    try:
        return list(await pool.fetch(query, *args))
    finally:
        await pool.close()


def _tracker_says(url: str, step: StepExecution, status: str) -> None:
    asyncio.run(
        _sql(
            url,
            "UPDATE operations SET status = $2::operation_status WHERE step_id = $1",
            step.step_id,
            status,
        )
    )


def _request_status(url: str, run: PlanRun) -> str:
    rows = asyncio.run(
        _sql(url, "SELECT status FROM payment_requests WHERE id = $1", run.request_id)
    )
    return str(rows[0]["status"])


def test_steps_run_in_order_and_pay_confirmation_marks_paid(database_url: str) -> None:
    run, signer, gate = asyncio.run(_new_run(database_url)), FakeSigner(), FakeGate()

    assert asyncio.run(_go(database_url, signer, run, gate)).status == "Waiting"
    assert signer.calls == 1 and gate.checked == [0]
    # The previous step is still Submitted: the next step is neither validated nor sent.
    assert asyncio.run(_go(database_url, signer, run, gate)).status == "Waiting"
    assert signer.calls == 1 and gate.checked == [0]

    _tracker_says(database_url, run.steps[0], "Confirmed")
    assert asyncio.run(_go(database_url, signer, run, gate)).status == "Waiting"
    assert signer.calls == 2 and gate.checked == [0, 1]  # re-validated before step 1
    assert _request_status(database_url, run) == "Paying"

    _tracker_says(database_url, run.steps[1], "Confirmed")
    assert asyncio.run(_go(database_url, signer, run, gate)).status == "Completed"
    assert _request_status(database_url, run) == "Paid"


def test_a_plan_with_a_swap_for_gas_step_runs_it_first_and_completes(database_url: str) -> None:
    run = asyncio.run(_new_run(database_url, kinds=("SWAP", "REFILL", "PAY")))
    signer, gate = FakeSigner(), FakeGate()

    for index, step in enumerate(run.steps):
        assert asyncio.run(_go(database_url, signer, run, gate)).status == "Waiting"
        assert gate.checked == list(range(index + 1)) and signer.calls == index + 1
        _tracker_says(database_url, step, "Confirmed")
    assert asyncio.run(_go(database_url, signer, run, gate)).status == "Completed"
    kinds = asyncio.run(
        _sql(
            database_url,
            "SELECT kind FROM operations WHERE request_id = $1 ORDER BY created_at",
            run.request_id,
        )
    )
    assert [str(row["kind"]) for row in kinds] == ["SWAP", "REFILL", "PAY"]
    assert _request_status(database_url, run) == "Paid"


def test_a_request_plan_with_a_leading_withdraw_runs_it_first_and_completes(
    database_url: str,
) -> None:
    run = asyncio.run(_new_run(database_url, kinds=("WITHDRAW", "REFILL", "PAY")))
    signer, gate = FakeSigner(), FakeGate()

    for index, step in enumerate(run.steps):
        assert asyncio.run(_go(database_url, signer, run, gate)).status == "Waiting"
        assert gate.checked == list(range(index + 1)) and signer.calls == index + 1
        _tracker_says(database_url, step, "Confirmed")
    assert asyncio.run(_go(database_url, signer, run, gate)).status == "Completed"
    kinds = asyncio.run(
        _sql(
            database_url,
            "SELECT kind FROM operations WHERE request_id = $1 ORDER BY created_at",
            run.request_id,
        )
    )
    assert [str(row["kind"]) for row in kinds] == ["WITHDRAW", "REFILL", "PAY"]


def test_owner_balance_change_between_refill_and_pay_stops_with_review(database_url: str) -> None:
    run, signer, gate = asyncio.run(_new_run(database_url)), FakeSigner(), FakeGate()
    asyncio.run(_go(database_url, signer, run, gate))
    _tracker_says(database_url, run.steps[0], "Confirmed")
    gate.verdict = _decision("BLOCK", PolicyReasonCode.SOURCE_BUFFER_BREACH)

    result = asyncio.run(_go(database_url, signer, run, gate))

    assert (result.status, result.code) == ("PartiallyCompleted", "SOURCE_BUFFER_BREACH")
    assert signer.calls == 1  # PAY was never signed
    assert _request_status(database_url, run) == "NeedsReview"
    items = asyncio.run(
        _sql(
            database_url,
            "SELECT type, primary_code, assigned_roles, completed_steps::text AS done "
            "FROM review_items WHERE request_id = $1",
            run.request_id,
        )
    )
    assert len(items) == 1 and items[0]["type"] == "POLICY_BLOCK"
    assert items[0]["primary_code"] == "SOURCE_BUFFER_BREACH" and items[0]["assigned_roles"] == [
        "Owner"
    ]
    assert "0x" + run.steps[0].step_id.hex() in items[0]["done"]
    # A second stop does not duplicate the open item.
    asyncio.run(_go(database_url, signer, run, gate))
    assert (
        len(
            asyncio.run(
                _sql(
                    database_url, "SELECT 1 FROM review_items WHERE request_id = $1", run.request_id
                )
            )
        )
        == 1
    )


def test_first_step_block_is_blocked_not_partial(database_url: str) -> None:
    run, signer, gate = asyncio.run(_new_run(database_url)), FakeSigner(), FakeGate()
    gate.verdict = _decision("NEEDS_APPROVAL", PolicyReasonCode.OVER_PER_REQUEST_LIMIT)
    result = asyncio.run(_go(database_url, signer, run, gate))
    assert result.status == "Blocked" and signer.calls == 0
    types = asyncio.run(
        _sql(database_url, "SELECT type FROM review_items WHERE request_id = $1", run.request_id)
    )
    assert [r["type"] for r in types] == ["NEEDS_AUTHORITY"]


def test_a_stale_or_forged_swap_quote_stops_the_plan_before_anything_is_signed(
    database_url: str,
) -> None:
    """EXE-L02: ``before_send`` rejects the quote; no operation, no signer call, one INFRA review."""
    for code in ("SWAP_QUOTE_EXPIRED", "SWAP_QUOTE_FORGED"):
        run = asyncio.run(_new_run(database_url, kinds=("SWAP", "REFILL", "PAY")))
        signer, gate = FakeSigner(), FakeGate()
        seen: list[str] = []

        async def reject(step: StepExecution, code: str = code, seen: list[str] = seen) -> None:
            seen.append(step.kind)
            raise QuoteRejected(code)

        result = asyncio.run(_go(database_url, signer, run, gate, before_send=reject))
        assert result.status == "Blocked" and result.code == code
        assert signer.calls == 0 and seen == ["SWAP"]
        reviews = asyncio.run(
            _sql(
                database_url,
                "SELECT type, primary_code FROM review_items WHERE request_id = $1",
                run.request_id,
            )
        )
        assert [(r["type"], r["primary_code"]) for r in reviews] == [("INFRA", code)]
        operations = asyncio.run(
            _sql(database_url, "SELECT 1 FROM operations WHERE request_id = $1", run.request_id)
        )
        assert operations == []
        assert _request_status(database_url, run) == "NeedsReview"


class _AdapterRpc:
    """Answers the adapter's ``tokenOut()`` view for ``build_swap_quote_hook``."""

    async def call(self, method: str, params: list[Any]) -> str:
        assert method == "eth_call"
        return "0x" + "00" * 12 + "66" * 20


def _quote_world(database_url: str, *, signing_key: str, ttl: int, stager: Any) -> Any:
    """A SWAP(SIGNED_QUOTE), REFILL, PAY run plus the driver's hook built from settings (EXE-L02)."""
    from eth_account import Account

    from treasurypilot_core.money import BaseUnits
    from treasurypilot_core.policy import Action, ExecutionPlan, PlanStep
    from treasurypilot_worker.config import Settings
    from treasurypilot_worker.executor.swap_quotes import (
        FakeQuoteSource,
        build_swap_quote_hook,
    )

    adapter, venue = "0x" + "88" * 20, "0x" + "77" * 20
    safe_t, token_in = "0x" + "22" * 20, "0x" + "55" * 20
    allowed = Account.from_key("0x" + "a1" * 32).address
    run = asyncio.run(_new_run(database_url, kinds=("SWAP", "REFILL", "PAY")))
    sid = "0x" + run.steps[0].step_id.hex()
    swap = run.steps[0]
    swap.sign_request["plan"] = {
        "steps": [{"stepId": sid, "amount": 100}],
        "swaps": {sid: {"minOut": 190, "venue": "SIGNED_QUOTE"}},
    }
    plan = ExecutionPlan(
        request_id=b"\x01" * 32,
        treasury="0x" + "11" * 20,
        chain_id=31337,
        steps=[
            PlanStep(
                seq=0,
                step_id=swap.step_id,
                action=Action.SWAP,
                from_wallet=safe_t,
                to=adapter,
                asset=token_in,
                amount=BaseUnits(100),
                min_out=BaseUnits(190),
                venue="SIGNED_QUOTE",
            )
        ],
        planner_source="DETERMINISTIC",
        evidence_ids=[],
    )
    settings = Settings(
        swap_quote_url="https://quotes.example/q",
        swap_adapter_address=adapter,
        swap_quote_signers=allowed,
        swap_quote_venues=venue,
    )
    now = 1_800_000_000
    source = FakeQuoteSource(
        signing_key,
        venue,
        lambda request: b"route",
        now=lambda: now,
        ttl_seconds=ttl,
    )
    hook = asyncio.run(
        build_swap_quote_hook(
            settings, plan, _AdapterRpc(), stager=stager, source=source, now=lambda: now
        )
    )
    return run, hook


def test_driver_hook_stops_a_stale_forged_or_unstageable_swap_quote(database_url: str) -> None:
    """EXE-L02: the hook the Celery driver builds stops the plan; no operation, no signer call."""

    async def stager(to: str, data: bytes) -> None:
        raise AssertionError("a rejected quote must never be staged")

    async def ok_stager(to: str, data: bytes) -> None:
        return None

    cases = [
        ("0x" + "b2" * 32, 300, ok_stager, "SWAP_QUOTE_FORGED"),  # signer not allowlisted
        ("0x" + "a1" * 32, -1, ok_stager, "SWAP_QUOTE_EXPIRED"),  # stale
        ("0x" + "a1" * 32, 300, None, "SWAP_QUOTE_STAGER_UNAVAILABLE"),  # fail closed
    ]
    for key, ttl, stage, code in cases:
        run, hook = _quote_world(
            database_url,
            signing_key=key,
            ttl=ttl,
            stager=stage if code != "SWAP_QUOTE_FORGED" else stager,
        )
        assert hook is not None
        signer, gate = FakeSigner(), FakeGate()
        result = asyncio.run(_go(database_url, signer, run, gate, before_send=hook))
        assert result.status == "Blocked" and result.code == code
        assert signer.calls == 0
        reviews = asyncio.run(
            _sql(
                database_url,
                "SELECT type, primary_code FROM review_items WHERE request_id = $1",
                run.request_id,
            )
        )
        assert [(r["type"], r["primary_code"]) for r in reviews] == [("INFRA", code)]
        assert (
            asyncio.run(
                _sql(database_url, "SELECT 1 FROM operations WHERE request_id = $1", run.request_id)
            )
            == []
        )
        assert _request_status(database_url, run) == "NeedsReview"


def test_expired_attestation_is_renewed_or_stops(database_url: str) -> None:
    run, signer, gate = asyncio.run(_new_run(database_url)), FakeSigner(), FakeGate()
    asyncio.run(_go(database_url, signer, run, gate))
    _tracker_says(database_url, run.steps[0], "Confirmed")
    later = lambda: datetime.now(UTC) + timedelta(hours=1)  # noqa: E731

    gate.renewed = _decision("BLOCK", PolicyReasonCode.ATTESTATION_EXPIRED)
    result = asyncio.run(_go(database_url, signer, run, gate, clock=later))
    assert result.status == "PartiallyCompleted" and gate.reattested == [1]
    assert signer.calls == 1

    # A stopped request is not advanced even by a valid renewal: a fresh plan takes that path.
    run = asyncio.run(_new_run(database_url))
    asyncio.run(_go(database_url, signer, run, gate))
    _tracker_says(database_url, run.steps[0], "Confirmed")
    gate.reattested.clear()
    gate.renewed = PlanRun(
        run.plan_id, run.request_id, run.steps, datetime.now(UTC) + timedelta(hours=2)
    )
    assert asyncio.run(_go(database_url, signer, run, gate, clock=later)).status == "Waiting"
    assert gate.reattested == [1] and signer.calls == 3


def test_terminal_refusal_and_reverted_step_open_review(database_url: str) -> None:
    run, signer, gate = asyncio.run(_new_run(database_url)), FakeSigner(), FakeGate()
    signer.fail_with = SignerRefused("ATTESTATION_EXPIRED")
    result = asyncio.run(_go(database_url, signer, run, gate))
    assert (result.status, result.code) == ("Blocked", "ATTESTATION_EXPIRED")

    other, signer = asyncio.run(_new_run(database_url)), FakeSigner()
    asyncio.run(_go(database_url, signer, other, gate))
    _tracker_says(database_url, other.steps[0], "Reverted")
    result = asyncio.run(_go(database_url, signer, other, gate))
    assert (result.status, result.code) == ("Blocked", "STEP_REVERTED")
    rows = asyncio.run(
        _sql(database_url, "SELECT type FROM review_items WHERE request_id = $1", other.request_id)
    )
    assert [r["type"] for r in rows] == ["INFRA"]


def test_insufficient_gas_refusal_opens_an_infra_review(database_url: str) -> None:
    run, signer = asyncio.run(_new_run(database_url)), FakeSigner()
    signer.fail_with = SignerRefused("INSUFFICIENT_GAS")

    result = asyncio.run(_go(database_url, signer, run, FakeGate()))

    assert (result.status, result.code) == ("Blocked", "INSUFFICIENT_GAS")
    rows = asyncio.run(
        _sql(database_url, "SELECT type FROM review_items WHERE request_id = $1", run.request_id)
    )
    assert [r["type"] for r in rows] == ["INFRA"]


def test_worker_routing_matches_api() -> None:
    for kind in ("POLICY_BLOCK", "NEEDS_AUTHORITY", "INFRA", "DISCREPANCY"):
        for code in ("BUFFER_BREACH", "AMOUNT_CHANGED"):
            api = route_for(ReviewType(kind), code)
            roles, sla = _route(kind, code)
            assert roles == [r.value for r in api.roles] and sla == api.sla


@pytest.mark.parametrize("status", ["NeedsReview", "Cancelled"])
def test_inactive_request_is_never_signed(database_url: str, status: str) -> None:
    run, signer, gate = asyncio.run(_new_run(database_url)), FakeSigner(), FakeGate()
    asyncio.run(
        _sql(
            database_url,
            "UPDATE payment_requests SET status = $2 WHERE id = $1",
            run.request_id,
            status,
        )
    )
    result = asyncio.run(_go(database_url, signer, run, gate))
    assert (result.status, result.code) == ("Inactive", status)
    assert signer.calls == 0 and gate.checked == []


def test_cancel_during_validation_is_honoured_before_signing(database_url: str) -> None:
    run, signer = asyncio.run(_new_run(database_url)), FakeSigner()

    class CancellingGate(FakeGate):
        async def pre_step(self, seq: int) -> Decision:
            await _sql(
                database_url,
                "UPDATE payment_requests SET status = 'Cancelled' WHERE id = $1",
                run.request_id,
            )
            return await super().pre_step(seq)

    result = asyncio.run(_go(database_url, signer, run, CancellingGate()))
    assert (result.status, result.code) == ("Inactive", "Cancelled") and signer.calls == 0


def test_stop_after_concurrent_cancel_opens_no_review_item(database_url: str) -> None:
    run, signer, gate = asyncio.run(_new_run(database_url)), FakeSigner(), FakeGate()
    gate.verdict = _decision("BLOCK", PolicyReasonCode.SOURCE_BUFFER_BREACH)

    class CancellingGate(FakeGate):
        async def pre_step(self, seq: int) -> Decision:
            await _sql(
                database_url,
                "UPDATE payment_requests SET status = 'Cancelled' WHERE id = $1",
                run.request_id,
            )
            return gate.verdict

    result = asyncio.run(_go(database_url, signer, run, CancellingGate()))
    assert result.status == "Inactive"
    assert not asyncio.run(
        _sql(database_url, "SELECT 1 FROM review_items WHERE request_id = $1", run.request_id)
    )


def test_unsent_attempted_step_is_replayed_without_the_gate(database_url: str) -> None:
    run, signer, gate = asyncio.run(_new_run(database_url)), FakeSigner(), FakeGate()
    signer.fail_with = SignerUnavailable("timeout")
    with pytest.raises(SignerUnavailable):
        asyncio.run(_go(database_url, signer, run, gate))
    assert gate.checked == [0]
    signer.fail_with = None
    gate.verdict = _decision(
        "BLOCK", PolicyReasonCode.SOURCE_BUFFER_BREACH
    )  # would stop a gate run

    assert asyncio.run(_go(database_url, signer, run, gate)).status == "Waiting"
    assert gate.checked == [0] and signer.calls == 2


def test_paid_goes_through_paying_with_both_events(database_url: str) -> None:
    run, signer, gate = asyncio.run(_new_run(database_url)), FakeSigner(), FakeGate()
    for step in run.steps:
        asyncio.run(_go(database_url, signer, run, gate))
        _tracker_says(database_url, step, "Confirmed")
    # Resumed after a lost Paying mark: still Preparing when the plan completes.
    asyncio.run(
        _sql(
            database_url,
            "UPDATE payment_requests SET status = 'Preparing' WHERE id = $1",
            run.request_id,
        )
    )
    assert asyncio.run(_go(database_url, signer, run, gate)).status == "Completed"
    events = asyncio.run(
        _sql(
            database_url,
            'SELECT "from", "to" FROM request_status_events WHERE request_id = $1 ORDER BY at',
            run.request_id,
        )
    )
    assert [(e["from"], e["to"]) for e in events][-2:] == [
        ("Preparing", "Paying"),
        ("Paying", "Paid"),
    ]


def test_paused_treasury_is_a_no_op_and_the_request_stays_queued(database_url: str) -> None:
    run, signer, gate = asyncio.run(_new_run(database_url)), FakeSigner(), FakeGate()
    flag = (
        "INSERT INTO backend_pause (treasury_id, org_id, paused, reason) VALUES ($1, $2, $3, 'x') "
    )
    flag += "ON CONFLICT (treasury_id) DO UPDATE SET paused = EXCLUDED.paused"
    asyncio.run(_sql(database_url, flag, _TREASURY, uuid.UUID(_ORG), True))
    try:
        result = asyncio.run(_go(database_url, signer, run, gate))
        assert result.status == "Paused"
        assert signer.calls == 0 and gate.checked == []
        assert _request_status(database_url, run) == "Preparing"  # not NeedsReview
        items = asyncio.run(
            _sql(database_url, "SELECT 1 FROM review_items WHERE request_id = $1", run.request_id)
        )
        assert items == []
    finally:
        asyncio.run(_sql(database_url, flag, _TREASURY, uuid.UUID(_ORG), False))
    assert asyncio.run(_go(database_url, signer, run, gate)).status == "Waiting"


class ScriptedVerifier:
    def __init__(self, *verdicts: str) -> None:
        self.verdicts, self.calls = list(verdicts), 0

    async def verify(self, step_id: bytes, operation_id: uuid.UUID) -> str:
        self.calls += 1
        return self.verdicts.pop(0)


async def _go_verified(
    url: str, signer: FakeSigner, run: PlanRun, gate: FakeGate, verifier: Any
) -> Any:
    return await _go(url, signer, run, gate, verifier=verifier)


def test_confirmed_step_needs_passed_post_condition_before_the_next_step(
    database_url: str,
) -> None:
    run, signer, gate = asyncio.run(_new_run(database_url)), FakeSigner(), FakeGate()
    verifier = ScriptedVerifier("UNKNOWN", "PASSED")
    asyncio.run(_go_verified(database_url, signer, run, gate, verifier))
    _tracker_says(database_url, run.steps[0], "Confirmed")

    result = asyncio.run(_go_verified(database_url, signer, run, gate, verifier))
    assert (result.status, result.code) == ("Waiting", "VERIFICATION_UNKNOWN")
    assert signer.calls == 1  # UNKNOWN: PAY is not sent

    result = asyncio.run(_go_verified(database_url, signer, run, gate, verifier))
    assert result.status == "Waiting" and signer.calls == 2 and verifier.calls == 2


def test_post_condition_discrepancy_opens_review_and_trips_breaker(database_url: str) -> None:
    run, signer, gate = asyncio.run(_new_run(database_url)), FakeSigner(), FakeGate()
    chain = _verify.pay_chain(run.steps[0].step_id, payee_gets=900)
    plan_step = _verify.step(_verify.Action.PAY, _verify.OP, _verify.PAYEE)
    asyncio.run(_go_real(database_url, signer, run, gate, chain, plan_step))
    _confirm(database_url, run.steps[0])

    result = asyncio.run(_go_real(database_url, signer, run, gate, chain, plan_step))

    assert (result.status, result.code) == ("PartiallyCompleted", "POST_CONDITION_DISCREPANCY")
    assert signer.calls == 1
    rows = asyncio.run(_sql(database_url, "SELECT * FROM verifications"))
    row = [r for r in rows if r["result"] == "DISCREPANCY"][-1]
    assert json.loads(row["diffs"]) == {
        f"balance:{_verify.PAYEE}": {"expected": 1000, "observed": 900}
    }
    items = asyncio.run(
        _sql(
            database_url,
            "SELECT type, assigned_roles FROM review_items WHERE request_id = $1",
            run.request_id,
        )
    )
    assert [(i["type"], i["assigned_roles"]) for i in items] == [
        ("DISCREPANCY", ["Finance", "Owner"])
    ]
    signals = asyncio.run(
        _sql(
            database_url,
            "SELECT signal_type FROM chain_safety_signals WHERE verification_id = $1",
            row["id"],
        )
    )
    assert [s["signal_type"] for s in signals] == ["CIRCUIT_BREAKER"]
    with pytest.raises(Exception, match="append-only"):
        asyncio.run(_sql(database_url, "DELETE FROM verifications"))


def test_normal_pay_passes_after_a_failed_read_is_unknown(database_url: str) -> None:
    run, signer, gate = asyncio.run(_new_run(database_url)), FakeSigner(), FakeGate()
    chain = _verify.pay_chain(run.steps[0].step_id)
    plan_step = _verify.step(_verify.Action.PAY, _verify.OP, _verify.PAYEE)
    asyncio.run(_go_real(database_url, signer, run, gate, chain, plan_step))
    _confirm(database_url, run.steps[0])

    chain.down = True
    result = asyncio.run(_go_real(database_url, signer, run, gate, chain, plan_step))
    assert (result.status, result.code) == ("Waiting", "VERIFICATION_UNKNOWN")
    assert signer.calls == 1

    chain.down = False
    result = asyncio.run(_go_real(database_url, signer, run, gate, chain, plan_step))
    assert result.status == "Waiting" and signer.calls == 2  # PASSED: PAY sent
    results = [
        r["result"]
        for r in asyncio.run(_sql(database_url, "SELECT result FROM verifications ORDER BY at"))
    ]
    assert results[-2:] == ["UNKNOWN", "PASSED"]


async def _go_real(
    url: str, signer: FakeSigner, run: PlanRun, gate: FakeGate, chain: Any, plan_step: Any
) -> Any:
    pool = await create_worker_pool(url, min_size=1, max_size=2)
    try:
        steps = {s.step_id: plan_step.model_copy(update={"step_id": s.step_id}) for s in run.steps}
        verifier = PostConditionVerifier(pool, chain, steps, _verify.REQUEST, _verify.MODULE)
        return await sequence_plan(pool, signer, run, gate, verifier=verifier)
    finally:
        await pool.close()


def _confirm(url: str, step: StepExecution) -> None:
    asyncio.run(
        _sql(
            url,
            "UPDATE transactions SET status = 'Confirmed', block_number = $2, confirmed_at = now() "
            "WHERE operation_id = (SELECT id FROM operations WHERE step_id = $1)",
            step.step_id,
            _verify.B,
        )
    )
    asyncio.run(
        _sql(url, "UPDATE operations SET status = 'Confirmed' WHERE step_id = $1", step.step_id)
    )


def test_reorg_is_unknown_and_three_reads_open_infra_review_then_reset(
    database_url: str,
) -> None:
    run, signer, gate = asyncio.run(_new_run(database_url)), FakeSigner(), FakeGate()
    chain = _verify.pay_chain(run.steps[0].step_id)
    plan_step = _verify.step(_verify.Action.PAY, _verify.OP, _verify.PAYEE)
    asyncio.run(_go_real(database_url, signer, run, gate, chain, plan_step))
    _confirm(database_url, run.steps[0])

    chain.receipt_block = _verify.B + 1  # reorged: never a DISCREPANCY
    for _ in range(2):
        result = asyncio.run(_go_real(database_url, signer, run, gate, chain, plan_step))
        assert (result.status, result.code) == ("Waiting", "VERIFICATION_UNKNOWN")
    result = asyncio.run(_go_real(database_url, signer, run, gate, chain, plan_step))
    assert (result.status, result.code) == ("PartiallyCompleted", "VERIFICATION_UNKNOWN")
    results = [
        r["result"]
        for r in asyncio.run(
            _sql(
                database_url,
                "SELECT result FROM verifications WHERE operation_id IN "
                "(SELECT id FROM operations WHERE step_id = $1)",
                run.steps[0].step_id,
            )
        )
    ]
    assert results.count("UNKNOWN") >= 3 and "DISCREPANCY" not in results

    # Resolving the review resets the count: the next UNKNOWN waits again.
    asyncio.run(
        _sql(
            database_url,
            "UPDATE review_items SET status = 'Resolved', resolved_at = now() "
            "WHERE request_id = $1",
            run.request_id,
        )
    )
    asyncio.run(
        _sql(
            database_url,
            "UPDATE payment_requests SET status = 'Preparing' WHERE id = $1",
            run.request_id,
        )
    )
    result = asyncio.run(_go_real(database_url, signer, run, gate, chain, plan_step))
    assert (result.status, result.code) == ("Waiting", "VERIFICATION_UNKNOWN")


def test_concurrent_verifiers_store_one_verdict_and_one_breaker_signal(
    database_url: str,
) -> None:
    run, signer, gate = asyncio.run(_new_run(database_url)), FakeSigner(), FakeGate()
    chain = _verify.pay_chain(run.steps[0].step_id, payee_gets=900)
    plan_step = _verify.step(_verify.Action.PAY, _verify.OP, _verify.PAYEE)
    asyncio.run(_go_real(database_url, signer, run, gate, chain, plan_step))
    _confirm(database_url, run.steps[0])

    async def race() -> list[str]:
        pool = await create_worker_pool(database_url, min_size=1, max_size=4)
        try:
            steps = {
                s.step_id: plan_step.model_copy(update={"step_id": s.step_id}) for s in run.steps
            }
            verifier = PostConditionVerifier(pool, chain, steps, _verify.REQUEST, _verify.MODULE)
            op = await pool.fetchval(
                "SELECT id FROM operations WHERE step_id = $1", run.steps[0].step_id
            )
            return list(
                await asyncio.gather(*(verifier.verify(run.steps[0].step_id, op) for _ in range(4)))
            )
        finally:
            await pool.close()

    assert asyncio.run(race()) == ["DISCREPANCY"] * 4
    rows = asyncio.run(
        _sql(
            database_url,
            "SELECT id FROM verifications WHERE result = 'DISCREPANCY' AND operation_id IN "
            "(SELECT id FROM operations WHERE step_id = $1)",
            run.steps[0].step_id,
        )
    )
    signals = asyncio.run(
        _sql(
            database_url,
            "SELECT 1 FROM chain_safety_signals WHERE verification_id = ANY($1)",
            [r["id"] for r in rows],
        )
    )
    assert len(rows) == 1 and len(signals) == 1


def _stopped_after_refill(url: str) -> tuple[PlanRun, FakeSigner, FakeGate]:
    run, signer, gate = asyncio.run(_new_run(url)), FakeSigner(), FakeGate()
    asyncio.run(
        _sql(
            url,
            "INSERT INTO plans (id, org_id, treasury_id, request_id, status) "
            "VALUES ($1, $2, $3, $4, 'Executing')",
            run.plan_id,
            uuid.UUID(_ORG),
            _TREASURY,
            run.request_id,
        )
    )
    asyncio.run(_go(url, signer, run, gate))
    _tracker_says(url, run.steps[0], "Confirmed")
    gate.verdict = _decision("BLOCK", PolicyReasonCode.SOURCE_BUFFER_BREACH)
    assert asyncio.run(_go(url, signer, run, gate)).status == "PartiallyCompleted"
    asyncio.run(
        _sql(url, "UPDATE plans SET status = 'PartiallyCompleted' WHERE id = $1", run.plan_id)
    )
    return run, signer, gate


async def _resume(url: str, request: uuid.UUID, actor: uuid.UUID | None = None) -> Any:
    pool = await create_worker_pool(url, min_size=1, max_size=1)
    try:
        return await resume_partial(pool, request, actor)
    finally:
        await pool.close()


async def _cancel(url: str, request: uuid.UUID, actor: uuid.UUID | None = None) -> Any:
    pool = await create_worker_pool(url, min_size=1, max_size=1)
    try:
        return await cancel_partial(pool, request, actor)
    finally:
        await pool.close()


def test_resume_sends_only_the_unfinished_pay_after_revalidation(database_url: str) -> None:
    run, signer, gate = _stopped_after_refill(database_url)
    gate.checked.clear()

    assert asyncio.run(_resume(database_url, run.request_id)).status == "Resumed"
    assert _request_status(database_url, run) == "Preparing"
    gate.verdict = _decision("ALLOW")
    assert asyncio.run(_go(database_url, signer, run, gate)).status == "Waiting"

    assert gate.checked == [1]  # only PAY re-validated
    assert signer.calls == 2  # one refill, one pay: no second refill
    ops = asyncio.run(
        _sql(database_url, "SELECT step_id FROM operations WHERE request_id = $1", run.request_id)
    )
    assert len(ops) == 2
    # The old review item is resolved and the plan is Executing again.
    rows = asyncio.run(
        _sql(database_url, "SELECT status FROM review_items WHERE request_id = $1", run.request_id)
    )
    assert [r["status"] for r in rows] == ["Resolved"]
    plan = asyncio.run(_sql(database_url, "SELECT status FROM plans WHERE id = $1", run.plan_id))
    assert plan[0]["status"] == "Executing"
    events = asyncio.run(
        _sql(
            database_url,
            'SELECT "from", "to", actor_type FROM request_status_events WHERE request_id = $1 '
            "AND \"to\" = 'Preparing'",
            run.request_id,
        )
    )
    assert [(e["from"], e["actor_type"]) for e in events] == [("NeedsReview", "SYSTEM")]
    # Not partial any more: a second resume is refused.
    assert asyncio.run(_resume(database_url, run.request_id)).status == "NotPartial"


def test_resume_still_blocked_stops_again_and_never_resends(database_url: str) -> None:
    run, signer, gate = _stopped_after_refill(database_url)
    asyncio.run(_resume(database_url, run.request_id))
    assert asyncio.run(_go(database_url, signer, run, gate)).status == "PartiallyCompleted"
    assert signer.calls == 1 and _request_status(database_url, run) == "NeedsReview"


def test_resume_refuses_while_an_operation_is_in_flight(database_url: str) -> None:
    run, _, _ = _stopped_after_refill(database_url)
    _tracker_says(database_url, run.steps[0], "Unknown")
    assert asyncio.run(_resume(database_url, run.request_id)).status == "InFlight"
    assert _request_status(database_url, run) == "NeedsReview"


def test_cancel_reports_funds_left_in_place(database_url: str) -> None:
    run, _, _ = _stopped_after_refill(database_url)
    report = asyncio.run(_cancel(database_url, run.request_id))
    assert report.cancelled and report.funds_left_in_place
    assert report.completed_steps == ("0x" + run.steps[0].step_id.hex(),)
    assert _request_status(database_url, run) == "Cancelled"


def test_cancel_closes_plan_resolves_items_and_audits(database_url: str) -> None:
    run, _, _ = _stopped_after_refill(database_url)
    report = asyncio.run(_cancel(database_url, run.request_id))
    assert report.cancelled and "not reversed" in report.summary
    plan = asyncio.run(_sql(database_url, "SELECT status FROM plans WHERE id = $1", run.plan_id))
    assert plan[0]["status"] == "Superseded"
    items = asyncio.run(
        _sql(
            database_url,
            "SELECT status, resolution FROM review_items WHERE request_id = $1",
            run.request_id,
        )
    )
    assert [(i["status"], i["resolution"]) for i in items] == [("Resolved", "CANCEL")]
    # A second cancel finds no PartiallyCompleted plan.
    assert not asyncio.run(_cancel(database_url, run.request_id)).cancelled


def test_cancel_without_a_partial_plan_is_refused(database_url: str) -> None:
    assert not asyncio.run(_cancel(database_url, uuid.uuid4())).cancelled


def test_cancel_refuses_while_an_operation_is_in_flight(database_url: str) -> None:
    run, _, _ = _stopped_after_refill(database_url)
    _tracker_says(database_url, run.steps[0], "Unknown")
    report = asyncio.run(_cancel(database_url, run.request_id))
    assert not report.cancelled and report.in_flight_steps == ("0x" + run.steps[0].step_id.hex(),)
    assert _request_status(database_url, run) == "NeedsReview"


@pytest.mark.parametrize("status", ["Reverted", "Abandoned"])
def test_resume_refuses_a_reverted_or_abandoned_step(database_url: str, status: str) -> None:
    run, _, _ = _stopped_after_refill(database_url)
    _tracker_says(database_url, run.steps[0], status)
    assert asyncio.run(_resume(database_url, run.request_id)).status == "NotRetryable"
    assert _request_status(database_url, run) == "NeedsReview"


def test_resume_refuses_non_retryable_review_items(database_url: str) -> None:
    run, _, _ = _stopped_after_refill(database_url)
    asyncio.run(
        _sql(
            database_url,
            "UPDATE review_items SET type = 'DISCREPANCY' WHERE request_id = $1",
            run.request_id,
        )
    )
    assert asyncio.run(_resume(database_url, run.request_id)).status == "NotRetryable"


def test_two_concurrent_resumes_resume_exactly_once(database_url: str) -> None:
    run, _, _ = _stopped_after_refill(database_url)

    async def both() -> list[Any]:
        return list(
            await asyncio.gather(
                _resume(database_url, run.request_id), _resume(database_url, run.request_id)
            )
        )

    statuses = sorted(r.status for r in asyncio.run(both()))
    assert statuses == ["NotPartial", "Resumed"]
    events = asyncio.run(
        _sql(
            database_url,
            "SELECT 1 FROM request_status_events WHERE request_id = $1 AND \"to\" = 'Preparing'",
            run.request_id,
        )
    )
    assert len(events) == 1
