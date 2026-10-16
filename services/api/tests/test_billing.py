"""Subscriptions and customer invoicing (ADM-L03): no fee is ever taken from a treasury."""

import ast
import asyncio
import io
import os
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr

from treasurypilot_api.admin import billing
from treasurypilot_api.admin.billing import (
    BillingError,
    CollectionRequest,
    FakePaymentProvider,
    price_lines,
)
from treasurypilot_api.admin.billing_models import BillingPlan
from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import SessionAccess, UserRecord
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.main import create_app

_PG = "TP_TEST_DATABASE_URL"
API_ROOT = Path(__file__).parents[1]
ORG = uuid.UUID("00000000-0000-7000-8000-0000000000d1")
ORG_B = uuid.UUID("00000000-0000-7000-8000-0000000000d2")
ASSET = uuid.UUID("00000000-0000-7000-8000-0000000000d3")
TOKEN = "x" * 48


def _plan(base: int = 5_000, per: int = 25) -> BillingPlan:
    return BillingPlan(
        id=uuid.uuid4(),
        code="pro",
        name="Pro",
        currency="USD",
        base_fee_minor=base,
        per_request_fee_minor=per,
    )


def test_price_lines_use_integer_minor_units() -> None:
    lines = price_lines(_plan(), 3, date(2026, 10, 1))
    assert [(k, q, u) for k, _, q, u in lines] == [("base", 1, 5_000), ("paid_requests", 3, 25)]
    assert sum(q * u for _, _, q, u in lines) == 5_075
    # No usage: only the base fee. A free plan yields a zero total.
    assert [k for k, *_ in price_lines(_plan(0, 25), 0, date(2026, 10, 1))] == ["base"]
    huge = price_lines(_plan(0, 10**12), 10**9, date(2026, 10, 1))
    assert sum(q * u for _, _, q, u in huge) == 10**21  # exact beyond 64-bit floats


def test_fake_provider_is_deterministic_and_offline() -> None:
    request = CollectionRequest(ORG, uuid.uuid4(), 100, "USD", "card", "key-1")
    provider = FakePaymentProvider(decline_orgs=frozenset({ORG_B}))
    first = asyncio.run(provider.collect(request))
    assert first == asyncio.run(provider.collect(request))
    assert first.succeeded and first.provider_ref.startswith("fake_")
    declined = asyncio.run(
        provider.collect(CollectionRequest(ORG_B, uuid.uuid4(), 1, "USD", "card", "k"))
    )
    assert not declined.succeeded and declined.failure_code == "card_declined"


def test_billing_modules_never_import_treasury_or_fund_moving_code() -> None:
    """BR-091: platform fees are collected in fiat, never from a customer treasury."""
    forbidden = {"treasury", "chain", "execution", "mandate", "invoices", "agent"}
    for name in ("billing.py", "billing_api.py", "billing_models.py"):
        tree = ast.parse((API_ROOT / "src/treasurypilot_api/admin" / name).read_text())
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            for module in modules:
                parts = module.split(".")
                assert not (
                    parts[0] == "treasurypilot_api" and len(parts) > 1 and parts[1] in forbidden
                ), f"{name} imports {module}"
    assert "treasury" not in billing.PaymentMethod.__args__[0] + billing.PaymentMethod.__args__[1]  # type: ignore[attr-defined]


def _client() -> TestClient:
    settings = Settings(
        environment="local",
        admin_staff_token=SecretStr(TOKEN),
        admin_staff_id="ops@example.test",
        admin_ip_allowlist="127.0.0.1/32",
        billing_provider="fake",
    )
    app = create_app(settings=settings, admin_sessions=cast(Any, lambda: None))
    return TestClient(app, client=("127.0.0.1", 50000))


def _as(client: TestClient, role: OrganizationRole) -> None:
    member = MemberAccess(
        access=SessionAccess(
            user=UserRecord(uuid.uuid4(), "u@example.test", "U", "active"),
            session_id=uuid.uuid4(),
        ),
        organization_id=ORG,
        roles=frozenset({role.value}),
    )
    client.app.dependency_overrides[require_member] = lambda: member  # type: ignore[attr-defined]


def test_org_billing_routes_expose_no_fund_movement_and_enforce_roles() -> None:
    client = _client()
    paths = {
        (path, method.upper())
        for path, ops in client.app.openapi()["paths"].items()  # type: ignore[attr-defined]
        if "/billing" in path
        for method in ops
    }
    assert {p for p in paths if p[0].startswith("/v1/")} == {
        ("/v1/orgs/{organization_id}/billing", "GET"),
        ("/v1/orgs/{organization_id}/billing/invoices", "GET"),
        ("/v1/orgs/{organization_id}/billing/invoices/{invoice_id}", "GET"),
        ("/v1/orgs/{organization_id}/billing/invoices/{invoice_id}/pay", "POST"),
    }
    _as(client, OrganizationRole.OPERATOR)
    assert client.get(f"/v1/orgs/{ORG}/billing").status_code == 403
    _as(client, OrganizationRole.AUDITOR)
    assert client.post(f"/v1/orgs/{ORG}/billing/invoices/{uuid.uuid4()}/pay").status_code == 403


def test_admin_billing_routes_validate_and_require_staff() -> None:
    client = _client()
    auth = {"Authorization": f"Bearer {TOKEN}"}
    assert client.post("/admin/billing/2026-09/invoices").status_code == 401
    assert client.post("/admin/billing/2026-13/invoices", headers=auth).status_code == 422
    bad = {
        "code": "Pro!",
        "name": "x",
        "currency": "usd",
        "baseFeeMinor": -1,
        "perRequestFeeMinor": 0,
    }
    assert client.post("/admin/billing/plans", headers=auth, json=bad).status_code == 422


def test_collection_is_off_without_a_provider() -> None:
    settings = Settings(environment="local")
    client = TestClient(create_app(settings=settings, admin_sessions=cast(Any, lambda: None)))
    _as(client, OrganizationRole.OWNER)
    assert client.post(f"/v1/orgs/{ORG}/billing/invoices/{uuid.uuid4()}/pay").status_code == 503


def test_fake_provider_is_refused_outside_local_and_test() -> None:
    with pytest.raises(ValueError, match="TP_BILLING_PROVIDER"):
        Settings(environment="production", billing_provider="fake")


def test_migration_creates_billing_tables_and_rolls_back() -> None:
    output = io.StringIO()
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://offline/offline")
    config.output_buffer = output

    command.upgrade(config, "20261016_0093:20261016_0094", sql=True)
    command.downgrade(config, "20261016_0094:20261016_0093", sql=True)

    sql = output.getvalue()
    for table in (
        "billing_plans",
        "billing_subscriptions",
        "billing_invoices",
        "billing_invoice_lines",
    ):
        assert f"CREATE TABLE {table}" in sql and f"DROP TABLE {table}" in sql
    assert "ck_billing_subscriptions_method" in sql and "uq_billing_subscriptions_active_org" in sql


async def _exercise(url: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from treasurypilot_api.admin.billing import (
        collect_invoice,
        create_plan,
        generate_invoices,
        subscribe,
    )
    from treasurypilot_api.database import create_session_factory

    engine, sessions = create_session_factory(url)
    now = datetime(2026, 11, 3, tzinfo=UTC)
    october = date(2026, 10, 1)
    try:
        async with engine.begin() as c:
            await c.execute(
                text(
                    "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, "
                    "rpc_urls) VALUES (11155111, 'Sepolia', true, 3, 'https://x.test', "
                    "'[\"https://rpc\"]')"
                )
            )
            await c.execute(
                text(
                    "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
                    "VALUES (:a, 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')"
                ),
                {"a": ASSET},
            )
            treasury = uuid.uuid4()
            for org in (ORG, ORG_B):
                await c.execute(
                    text("INSERT INTO organizations (id, name) VALUES (:o, 'B')"), {"o": org}
                )
            await c.execute(
                text(
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id) "
                    "VALUES (:t, :o, 11155111, :a)"
                ),
                {"t": treasury, "o": ORG, "a": ASSET},
            )
            for day in (5, 6):
                request = uuid.uuid4()
                await c.execute(
                    text(
                        "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, amount, "
                        "asset_id, status) VALUES (:r, :o, :t, 11155111, 1000, :a, 'Draft')"
                    ),
                    {"r": request, "o": ORG, "t": treasury, "a": ASSET},
                )
                await c.execute(
                    text(
                        'INSERT INTO request_status_events (id, request_id, "to", actor_type, at) '
                        "VALUES (gen_random_uuid(), :r, 'Paid', 'SYSTEM', :at)"
                    ),
                    {"r": request, "at": datetime(2026, 10, day, tzinfo=UTC)},
                )

        async def balance_snapshot() -> list[object]:
            async with engine.connect() as c:
                rows = await c.execute(
                    text("SELECT id, amount, status FROM payment_requests ORDER BY id")
                )
                return [tuple(r) for r in rows]

        before = await balance_snapshot()
        async with sessions() as session, session.begin():
            plan = await create_plan(
                session,
                code="pro",
                name="Pro",
                currency="USD",
                base_fee_minor=5_000,
                per_request_fee_minor=25,
            )
            with pytest.raises(BillingError):
                await create_plan(
                    session,
                    code="pro",
                    name="Dup",
                    currency="USD",
                    base_fee_minor=1,
                    per_request_fee_minor=1,
                )
            await subscribe(
                session,
                org_id=ORG,
                plan_id=plan.id,
                payment_method="card",
                now=datetime(2026, 9, 1, tzinfo=UTC),
            )
            # Re-subscribing replaces the active subscription; still exactly one is active.
            second = await subscribe(
                session,
                org_id=ORG,
                plan_id=plan.id,
                payment_method="bank_transfer",
                now=datetime(2026, 9, 2, tzinfo=UTC),
            )
            await subscribe(
                session,
                org_id=ORG_B,
                plan_id=plan.id,
                payment_method="card",
                now=datetime(2026, 11, 2, tzinfo=UTC),  # starts after October: not billed
            )
            plan_id = plan.id

        async with sessions() as session, session.begin():
            with pytest.raises(BillingError) as early:
                await generate_invoices(session, date(2026, 11, 1), now=now)
            assert early.value.code == "MONTH_NOT_CLOSED"

        async with sessions() as session, session.begin():
            created = await generate_invoices(session, october, now=now)
            assert [(i.org_id, i.total_minor, i.status) for i in created] == [(ORG, 5_050, "open")]
            assert created[0].subscription_id == second.id
            invoice_id = created[0].id
        async with sessions() as session, session.begin():
            assert await generate_invoices(session, october, now=now) == []  # idempotent

        provider = FakePaymentProvider()
        async with sessions() as session, session.begin():
            paid = await collect_invoice(
                session, provider, org_id=ORG, invoice_id=invoice_id, now=now
            )
            assert paid.status == "paid" and paid.provider == "fake"
        async with sessions() as session, session.begin():
            again = await collect_invoice(
                session, provider, org_id=ORG, invoice_id=invoice_id, now=now
            )
            assert again.status == "paid"
        assert len(provider.calls) == 1  # a paid invoice is never charged twice
        assert provider.calls[0].payment_method == "bank_transfer"
        assert provider.calls[0].amount_minor == 5_050
        with pytest.raises(BillingError) as other:
            async with sessions() as session, session.begin():
                await collect_invoice(
                    session, provider, org_id=ORG_B, invoice_id=invoice_id, now=now
                )
        assert other.value.code == "INVOICE_NOT_FOUND"  # org-scoped

        declining = FakePaymentProvider(decline_orgs=frozenset({ORG}))
        async with engine.begin() as c:
            await c.execute(text("UPDATE billing_invoices SET status = 'open', paid_at = NULL"))
        async with sessions() as session, session.begin():
            failed = await collect_invoice(
                session, declining, org_id=ORG, invoice_id=invoice_id, now=now
            )
            assert failed.status == "payment_failed" and failed.paid_at is None

        # The database refuses any payment source other than card or bank transfer.
        for method in ("treasury", "wallet"):
            with pytest.raises(IntegrityError):
                async with engine.begin() as c:
                    await c.execute(
                        text(
                            "INSERT INTO billing_subscriptions (id, org_id, plan_id, status, "
                            "payment_method) VALUES (gen_random_uuid(), :o, :p, 'cancelled', :m)"
                        ),
                        {"o": ORG, "p": plan_id, "m": method},
                    )
        # Invoicing and collection left every customer payment request untouched.
        assert await balance_snapshot() == before
    finally:
        async with engine.begin() as c:
            await c.execute(text("SET LOCAL session_replication_role = replica"))
            for table in (
                "billing_invoice_lines",
                "billing_invoices",
                "billing_subscriptions",
                "billing_plans",
                "usage_monthly",
                "request_status_events",
                "payment_requests",
            ):
                await c.execute(text(f"DELETE FROM {table}"))  # noqa: S608
        await engine.dispose()


@pytest.mark.skipif(_PG not in os.environ, reason=f"{_PG} is required for the PostgreSQL test")
def test_invoicing_and_collection_never_touch_customer_treasuries() -> None:
    url = os.environ[_PG]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_exercise(url))
    finally:
        command.downgrade(config, "base")
