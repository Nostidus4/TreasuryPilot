"""Step sequencing against PostgreSQL with a fake signer, gate and tracker (EXE-008)."""

from __future__ import annotations

import asyncio
import importlib.util
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
from treasurypilot_core.policy import Check, Decision, PolicyReasonCode
from treasurypilot_worker.executor.outbox import SignerRefused, SignerUnavailable, StepExecution
from treasurypilot_worker.executor.sequencer import PlanRun, _route, sequence_plan
from treasurypilot_worker.locks import create_worker_pool

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


async def _new_run(url: str, valid_for: timedelta = timedelta(minutes=5)) -> PlanRun:
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
    steps = (_step(request, "REFILL"), _step(request, "PAY"))
    return PlanRun(uuid.uuid4(), request, steps, datetime.now(UTC) + valid_for)


async def _go(url: str, signer: FakeSigner, run: PlanRun, gate: FakeGate, **kw: Any) -> Any:
    pool = await create_worker_pool(url, min_size=1, max_size=2)
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


def test_worker_routing_matches_api() -> None:
    for kind in ("POLICY_BLOCK", "NEEDS_AUTHORITY", "INFRA"):
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
