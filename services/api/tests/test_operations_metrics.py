from __future__ import annotations

import asyncio
import os
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from treasurypilot_api.observability.metrics import (
    Event,
    MetricInputs,
    RequestFacts,
    TxFacts,
    compute_operations_metrics,
)

START = datetime(2026, 10, 1, tzinfo=UTC)
END = datetime(2026, 10, 3, 23, 59, 59, tzinfo=UTC)


def _ids(n: int) -> list[uuid.UUID]:
    return [uuid.UUID(int=i + 1) for i in range(n)]


def _at(day: int, hour: int = 0, minute: int = 0) -> datetime:
    return START + timedelta(days=day - 1, hours=hour, minutes=minute)


def _dataset() -> MetricInputs:
    a, b, c, d, e = _ids(5)
    approval = [Event("AwaitingApproval", _at(1)), Event("Approved", _at(1, 0, 30))]
    requests = [
        # a: paid on time (due day 2, paid day 2 evening); approval 30 min, approved->scheduled 1 h
        RequestFacts(
            a,
            date(2026, 10, 2),
            1_000,
            [*approval, Event("Scheduled", _at(1, 1, 30)), Event("Paid", _at(2, 20))],
        ),
        # b: paid late (due day 1, paid day 3); approval 90 min
        RequestFacts(
            b,
            date(2026, 10, 1),
            2_000,
            [
                Event("AwaitingApproval", _at(1)),
                Event("Approved", _at(1, 1, 30)),
                Event("Scheduled", _at(1, 3, 30)),
                Event("Paid", _at(3, 1)),
            ],
        ),
        # c: blocked by policy after scheduling: stays in the completion denominator
        RequestFacts(c, None, 500, [Event("Scheduled", _at(2)), Event("NeedsReview", _at(2, 1))]),
        # d: cancelled by a human after scheduling: excluded
        RequestFacts(
            d, None, 700, [Event("Scheduled", _at(2)), Event("Cancelled", _at(2, 2), "USER")]
        ),
        # e: rejected by a human before scheduling: counted as a rejection by reason
        RequestFacts(e, None, 900, [Event("Rejected", _at(3), "USER", "DUPLICATE_INVOICE")]),
    ]
    txs = [
        TxFacts("PAY", _at(2, 19), _at(2, 19, 2), 100, None),
        TxFacts("PAY", _at(3), _at(3, 0, 10), 300, None),
        TxFacts("REFILL", _at(3, 5), None, 50, "08c379a0"),  # reverted, fee still counted
    ]
    return MetricInputs(
        start=START,
        end=END,
        requests=requests,
        interventions=Counter({a: 1, b: 3, c: 5}),  # c is not paid: not counted
        blocks=["OVER_PER_REQUEST_LIMIT", "OVER_PER_REQUEST_LIMIT", "PAYEE_NOT_APPROVED"],
        exceptions=2,
        unknown_operations=1,
        transactions=txs,
    )


def test_seeded_dataset_metrics() -> None:
    m = compute_operations_metrics(_dataset())

    assert m.payments_count == 2
    assert m.on_time_rate == 0.5
    assert m.completion_rate == round(2 / 3, 4)  # a, b paid; c blocked; d excluded
    assert m.interventions_per_request == 2.0  # (1 + 3) / 2 paid
    assert m.median_approval_minutes == 60.0
    assert (m.exceptions, m.unknown_operations, m.tx_count) == (2, 1, 3)
    assert m.fees.total_wei == "450"
    assert m.fees.by_step_type == {"PAY": "400", "REFILL": "50"}
    assert m.reverts_by_selector == {"08c379a0": 1}
    assert [p.paid for p in m.series] == [0, 1, 1]
    assert [p.volume for p in m.series] == ["0", "1000", "2000"]


def test_latency_by_phase() -> None:
    phases = compute_operations_metrics(_dataset()).latency_by_phase
    scheduled = phases["approvalToScheduled"]
    assert scheduled is not None
    assert (scheduled.median_seconds, scheduled.p90_seconds, scheduled.count) == (
        5400.0,
        7200.0,
        2,
    )
    confirmed = phases["submitToConfirmed"]
    assert confirmed is not None
    assert confirmed.median_seconds == 360.0
    assert phases["confirmedToVerified"] is None


def test_rejected_requests_are_included() -> None:
    m = compute_operations_metrics(_dataset())
    assert m.rejections_by_reason == {
        "DUPLICATE_INVOICE": 1,
        "OVER_PER_REQUEST_LIMIT": 2,
        "PAYEE_NOT_APPROVED": 1,
    }


def test_empty_period_is_all_zero() -> None:
    m = compute_operations_metrics(MetricInputs(START, END, []))
    assert (m.payments_count, m.completion_rate, m.on_time_rate) == (0, 0.0, 0.0)
    assert m.fees.total_wei == "0"
    assert all(v is None for v in m.latency_by_phase.values())


_PG = "TP_TEST_DATABASE_URL"
_TREASURY = uuid.UUID("00000000-0000-7000-8000-000000000040")
_ASSET = uuid.UUID("00000000-0000-7000-8000-000000000030")
_ORG = uuid.UUID("00000000-0000-7000-8000-0000000000a0")
_USER = uuid.UUID("00000000-0000-7000-8000-0000000000a1")
_REQ = uuid.UUID("00000000-0000-7000-8000-0000000000a2")


async def _exercise_loader(database_url: str) -> None:
    from sqlalchemy import text

    from treasurypilot_api.database import create_session_factory
    from treasurypilot_api.observability.metrics import load_inputs
    from treasurypilot_api.recovery.models import ReviewItem

    engine, sessions = create_session_factory(database_url)
    try:
        async with engine.begin() as c:
            for sql in [
                "INSERT INTO users (id, email) VALUES (:u, 'm@example.test')",
                "INSERT INTO organizations (id, name) VALUES (:o, 'Metrics')",
                (
                    "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, "
                    "rpc_urls) VALUES (11155111, 'Sepolia', true, 3, 'https://x.test', "
                    "'[\"https://rpc\"]')"
                ),
                (
                    "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
                    "VALUES (:a, 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')"
                ),
                (
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id) "
                    "VALUES (:t, :o, 11155111, :a)"
                ),
                (
                    "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, invoice_no, "
                    "due_at, amount, asset_id, status) VALUES (:r, :o, :t, 11155111, 'M-1', "
                    "'2026-10-02', 1000, :a, 'Draft')"
                ),
            ]:
                await c.execute(
                    text(sql), {"u": _USER, "o": _ORG, "a": _ASSET, "t": _TREASURY, "r": _REQ}
                )
            for frm, to, actor, at in [
                (None, "AwaitingApproval", "USER", _at(1)),
                ("AwaitingApproval", "Approved", "USER", _at(1, 0, 30)),
                ("Approved", "Scheduled", "SYSTEM", _at(1, 1)),
                ("Scheduled", "Paid", "SYSTEM", _at(2)),
            ]:
                await c.execute(
                    text(
                        'INSERT INTO request_status_events (id, request_id, "from", "to", '
                        "actor_type, at) VALUES (gen_random_uuid(), :r, :f, :t, :ty, :at)"
                    ),
                    {"r": _REQ, "f": frm, "t": to, "ty": actor, "at": at},
                )
        async with sessions() as session, session.begin():
            session.add(
                ReviewItem(
                    org_id=_ORG,
                    treasury_id=_TREASURY,
                    request_id=_REQ,
                    request_version=1,
                    type="POLICY_BLOCK",
                    primary_code="OVER_PER_REQUEST_LIMIT",
                    reason_codes=["OVER_PER_REQUEST_LIMIT"],
                    completed_steps=[],
                    assigned_roles=["Owner"],
                    sla_due_at=_at(2),
                    created_at=_at(1, 2),
                    resolved_by=_USER,
                )
            )
        async with sessions() as session:
            data = await load_inputs(session, _ORG, START, END, None)
        m = compute_operations_metrics(data)
        assert (m.payments_count, m.on_time_rate, m.completion_rate) == (1, 1.0, 1.0)
        assert m.median_approval_minutes == 30.0
        assert m.interventions_per_request == 1.0
        assert m.rejections_by_reason == {"OVER_PER_REQUEST_LIMIT": 1}
        assert m.series[1].volume == "1000"
        async with sessions() as session:
            empty = await load_inputs(session, uuid.uuid4(), START, END, None)
        assert empty.requests == []
    finally:
        async with engine.begin() as c:
            # Replica role skips the append-only triggers so the migrations can downgrade.
            await c.execute(text("SET LOCAL session_replication_role = replica"))
            for sql in (
                "DELETE FROM review_items WHERE org_id = :o",
                "DELETE FROM request_status_events WHERE request_id = :r",
                "DELETE FROM payment_requests WHERE id = :r",
            ):
                await c.execute(text(sql), {"o": _ORG, "r": _REQ})
        await engine.dispose()


@pytest.mark.skipif(_PG not in os.environ, reason=f"{_PG} is required for the PostgreSQL test")
def test_postgres_loader_matches_seeded_dataset() -> None:
    database_url = os.environ[_PG]
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_exercise_loader(database_url))
    finally:
        command.downgrade(config, "base")
