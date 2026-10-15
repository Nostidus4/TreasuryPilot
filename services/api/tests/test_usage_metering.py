import asyncio
import os
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr

from treasurypilot_api.admin.usage import parse_month
from treasurypilot_api.config import Settings
from treasurypilot_api.main import create_app

_PG = "TP_TEST_DATABASE_URL"
_ORG_A = uuid.UUID("00000000-0000-7000-8000-0000000000a1")
_ORG_B = uuid.UUID("00000000-0000-7000-8000-0000000000b1")
_ASSET = uuid.UUID("00000000-0000-7000-8000-0000000000c1")
_ASSET2 = uuid.UUID("00000000-0000-7000-8000-0000000000c2")  # 18 decimals
_BIG = 10**30  # beyond 64-bit: volume must stay an exact integer


def test_parse_month() -> None:
    assert parse_month("2026-10") == date(2026, 10, 1)
    for bad in ("2026-13", "2026-1", "26-10", "2026-10-01", ""):
        with pytest.raises(ValueError):
            parse_month(bad)


async def _exercise(url: str) -> None:
    from sqlalchemy import text

    from treasurypilot_api.admin.usage import recompute_month
    from treasurypilot_api.database import create_session_factory

    engine, sessions = create_session_factory(url)
    plus7 = timezone(timedelta(hours=7))
    try:
        async with engine.begin() as c:
            await c.execute(
                text("INSERT INTO users (id, email) VALUES (gen_random_uuid(), 'u@x.test')")
            )
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
                {"a": _ASSET},
            )
            await c.execute(
                text(
                    "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
                    "VALUES (:a, 11155111, decode(repeat('22', 20), 'hex'), 'DAI', 18, 'Maker')"
                ),
                {"a": _ASSET2},
            )
            treasuries = {}
            for org in (_ORG_A, _ORG_B):
                treasuries[org] = uuid.uuid4()
                await c.execute(
                    text("INSERT INTO organizations (id, name) VALUES (:o, 'U')"), {"o": org}
                )
                await c.execute(
                    text(
                        "INSERT INTO treasuries (id, org_id, chain_id, asset_id) "
                        "VALUES (:t, :o, 11155111, :a)"
                    ),
                    {"t": treasuries[org], "o": org, "a": _ASSET},
                )

            async def paid(
                org: uuid.UUID,
                amount: int,
                *events: tuple[str, datetime],
                asset: uuid.UUID = _ASSET,
            ) -> None:
                rid = uuid.uuid4()
                await c.execute(
                    text(
                        "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, amount, "
                        "asset_id, status) VALUES (:r, :o, :t, 11155111, :amt, :a, 'Draft')"
                    ),
                    {"r": rid, "o": org, "t": treasuries[org], "amt": amount, "a": asset},
                )
                for to, at in events:
                    await c.execute(
                        text(
                            'INSERT INTO request_status_events (id, request_id, "to", actor_type, at) '
                            "VALUES (gen_random_uuid(), :r, :to, 'SYSTEM', :at)"
                        ),
                        {"r": rid, "to": to, "at": at},
                    )

            utc = lambda *a: datetime(*a, tzinfo=UTC)  # noqa: E731
            await paid(_ORG_A, 100, ("Paid", utc(2026, 10, 1)))  # first instant of October
            await paid(_ORG_A, 200, ("Paid", utc(2026, 10, 31, 23, 59, 59)))  # last second
            await paid(_ORG_A, 400, ("Paid", utc(2026, 9, 30, 23, 59, 59)))  # September
            await paid(_ORG_A, 800, ("Paid", utc(2026, 11, 1)))  # November
            # 2026-10-01 05:00+07 is still 30 Sep in UTC.
            await paid(_ORG_A, 1600, ("Paid", datetime(2026, 10, 1, 5, tzinfo=plus7)))
            # Duplicate Paid events count once, in the first Paid month.
            await paid(_ORG_A, 3200, ("Paid", utc(2026, 10, 5)), ("Paid", utc(2026, 11, 5)))
            await paid(_ORG_A, 6400, ("Scheduled", utc(2026, 10, 5)))  # not paid
            await paid(_ORG_B, _BIG, ("Paid", utc(2026, 10, 15)))
            # Another asset of the same org is metered in its own row, never summed with USDC.
            await paid(_ORG_A, 10**18, ("Paid", utc(2026, 10, 7)), asset=_ASSET2)

        async def run(month: date) -> list[tuple[uuid.UUID, uuid.UUID, int, int]]:
            async with sessions() as session, session.begin():
                rows = await recompute_month(session, month)
                return [(r.org_id, r.asset_id, r.paid_count, r.paid_volume) for r in rows]

        october = date(2026, 10, 1)
        expected = sorted(
            [
                (_ORG_A, _ASSET, 3, 3500),
                (_ORG_A, _ASSET2, 1, 10**18),
                (_ORG_B, _ASSET, 1, _BIG),
            ]
        )
        first = await run(october)
        assert sorted(first) == expected
        assert sorted(await run(october)) == expected  # idempotent re-computation

        async with engine.connect() as c:
            stored = (
                await c.execute(
                    text("SELECT org_id, asset_id, paid_count, paid_volume FROM usage_monthly")
                )
            ).all()
        assert sorted((r[0], r[1], r[2], int(r[3])) for r in stored) == expected

        # Two concurrent recomputes of one month serialize on the advisory lock; both succeed.
        both = await asyncio.gather(run(october), run(october))
        assert all(sorted(r) == expected for r in both)

        assert await run(date(2026, 9, 1)) == [
            (_ORG_A, _ASSET, 2, 2000)
        ]  # other months are separate
        assert await run(date(2026, 12, 1)) == []

        # Rows lost from the table are rebuilt from the event store by the next recompute.
        async with engine.begin() as c:
            await c.execute(text("DELETE FROM usage_monthly WHERE month = '2026-10-01'"))
        assert sorted(await run(october)) == expected
    finally:
        async with engine.begin() as c:
            await c.execute(text("SET LOCAL session_replication_role = replica"))
            for sql in (
                "DELETE FROM platform_admin_events",
                "DELETE FROM usage_monthly",
                "DELETE FROM request_status_events",
                "DELETE FROM payment_requests",
            ):
                await c.execute(text(sql))
        await engine.dispose()


@pytest.mark.skipif(_PG not in os.environ, reason=f"{_PG} is required for the PostgreSQL test")
def test_usage_reconciles_with_event_store_in_utc_months() -> None:
    url = os.environ[_PG]
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_exercise(url))
    finally:
        command.downgrade(config, "base")


def _admin_client(sessions: object) -> TestClient:
    settings = Settings(
        environment="local",
        admin_staff_token=SecretStr("x" * 48),
        admin_staff_id="ops@example.test",
        admin_ip_allowlist="127.0.0.1/32",
    )
    app = create_app(settings=settings, admin_sessions=cast(Any, sessions))
    return TestClient(app, client=("127.0.0.1", 50000))


def test_usage_route_validation_and_auth_need_no_database() -> None:
    client = _admin_client(lambda: None)
    auth = {"Authorization": "Bearer " + "x" * 48}

    assert client.post("/admin/usage/2026-13/recompute", headers=auth).status_code == 422
    assert client.get("/admin/usage?month=2026-13", headers=auth).status_code == 422
    assert client.post("/admin/usage/2026-10/recompute").status_code == 401
    assert client.get("/admin/usage?month=2026-10").status_code == 401
    other_ip = TestClient(client.app, client=("192.0.2.9", 1))
    assert other_ip.post("/admin/usage/2026-10/recompute", headers=auth).status_code == 403


async def _seed_one_paid(url: str) -> None:
    from sqlalchemy import text

    from treasurypilot_api.database import create_session_factory

    engine, _ = create_session_factory(url)
    t, r = uuid.uuid4(), uuid.uuid4()
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
                {"a": _ASSET},
            )
            await c.execute(
                text("INSERT INTO organizations (id, name) VALUES (:o, 'U')"), {"o": _ORG_A}
            )
            await c.execute(
                text(
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id) "
                    "VALUES (:t, :o, 11155111, :a)"
                ),
                {"t": t, "o": _ORG_A, "a": _ASSET},
            )
            await c.execute(
                text(
                    "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, amount, "
                    "asset_id, status) VALUES (:r, :o, :t, 11155111, 500, :a, 'Draft')"
                ),
                {"r": r, "o": _ORG_A, "t": t, "a": _ASSET},
            )
            await c.execute(
                text(
                    'INSERT INTO request_status_events (id, request_id, "to", actor_type, at) '
                    "VALUES (gen_random_uuid(), :r, 'Paid', 'SYSTEM', '2026-10-05T00:00:00Z')"
                ),
                {"r": r},
            )
    finally:
        await engine.dispose()


async def _cleanup(url: str) -> None:
    from sqlalchemy import text

    from treasurypilot_api.database import create_session_factory

    engine, _ = create_session_factory(url)
    try:
        async with engine.begin() as c:
            await c.execute(text("SET LOCAL session_replication_role = replica"))
            for table in (
                "platform_admin_events",
                "usage_monthly",
                "request_status_events",
                "payment_requests",
            ):
                await c.execute(text(f"DELETE FROM {table}"))  # noqa: S608
    finally:
        await engine.dispose()


async def _audit_events(url: str) -> list[tuple[uuid.UUID, str, str, dict[str, object]]]:
    from sqlalchemy import text

    from treasurypilot_api.database import create_session_factory

    engine, _ = create_session_factory(url)
    try:
        async with engine.connect() as c:
            rows = (
                await c.execute(
                    text("SELECT org_id, actor_id, action, data FROM platform_admin_events")
                )
            ).all()
        return [(r[0], r[1], r[2], r[3]) for r in rows]
    finally:
        await engine.dispose()


@pytest.mark.skipif(_PG not in os.environ, reason=f"{_PG} is required for the PostgreSQL test")
def test_usage_routes_recompute_audit_and_read() -> None:
    from treasurypilot_api.database import create_session_factory

    url = os.environ[_PG]
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed_one_paid(url))
        _, sessions = create_session_factory(url)
        auth = {"Authorization": "Bearer " + "x" * 48}
        with _admin_client(sessions) as client:
            posted = client.post("/admin/usage/2026-10/recompute", headers=auth)
            assert posted.status_code == 200
            got = client.get("/admin/usage?month=2026-10", headers=auth)
            assert got.json() == posted.json()
            assert got.json()["items"] == [
                {
                    "orgId": str(_ORG_A),
                    "month": "2026-10",
                    "assetId": str(_ASSET),
                    "paidCount": 1,
                    "paidVolume": "500",
                }
            ]
            other = client.get(f"/admin/usage?month=2026-10&org_id={_ORG_B}", headers=auth)
            assert other.json() == {"items": []}

        events = asyncio.run(_audit_events(url))
        assert events == [
            (
                _ORG_A,
                "ops@example.test",
                "usage.recomputed",
                {"month": "2026-10", "source_ip": "127.0.0.1", "orgs": [str(_ORG_A)]},
            )
        ]
    finally:
        asyncio.run(_cleanup(url))
        command.downgrade(config, "base")
