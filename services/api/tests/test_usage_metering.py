import asyncio
import os
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from treasurypilot_api.admin.usage import parse_month

_PG = "TP_TEST_DATABASE_URL"
_ORG_A = uuid.UUID("00000000-0000-7000-8000-0000000000a1")
_ORG_B = uuid.UUID("00000000-0000-7000-8000-0000000000b1")
_ASSET = uuid.UUID("00000000-0000-7000-8000-0000000000c1")
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

            async def paid(org: uuid.UUID, amount: int, *events: tuple[str, datetime]) -> None:
                rid = uuid.uuid4()
                await c.execute(
                    text(
                        "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, amount, "
                        "asset_id, status) VALUES (:r, :o, :t, 11155111, :amt, :a, 'Draft')"
                    ),
                    {"r": rid, "o": org, "t": treasuries[org], "amt": amount, "a": _ASSET},
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

        async def run(month: date) -> list[tuple[uuid.UUID, int, int]]:
            async with sessions() as session, session.begin():
                rows = await recompute_month(session, month)
                return [(r.org_id, r.paid_count, r.paid_volume) for r in rows]

        october = date(2026, 10, 1)
        expected = sorted([(_ORG_A, 3, 3500), (_ORG_B, 1, _BIG)])
        first = await run(october)
        assert sorted(first) == expected
        assert sorted(await run(october)) == expected  # idempotent re-computation

        async with engine.connect() as c:
            stored = (
                await c.execute(text("SELECT org_id, paid_count, paid_volume FROM usage_monthly"))
            ).all()
        assert sorted((r[0], r[1], int(r[2])) for r in stored) == expected

        assert await run(date(2026, 9, 1)) == [(_ORG_A, 2, 2000)]  # other months are separate
        assert await run(date(2026, 12, 1)) == []

        # A new event arrives; recompute reconciles, and removing nothing leaves other months alone.
        async with engine.begin() as c:
            await c.execute(text("DELETE FROM usage_monthly WHERE month = '2026-10-01'"))
        assert sorted(await run(october)) == expected
    finally:
        async with engine.begin() as c:
            await c.execute(text("SET LOCAL session_replication_role = replica"))
            for sql in (
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
