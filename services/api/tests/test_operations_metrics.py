from __future__ import annotations

import asyncio
import os
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from treasurypilot_api.observability.metrics import (
    Event,
    MetricInputs,
    OperationsMetrics,
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
    assert [p.completed for p in m.series] == [0, 1, 1]
    assert [p.on_time for p in m.series] == [0, 1, 0]
    assert [p.interventions for p in m.series] == [0, 1, 3]
    assert [p.fees_wei for p in m.series] == ["0", "100", "350"]


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
_ASSET = uuid.UUID("00000000-0000-7000-8000-000000000030")
_USER = uuid.UUID("00000000-0000-7000-8000-0000000000a1")
_ORG = uuid.UUID("00000000-0000-7000-8000-0000000000a0")
_TREASURY = uuid.UUID("00000000-0000-7000-8000-000000000040")
_TREASURY_2 = uuid.UUID("00000000-0000-7000-8000-000000000041")
_REQ = uuid.UUID("00000000-0000-7000-8000-0000000000a2")
_REQ_2 = uuid.UUID("00000000-0000-7000-8000-0000000000a3")
_ORG_B = uuid.UUID("00000000-0000-7000-8000-0000000000b0")
_TREASURY_B = uuid.UUID("00000000-0000-7000-8000-000000000050")
_REQ_B = uuid.UUID("00000000-0000-7000-8000-0000000000b2")


async def _seed(c: object) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncConnection

    conn = cast(AsyncConnection, c)

    async def run(sql: str, **params: object) -> None:
        await conn.execute(text(sql), params)

    await run("INSERT INTO users (id, email) VALUES (:u, 'm@example.test')", u=_USER)
    await run(
        "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
        "VALUES (11155111, 'Sepolia', true, 3, 'https://x.test', '[\"https://rpc\"]')"
    )
    await run(
        "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
        "VALUES (:a, 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
        a=_ASSET,
    )
    for org, treasury in [(_ORG, _TREASURY), (_ORG, _TREASURY_2), (_ORG_B, _TREASURY_B)]:
        if treasury != _TREASURY_2:
            await run("INSERT INTO organizations (id, name) VALUES (:o, 'Metrics')", o=org)
        await run(
            "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES (:t, :o, 11155111, :a)",
            t=treasury,
            o=org,
            a=_ASSET,
        )
    for req, org, treasury in [
        (_REQ, _ORG, _TREASURY),
        (_REQ_2, _ORG, _TREASURY_2),
        (_REQ_B, _ORG_B, _TREASURY_B),
    ]:
        await run(
            "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, invoice_no, "
            "due_at, amount, asset_id, status) VALUES (:r, :o, :t, 11155111, :n, "
            "'2026-10-02', 1000, :a, 'Draft')",
            r=req,
            o=org,
            t=treasury,
            a=_ASSET,
            n=f"M-{req.int % 100}",
        )
    for req in (_REQ, _REQ_B):
        for frm, to, actor, at in [
            (None, "AwaitingApproval", "USER", _at(1)),
            ("AwaitingApproval", "Approved", "USER", _at(1, 0, 30)),
            ("Approved", "Scheduled", "SYSTEM", _at(1, 1)),
            ("Scheduled", "Paid", "SYSTEM", _at(2)),
        ]:
            await run(
                'INSERT INTO request_status_events (id, request_id, "from", "to", '
                "actor_type, at) VALUES (gen_random_uuid(), :r, :f, :t, :ty, :at)",
                r=req,
                f=frm,
                t=to,
                ty=actor,
                at=at,
            )

    # (n, request, treasury, kind, status, tx: (submitted, confirmed, selector, fee) | None)
    ops: list[tuple[int, uuid.UUID, uuid.UUID, str, str, tuple[object, ...] | None]] = [
        (1, _REQ, _TREASURY, "PAY", "Confirmed", (_at(2, 19), _at(2, 19, 2), None, 100)),
        (2, _REQ, _TREASURY, "REFILL", "Reverted", (_at(3, 5), None, "08c379a0", None)),
        (3, _REQ, _TREASURY, "PAY", "Unknown", None),
        (4, _REQ_2, _TREASURY_2, "PAY", "Confirmed", (_at(2, 20), None, None, 7)),
        (5, _REQ_B, _TREASURY_B, "PAY", "Confirmed", (_at(2, 21), _at(2, 22), None, 999)),
        (6, _REQ_B, _TREASURY_B, "PAY", "Unknown", None),
    ]
    for n, req, treasury, kind, status, tx in ops:
        op_id = uuid.UUID(int=0xA000 + n)
        await run(
            "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, kind, "
            f"payload, idempotency_key, status) VALUES (:id, :t, :id, :r, decode(:s, 'hex'), "
            f"'{kind}', '{{}}'::jsonb, :k, '{status}')",
            id=op_id,
            t=treasury,
            r=req,
            s=f"{n:02x}" * 32,
            k=f"op-{n}",
        )
        if tx is None:
            continue
        submitted, confirmed, selector, fee = tx
        tx_id = uuid.UUID(int=0xB000 + n)
        await run(
            "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, from_address, "
            "submitted_at, confirmed_at, revert_selector) VALUES (:id, :op, 11155111, "
            "decode(:h, 'hex'), 0, decode(repeat('33', 20), 'hex'), :sub, :conf, "
            "decode(:sel, 'hex'))",
            id=tx_id,
            op=op_id,
            h=f"{n:02x}" * 32,
            sub=submitted,
            conf=confirmed,
            sel=selector,
        )
        if fee is not None:
            await run(
                "INSERT INTO gas_ledger (id, treasury_id, transaction_id, payer, payer_address, "
                "fee_wei, day) VALUES (gen_random_uuid(), :t, :tx, 'EXECUTOR', "
                "decode(repeat('33', 20), 'hex'), :fee, '2026-10-02')",
                t=treasury,
                tx=tx_id,
                fee=fee,
            )


async def _exercise_loader(database_url: str) -> None:
    from sqlalchemy import text

    from treasurypilot_api.database import create_session_factory
    from treasurypilot_api.observability.metrics import load_inputs
    from treasurypilot_api.recovery.models import ReviewItem

    engine, sessions = create_session_factory(database_url)
    try:
        async with engine.begin() as c:
            await _seed(c)

        def review(
            request: uuid.UUID,
            org: uuid.UUID,
            treasury: uuid.UUID,
            created: datetime,
            kind: str = "POLICY_BLOCK",
        ) -> ReviewItem:
            return ReviewItem(
                org_id=org,
                treasury_id=treasury,
                request_id=request,
                request_version=1,
                type=kind,
                primary_code="OVER_PER_REQUEST_LIMIT",
                reason_codes=["OVER_PER_REQUEST_LIMIT"],
                completed_steps=[],
                assigned_roles=["Owner"],
                sla_due_at=_at(2),
                created_at=created,
                resolved_by=_USER,
            )

        async with sessions() as session, session.begin():
            # One created in the period, one before it (still an intervention on a paid request).
            session.add(review(_REQ, _ORG, _TREASURY, _at(1, 2)))
            session.add(review(_REQ, _ORG, _TREASURY, START - timedelta(days=5), "NEEDS_AUTHORITY"))
            session.add(review(_REQ_B, _ORG_B, _TREASURY_B, _at(1, 2)))

        async def metrics(org: uuid.UUID, treasury: uuid.UUID | None) -> OperationsMetrics:
            async with sessions() as session:
                return compute_operations_metrics(
                    await load_inputs(session, org, START, END, treasury)
                )

        m = await metrics(_ORG, _TREASURY)
        assert (m.payments_count, m.on_time_rate, m.completion_rate) == (1, 1.0, 1.0)
        assert m.median_approval_minutes == 30.0
        assert m.interventions_per_request == 2.0
        assert m.rejections_by_reason == {"OVER_PER_REQUEST_LIMIT": 1}
        assert m.series[1].volume == "1000"
        assert m.tx_count == 2
        assert m.fees.total_wei == "100"
        assert m.fees.by_step_type == {"PAY": "100", "REFILL": "0"}
        assert m.reverts_by_selector == {"08c379a0": 1}
        assert m.unknown_operations == 1
        confirmed = m.latency_by_phase["submitToConfirmed"]
        assert confirmed is not None
        assert (confirmed.median_seconds, confirmed.count) == (120.0, 1)

        # Whole org: both treasuries, none of org B's rows (fee 999, its Unknown op).
        whole = await metrics(_ORG, None)
        assert whole.tx_count == 3
        assert whole.fees.by_step_type == {"PAY": "107", "REFILL": "0"}
        assert whole.unknown_operations == 1
        assert whole.payments_count == 1

        second = await metrics(_ORG, _TREASURY_2)
        assert (second.tx_count, second.fees.total_wei, second.unknown_operations) == (1, "7", 0)

        other = await metrics(_ORG_B, None)
        assert (other.tx_count, other.fees.total_wei, other.unknown_operations) == (1, "999", 1)
        assert other.interventions_per_request == 1.0

        empty = await metrics(uuid.uuid4(), None)
        assert (empty.payments_count, empty.tx_count) == (0, 0)
    finally:
        async with engine.begin() as c:
            # Replica role skips the append-only triggers so the migrations can downgrade.
            await c.execute(text("SET LOCAL session_replication_role = replica"))
            for sql in (
                "DELETE FROM review_items WHERE org_id IN (:o, :b)",
                "DELETE FROM gas_ledger WHERE treasury_id IN (:t, :t2, :tb)",
                "DELETE FROM transactions WHERE operation_id IN "
                "(SELECT id FROM operations WHERE treasury_id IN (:t, :t2, :tb))",
                "DELETE FROM operations WHERE treasury_id IN (:t, :t2, :tb)",
                "DELETE FROM request_status_events WHERE request_id IN (:r, :r2, :rb)",
                "DELETE FROM payment_requests WHERE id IN (:r, :r2, :rb)",
            ):
                await c.execute(
                    text(sql),
                    {
                        "o": _ORG,
                        "b": _ORG_B,
                        "t": _TREASURY,
                        "t2": _TREASURY_2,
                        "tb": _TREASURY_B,
                        "r": _REQ,
                        "r2": _REQ_2,
                        "rb": _REQ_B,
                    },
                )
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


# --- HTTP route ---

_PATH_ORG = uuid.UUID("00000000-0000-4000-8000-000000000111")


def _client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    roles: frozenset[str] = frozenset({"Finance"}),
    member_org: uuid.UUID = _PATH_ORG,
    sessions: object | None = lambda: None,
) -> tuple[TestClient, list[tuple[datetime, datetime]]]:
    from treasurypilot_api.config import Settings
    from treasurypilot_api.identity.auth import SessionAccess, UserRecord
    from treasurypilot_api.identity.rbac import MemberAccess, require_member
    from treasurypilot_api.main import create_app
    from treasurypilot_api.observability import metrics

    periods: list[tuple[datetime, datetime]] = []

    class _Session:
        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    async def fake_load(
        _s: object, _o: uuid.UUID, start: datetime, end: datetime, _t: uuid.UUID | None
    ) -> MetricInputs:
        periods.append((start, end))
        return MetricInputs(start, end, [])

    monkeypatch.setattr(metrics, "load_inputs", fake_load)
    app = create_app(settings=Settings(environment="local"))
    if sessions is not None:
        app.state.request_sessions = lambda: _Session()

    async def member(organization_id: uuid.UUID) -> MemberAccess:
        access = SessionAccess(
            user=UserRecord(uuid.uuid4(), "m@example.test", None, "active"),
            session_id=uuid.uuid4(),
            step_up_at=datetime.now(UTC),
        )
        return MemberAccess(access=access, organization_id=member_org, roles=roles)

    app.dependency_overrides[require_member] = member
    return TestClient(app), periods


def _url(query: str = "") -> str:
    return f"/v1/orgs/{_PATH_ORG}/metrics/operations{query}"


@pytest.mark.parametrize("role", ["Viewer", "Approver"])
def test_route_forbids_other_roles(monkeypatch: pytest.MonkeyPatch, role: str) -> None:
    client, _ = _client(monkeypatch, roles=frozenset({role}))
    assert client.get(_url()).status_code == 403


def test_route_cross_org_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch, member_org=uuid.uuid4())
    assert client.get(_url()).status_code == 404


def test_route_without_session_factory_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch, sessions=None)
    assert client.get(_url()).status_code == 503


@pytest.mark.parametrize(
    "query",
    ["?from=2026-10-03T00:00:00Z&to=2026-10-01T00:00:00Z", "?from=2025-01-01&to=2026-10-01"],
)
def test_route_rejects_bad_period(monkeypatch: pytest.MonkeyPatch, query: str) -> None:
    client, _ = _client(monkeypatch)
    assert client.get(_url(query)).status_code == 422


def test_route_accepts_naive_and_aware_datetimes(monkeypatch: pytest.MonkeyPatch) -> None:
    client, periods = _client(monkeypatch)
    naive = client.get(_url("?from=2026-10-01T00:00:00&to=2026-10-03T00:00:00"))
    aware = client.get(_url("?from=2026-10-01T07:00:00%2B07:00&to=2026-10-03T00:00:00Z"))
    assert naive.status_code == aware.status_code == 200
    assert periods[0] == periods[1] == (START, START + timedelta(days=2))
    assert client.get(_url("?from=2026-10-01T00:00:00")).status_code == 200  # to defaults to now
