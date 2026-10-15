from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from treasurypilot_api.observability.savings import (
    LoadedSavings,
    SavingsBatch,
    SavingsMetrics,
    SavingsRequest,
    compute_savings,
)
from treasurypilot_core.domain import (
    ApprovedRequest,
    LateFee,
    Limits,
    PaymentTerms,
    PolicyView,
    Snapshot,
    WalletState,
)
from treasurypilot_core.money import BaseUnits as U


def _snapshot(day: int) -> Snapshot:
    wallet = WalletState(address="w", balance=U(10**9), buffer=U(0), target=U(0))
    source = wallet.model_copy(update={"address": "src"})
    return Snapshot(
        day=day,
        source=source,
        operational={"w": wallet},
        used_today={"pay": U(0), "refill": U(0)},
        payee_active_day={"p": 0},
        safe_usdc=U(10**9),
        a_usdc=U(0),
        pool_available=U(0),
        supply_rate_bps=0,
        borrow_rate_bps=0,
        debt=U(0),
    )


def _policy(daily: int) -> PolicyView:
    limits = Limits(per_request=U(10**9), daily=U(daily))
    return PolicyView(pay=limits, refill=limits, cooling_seconds=0)


def _req(
    name: str, amount: int, due: int, bps: int = 0, deadline: int | None = None, late: int = 0
) -> ApprovedRequest:
    return ApprovedRequest(
        id=name,
        paying_wallet="w",
        payee="p",
        amount=U(amount),
        approved_seq=0,
        terms=PaymentTerms(
            net_due_day=due,
            discount_bps=bps,
            discount_deadline_day=deadline,
            late_fee=LateFee(kind="fixed", amount=U(late)) if late else None,
        ),
    )


def _batches() -> list[SavingsBatch]:
    # Batch 1 (day 100, daily cap 1000). EDF order r1 (due 101), r2 (due 102).
    #   B1: r1 pays 990 on day 100 (1% = 10 saved, minus 5 gas = 5); r2's early 570 would exceed the cap, so it
    #   pays 600 on day 101 (no discount). B1 value: r1 5, r2 0.
    #   Actual: r2 early on day 100 (5% = 30 saved, minus 5 early-payment gas = 25), r1 on
    #   day 101 at 1000 (value 0). Saved: r1 -5, r2 +25 = +20; batch 2 below -7, total 13.
    r1 = _req("r1", 1000, 101, 100, 100)
    r2 = _req("r2", 600, 102, 500, 100)
    # Batch 2 (day 200): r3 due day 200 with a fixed late fee of 7. B1 pays on time (value 0);
    #   actual pays on day 202 (value -7). Saved: -7.
    r3 = _req("r3", 400, 200, late=7)
    return [
        SavingsBatch(
            _snapshot(100),
            _policy(1000),
            [SavingsRequest(r1, "I-1", "Acme", 101, 5), SavingsRequest(r2, "I-2", "Acme", 100, 5)],
        ),
        SavingsBatch(_snapshot(200), _policy(1000), [SavingsRequest(r3, "I-3", "Beta", 202, 5)]),
    ]


def test_savings_equal_hand_computed_value() -> None:
    m = compute_savings(_batches())
    rows = {r.request_id: (r.baseline, r.actual, r.saved) for r in m.per_request}
    assert rows == {
        "r1": ("995", "1000", "-5"),
        "r2": ("600", "575", "25"),
        "r3": ("400", "407", "-7"),
    }
    assert (m.totals.baseline, m.totals.actual, m.totals.saved) == ("1995", "1982", "13")
    assert "earliest-deadline-first" in m.methodology


def test_negative_savings_are_reported_negative() -> None:
    m = compute_savings(_batches()[1:])
    assert m.totals.saved == "-7"
    assert m.per_request[0].saved == "-7"


def test_unschedulable_requests_are_counted_as_skipped() -> None:
    # Cap below the amount: B1 can never pay r1, so it is not compared but is counted.
    batch = SavingsBatch(
        _snapshot(100), _policy(10), [SavingsRequest(_req("r1", 1000, 101), "I", "A", 101, 0)]
    )
    m = compute_savings([batch], skipped=1)
    assert (m.per_request, m.skipped) == ([], 2)


def test_empty_is_zero() -> None:
    m = compute_savings([])
    assert (m.totals.saved, m.per_request) == ("0", [])


# --- PostgreSQL loader ---

_PG = "TP_TEST_DATABASE_URL"
_IDS = {
    k: uuid.UUID(f"00000000-0000-7000-8000-0000000000{v}")
    for k, v in {
        "user": "d1",
        "asset": "d2",
        "org": "d3",
        "treasury": "d4",
        "vendor": "d5",
        "req": "d6",
        "op": "d7",
        "tx": "d8",
        "other_org": "e3",
        "other_treasury": "e4",
        "other_vendor": "e5",
        "other_req": "e6",
        "req2": "d9",
        "payee": "da",
        "other_payee": "ea",
    }.items()
}
_START = datetime(2026, 10, 1, tzinfo=UTC)
_END = datetime(2026, 10, 12, tzinfo=UTC)


async def _exercise(database_url: str) -> None:
    from sqlalchemy import text

    from treasurypilot_api.database import create_session_factory
    from treasurypilot_api.observability.savings import load_savings_batches

    ids = _IDS
    day = int(datetime(2026, 10, 10, tzinfo=UTC).timestamp()) // 86_400
    terms = f'{{"net_due_day": {day}, "discount_bps": 100, "discount_deadline_day": {day - 1}}}'
    engine, sessions = create_session_factory(database_url)
    try:
        async with engine.begin() as c:

            async def run(sql: str, **p: object) -> None:
                await c.execute(text(sql), p)

            await run("INSERT INTO users (id, email) VALUES (:u, 's@example.test')", u=ids["user"])
            await run(
                "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, "
                "rpc_urls) VALUES (11155111, 'Sepolia', true, 3, 'https://x.test', "
                "'[\"https://rpc\"]')"
            )
            await run(
                "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
                "VALUES (:a, 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
                a=ids["asset"],
            )
            for org, treasury, vendor, req in [
                ("org", "treasury", "vendor", "req"),
                ("other_org", "other_treasury", "other_vendor", "other_req"),
            ]:
                await run("INSERT INTO organizations (id, name) VALUES (:o, 'S')", o=ids[org])
                await run(
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id) "
                    "VALUES (:t, :o, 11155111, :a)",
                    t=ids[treasury],
                    o=ids[org],
                    a=ids["asset"],
                )
                await run(
                    "INSERT INTO vendors (id, org_id, name, normalized_ref, version) "
                    "VALUES (:v, :o, 'Acme Ltd', :n, 1)",
                    v=ids[vendor],
                    o=ids[org],
                    n=str(ids[vendor]),
                )
                await run(
                    "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, "
                    "invoice_no, issue_date, due_at, amount, asset_id, status, terms, "
                    "terms_confirmed_by, terms_confirmed_at) VALUES (:r, :o, :t, 11155111, :v, "
                    "'INV-7', CAST('2026-10-01' AS date), CAST('2026-10-10' AS date), 1000, :a, 'Draft', "
                    "CAST(:terms AS jsonb), :u, now())",
                    r=ids[req],
                    o=ids[org],
                    t=ids[treasury],
                    v=ids[vendor],
                    a=ids["asset"],
                    terms=terms,
                    u=ids["user"],
                )
                for to, at in [
                    ("Scheduled", datetime(2026, 10, 8, 12, tzinfo=UTC)),
                    ("Paid", datetime(2026, 10, 10, 12, tzinfo=UTC)),
                ]:
                    await run(
                        'INSERT INTO request_status_events (id, request_id, "to", actor_type, at) '
                        "VALUES (gen_random_uuid(), :r, :to, 'SYSTEM', :at)",
                        r=ids[req],
                        to=to,
                        at=at,
                    )
            for org, treasury, vendor, payee, cap in [
                ("org", "treasury", "vendor", "payee", 1000),
                ("other_org", "other_treasury", "other_vendor", "other_payee", 10**9),
            ]:
                await run(
                    "INSERT INTO payees (id, org_id, treasury_id, vendor_id, label, address, "
                    "status, active_from, oob_verified_by, oob_verified_at, oob_method, oob_note, "
                    "version) VALUES (:p, :o, :t, :v, 'Acme', decode(repeat('44', 20), 'hex'), "
                    "'Active', CAST('2026-09-01' AS timestamptz), :u, now(), 'PHONE', 'ok', 1)",
                    p=ids[payee],
                    o=ids[org],
                    t=ids[treasury],
                    v=ids[vendor],
                    u=ids["user"],
                )
                await run(
                    "INSERT INTO mandate_versions (id, org_id, treasury_id, version, "
                    "onchain_version, status, config, config_hash, valid_from, expires_at, "
                    "created_by, activated_at) VALUES (gen_random_uuid(), :o, :t, 1, 1, 'Active', "
                    "CAST(:cfg AS jsonb), decode(repeat('55', 32), 'hex'), "
                    "CAST('2026-09-01' AS timestamptz), CAST('2027-01-01' AS timestamptz), :u, "
                    "CAST('2026-09-01' AS timestamptz))",
                    o=ids[org],
                    t=ids[treasury],
                    u=ids["user"],
                    cfg=f'{{"limits": {{"PAY": {{"perRequest": "{cap}", "daily": "{cap}"}}}}}}',
                )
            await run(
                "UPDATE payment_requests SET payee_id = :p WHERE id = :r",
                p=ids["payee"],
                r=ids["req"],
            )
            await run(
                "UPDATE payment_requests SET payee_id = :p WHERE id = :r",
                p=ids["other_payee"],
                r=ids["other_req"],
            )
            # req2: bigger discount, lapses after day 8, so the day-8 daily cap decides who gets it.
            await run(
                "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, "
                "payee_id, invoice_no, issue_date, due_at, amount, asset_id, status, terms, "
                "terms_confirmed_by, terms_confirmed_at) VALUES (:r, :o, :t, 11155111, :v, :p, "
                "'INV-8', CAST('2026-10-01' AS date), CAST('2026-10-11' AS date), 1000, :a, "
                "'Draft', CAST(:terms AS jsonb), :u, now())",
                r=ids["req2"],
                o=ids["org"],
                t=ids["treasury"],
                v=ids["vendor"],
                p=ids["payee"],
                a=ids["asset"],
                terms=f'{{"net_due_day": {day + 1}, "discount_bps": 500, '
                f'"discount_deadline_day": {day - 2}}}',
                u=ids["user"],
            )
            for to, at in [
                ("Scheduled", datetime(2026, 10, 8, 12, tzinfo=UTC)),
                ("Paid", datetime(2026, 10, 8, 13, tzinfo=UTC)),
            ]:
                await run(
                    'INSERT INTO request_status_events (id, request_id, "to", actor_type, at) '
                    "VALUES (gen_random_uuid(), :r, :to, 'SYSTEM', :at)",
                    r=ids["req2"],
                    to=to,
                    at=at,
                )
            await run(
                "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, "
                "kind, payload, idempotency_key, status) VALUES (:id, :t, :id, :r, "
                "decode(repeat('01', 32), 'hex'), 'PAY', '{}'::jsonb, 'op-1', 'Confirmed')",
                id=ids["op"],
                t=ids["treasury"],
                r=ids["req"],
            )
            await run(
                "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, "
                "from_address, submitted_at) VALUES (:id, :op, 11155111, "
                "decode(repeat('01', 32), 'hex'), 0, decode(repeat('33', 20), 'hex'), now())",
                id=ids["tx"],
                op=ids["op"],
            )
            await run(
                "INSERT INTO gas_ledger (id, treasury_id, transaction_id, payer, payer_address, "
                "fee_wei, day) VALUES (gen_random_uuid(), :t, :tx, 'EXECUTOR', "
                "decode(repeat('33', 20), 'hex'), 2000000000, CAST('2026-10-10' AS date))",
                t=ids["treasury"],
                tx=ids["tx"],
            )
            # A liquidity operation (no request) with gas must not disturb the per-request numbers.
            await run(
                "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, "
                "kind, payload, idempotency_key, status) VALUES (gen_random_uuid(), :t, "
                "gen_random_uuid(), NULL, decode(repeat('02', 32), 'hex'), 'SUPPLY', "
                "'{}'::jsonb, 'op-liq', 'Confirmed')",
                t=ids["treasury"],
            )
            await run(
                "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, "
                "from_address, submitted_at) SELECT gen_random_uuid(), id, 11155111, "
                "decode(repeat('02', 32), 'hex'), 1, decode(repeat('33', 20), 'hex'), now() "
                "FROM operations WHERE idempotency_key = 'op-liq'"
            )
            await run(
                "INSERT INTO gas_ledger (id, treasury_id, transaction_id, payer, payer_address, "
                "fee_wei, day) SELECT gen_random_uuid(), :t, tx.id, 'EXECUTOR', "
                "decode(repeat('33', 20), 'hex'), 5000000000, CAST('2026-10-10' AS date) "
                "FROM transactions tx WHERE tx.tx_hash = decode(repeat('02', 32), 'hex')",
                t=ids["treasury"],
            )
            await run(
                "INSERT INTO treasury_fee_policies (id, org_id, treasury_id, preset, "
                "max_fee_multiplier_bps, tip_percentile, resend_after_s, bump_bps, "
                "per_plan_threshold_wei, daily_budget_wei, reference_eth_price, accepted_by, "
                "accepted_at, version, row_version) VALUES (gen_random_uuid(), :o, :t, 'NORMAL', "
                "20000, 50, 60, 1250, 1, 1, 2000000000, :u, now(), 1, 1)",
                o=ids["org"],
                t=ids["treasury"],
                u=ids["user"],
            )

        async def savings(org: uuid.UUID) -> SavingsMetrics:
            async with sessions() as session:
                loaded = await load_savings_batches(session, org, _START, _END)
                return compute_savings(loaded.batches, loaded.skipped, loaded.warnings)

        # Fee 2e9 wei * 2e9 / 1e18 = 4 on INV-7 only (INV-8 has no gas). The 1000 daily cap binds
        # on day 8: B1 (EDF, INV-7 due first) takes the cap for INV-7 (1% off, cost 994) and
        # INV-8 misses its 5% window (1000). Actual: INV-8 early (950), INV-7 on its due day
        # (1000). Saved: (994 + 1000) - (1000 + 950) = +44, from persisted data alone.
        m = await savings(ids["org"])
        rows = {r.invoice_number: (r.baseline, r.actual, r.saved) for r in m.per_request}
        assert rows == {"INV-7": ("994", "1000", "-6"), "INV-8": ("1000", "950", "50")}
        assert m.totals.saved == "44"
        assert m.skipped == 0 and m.warnings == []

        other = await savings(ids["other_org"])  # no fee policy: fee 0 -> B1 cost 990
        assert [r.baseline for r in other.per_request] == ["990"]
        assert (await savings(uuid.uuid4())).per_request == []
    finally:
        async with engine.begin() as c:
            await c.execute(text("SET LOCAL session_replication_role = replica"))
            for sql in (
                "DELETE FROM treasury_fee_policies",
                "DELETE FROM gas_ledger",
                "DELETE FROM transactions",
                "DELETE FROM operations",
                "DELETE FROM request_status_events",
                "DELETE FROM payment_requests",
            ):
                await c.execute(text(sql))
        await engine.dispose()


@pytest.mark.skipif(_PG not in os.environ, reason=f"{_PG} is required for the PostgreSQL test")
def test_postgres_loader_matches_hand_computed_savings() -> None:
    database_url = os.environ[_PG]
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_exercise(database_url))
    finally:
        command.downgrade(config, "base")


# --- HTTP route ---

_ORG = uuid.UUID("00000000-0000-4000-8000-000000000111")


def _client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    roles: frozenset[str] = frozenset({"Finance"}),
    member_org: uuid.UUID = _ORG,
    sessions: bool = True,
) -> TestClient:
    from treasurypilot_api.config import Settings
    from treasurypilot_api.identity.auth import SessionAccess, UserRecord
    from treasurypilot_api.identity.rbac import MemberAccess, require_member
    from treasurypilot_api.main import create_app
    from treasurypilot_api.observability import savings

    class _Session:
        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    async def fake_load(*_: object) -> LoadedSavings:
        return LoadedSavings(_batches(), skipped=2, warnings=("w",))

    monkeypatch.setattr(savings, "load_savings_batches", fake_load)
    app = create_app(settings=Settings(environment="local"))
    if sessions:
        app.state.request_sessions = lambda: _Session()

    async def member(organization_id: uuid.UUID) -> MemberAccess:
        access = SessionAccess(
            user=UserRecord(uuid.uuid4(), "m@example.test", None, "active"),
            session_id=uuid.uuid4(),
            step_up_at=datetime.now(UTC),
        )
        return MemberAccess(access=access, organization_id=member_org, roles=roles)

    app.dependency_overrides[require_member] = member
    return TestClient(app)


def _url(query: str = "") -> str:
    return f"/v1/orgs/{_ORG}/metrics/savings{query}"


def test_route_returns_web_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    body = cast(dict[str, object], _client(monkeypatch).get(_url()).json())
    assert set(body) == {"totals", "perRequest", "skipped", "warnings", "methodology"}
    assert (body["skipped"], body["warnings"]) == (2, ["w"])
    assert body["totals"] == {"baseline": "1995", "actual": "1982", "saved": "13"}


@pytest.mark.parametrize("role", ["Viewer", "Auditor", "Approver"])
def test_route_forbids_other_roles(monkeypatch: pytest.MonkeyPatch, role: str) -> None:
    assert _client(monkeypatch, roles=frozenset({role})).get(_url()).status_code == 403


def test_route_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _client(monkeypatch, member_org=uuid.uuid4()).get(_url()).status_code == 404
    assert _client(monkeypatch, sessions=False).get(_url()).status_code == 503
    bad = "?from=2026-10-03T00:00:00Z&to=2026-10-01T00:00:00Z"
    assert _client(monkeypatch).get(_url(bad)).status_code == 422
