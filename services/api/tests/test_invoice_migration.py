from __future__ import annotations

import asyncio
import io
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.invoices.requests import _recompute_flags

API_ROOT = Path(__file__).parents[1]


def alembic_config(*, database_url: str | None = None) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    url = database_url or "postgresql+asyncpg://offline/offline"
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def test_invoice_upgrade_and_downgrade_compile_offline() -> None:
    output = io.StringIO()
    config = alembic_config()
    config.output_buffer = output

    command.upgrade(config, "head", sql=True)
    command.downgrade(config, "head:base", sql=True)

    sql = output.getvalue()
    for table_name in (
        "payment_requests",
        "request_revisions",
        "documents",
        "flags",
        "approvals",
        "csv_imports",
        "request_status_events",
        "recurring_payment_schedules",
        "recurring_payment_periods",
    ):
        assert f"CREATE TABLE {table_name}" in sql
        assert f"DROP TABLE {table_name}" in sql

    assert "uq_payment_requests_active_fingerprint" in sql
    assert "ix_payment_requests_vendor_amount_issue_date" in sql
    assert "status NOT IN ('Rejected', 'Cancelled', 'Expired')" in sql
    assert "CREATE TRIGGER trg_approvals_immutable" in sql
    assert "CREATE TRIGGER trg_request_revisions_append_only" in sql
    assert "CREATE TRIGGER trg_request_status_events_append_only" in sql
    assert '"from" IS NULL OR "from" IN (' in sql
    assert '"to" IN (' in sql
    assert "fk_exceptions_request_treasury" in sql
    assert "ix_payees_treasury_status" in sql
    assert "uq_treasury_wallets_id_treasury" in sql
    assert "uq_recurring_period_schedule_date" in sql
    assert "ck_recurring_period_outcome" in sql
    assert "'RECURRING'" in sql


async def _verify_invoice_constraints(database_url: str) -> None:
    user_id = "00000000-0000-7000-8000-000000000001"
    org_id = "00000000-0000-7000-8000-000000000010"
    asset_id = "00000000-0000-7000-8000-000000000030"
    treasury_id = "00000000-0000-7000-8000-000000000040"
    fingerprint_treasury_id = "00000000-0000-7000-8000-000000000043"
    vendor_id = "00000000-0000-7000-8000-000000000050"
    payee_id = "00000000-0000-7000-8000-000000000060"
    fingerprint_payee_id = "00000000-0000-7000-8000-000000000062"
    request_id = "00000000-0000-7000-8000-000000000070"
    duplicate_request_id = "00000000-0000-7000-8000-000000000071"
    approval_id = "00000000-0000-7000-8000-000000000080"
    revision_id = "00000000-0000-7000-8000-000000000090"
    event_id = "00000000-0000-7000-8000-000000000091"
    fingerprint = "ab" * 32

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id, email) VALUES "
                    f"('{user_id}', 'invoice-migration@example.com')"
                )
            )
            await connection.execute(
                text(f"INSERT INTO organizations (id, name) VALUES ('{org_id}', 'Invoice test')")
            )
            await connection.execute(
                text(
                    "INSERT INTO chains (chain_id, name, is_testnet, confirmations, "
                    "explorer_url, rpc_urls) VALUES "
                    "(11155111, 'Sepolia', true, 3, 'https://sepolia.etherscan.io', '[\"https://rpc\"]')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
                    f"VALUES ('{asset_id}', 11155111, decode(repeat('11', 20), 'hex'), "
                    "'USDC', 6, 'Circle')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES "
                    f"('{treasury_id}', '{org_id}', 11155111, '{asset_id}')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES "
                    f"('{fingerprint_treasury_id}', '{org_id}', 11155111, '{asset_id}')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES "
                    f"('{vendor_id}', '{org_id}', 'Invoice Vendor', 'invoice-vendor')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO payees "
                    "(id, org_id, treasury_id, vendor_id, label, address, status) VALUES "
                    f"('{payee_id}', '{org_id}', '{treasury_id}', '{vendor_id}', 'Main', "
                    "decode(repeat('22', 20), 'hex'), 'Proposed')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO payees "
                    "(id, treasury_id, org_id, vendor_id, label, address, status) VALUES "
                    f"('{fingerprint_payee_id}', '{fingerprint_treasury_id}', '{org_id}', '{vendor_id}', 'Other', "
                    "decode(repeat('23', 20), 'hex'), 'Proposed')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO payment_requests "
                    "(id, org_id, treasury_id, chain_id, vendor_id, payee_id, invoice_no, issue_date, "
                    "due_at, amount, asset_id, fingerprint) VALUES "
                    f"('{request_id}', '{org_id}', '{treasury_id}', 11155111, '{vendor_id}', '{payee_id}', "
                    f"'INV-001', '2026-10-01', '2026-10-31', 1100, '{asset_id}', "
                    f"decode('{fingerprint}', 'hex'))"
                )
            )
            # The same invoice fingerprint is valid in a different treasury.
            await connection.execute(
                text(
                    "INSERT INTO payment_requests "
                    "(id, org_id, treasury_id, chain_id, vendor_id, payee_id, invoice_no, issue_date, "
                    "due_at, amount, asset_id, fingerprint) VALUES "
                    f"('00000000-0000-7000-8000-000000000075', '{org_id}', '{fingerprint_treasury_id}', "
                    f"11155111, '{vendor_id}', '{fingerprint_payee_id}', 'INV-001', '2026-10-01', "
                    f"'2026-10-31', 1000, '{asset_id}', decode('{fingerprint}', 'hex'))"
                )
            )

        race_barrier = asyncio.Barrier(2)

        async def insert_racing_fingerprint(request_id: str) -> bool:
            await race_barrier.wait()
            try:
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO payment_requests "
                            "(id, org_id, treasury_id, chain_id, vendor_id, payee_id, invoice_no, "
                            "issue_date, due_at, amount, asset_id, fingerprint) VALUES "
                            f"('{request_id}', '{org_id}', '{treasury_id}', 11155111, '{vendor_id}', "
                            f"'{payee_id}', 'INV-RACE', '2026-10-01', '2026-10-31', 1000, "
                            f"'{asset_id}', decode(repeat('cd', 32), 'hex'))"
                        )
                    )
                return True
            except IntegrityError:
                return False

        race_results = await asyncio.gather(
            insert_racing_fingerprint("00000000-0000-7000-8000-000000000076"),
            insert_racing_fingerprint("00000000-0000-7000-8000-000000000077"),
        )
        assert sorted(race_results) == [False, True]

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO payment_requests "
                    "(id, org_id, treasury_id, chain_id, vendor_id, payee_id, invoice_no, "
                    "issue_date, due_at, amount, asset_id, status, fingerprint) VALUES "
                    + ", ".join(
                        f"('00000000-0000-7000-8000-000000000{100 + index}', '{org_id}', "
                        f"'{treasury_id}', 11155111, '{vendor_id}', '{payee_id}', 'PAID-{index}', "
                        f"'2026-01-01', '2026-01-31', {amount}, '{asset_id}', 'Paid', "
                        f"decode('{index:02x}' || repeat('cd', 31), 'hex'))"
                        for index, amount in enumerate((1000, 1020, 980, 1010, 990))
                    )
                )
            )
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO request_revisions (id, request_id, revision, snapshot) "
                    f"VALUES ('00000000-0000-7000-8000-000000000199', '{request_id}', 1, "
                    "'{}'::jsonb)"
                )
            )
        async with AsyncSession(engine) as session:
            row = await session.get(PaymentRequest, uuid.UUID(request_id))
            assert row is not None
            flags = await _recompute_flags(session, row)
            await session.flush()
            assert "AMOUNT_OUTLIER" in {flag["code"] for flag in flags}
            await session.commit()

        with pytest.raises(IntegrityError, match="uq_payment_requests_active_fingerprint"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO payment_requests "
                        "(id, org_id, treasury_id, chain_id, vendor_id, payee_id, invoice_no, issue_date, "
                        "due_at, amount, asset_id, fingerprint) VALUES "
                        f"('{duplicate_request_id}', '{org_id}', '{treasury_id}', 11155111, '{vendor_id}', "
                        f"'{payee_id}', 'INV-002', '2026-10-02', '2026-10-31', 1000, "
                        f"'{asset_id}', decode('{fingerprint}', 'hex'))"
                    )
                )

        async with engine.begin() as connection:
            await connection.execute(
                text(f"UPDATE payment_requests SET status = 'Cancelled' WHERE id = '{request_id}'")
            )
            await connection.execute(
                text(
                    "INSERT INTO payment_requests "
                    "(id, org_id, treasury_id, chain_id, vendor_id, payee_id, invoice_no, issue_date, "
                    "due_at, amount, asset_id, fingerprint) VALUES "
                    f"('{duplicate_request_id}', '{org_id}', '{treasury_id}', 11155111, '{vendor_id}', "
                    f"'{payee_id}', 'INV-002', '2026-10-02', '2026-10-31', 1000, "
                    f"'{asset_id}', decode('{fingerprint}', 'hex'))"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO request_revisions (id, request_id, revision, snapshot) "
                    f"VALUES ('{revision_id}', '{duplicate_request_id}', 1, '{{}}'::jsonb)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO approvals "
                    "(id, request_id, revision, approver_address, typed_data, signature, expires_at) "
                    "VALUES "
                    f"('{approval_id}', '{duplicate_request_id}', 1, decode(repeat('33', 20), 'hex'), "
                    "'{}'::jsonb, decode('01', 'hex'), '2027-01-01T00:00:00Z')"
                )
            )
            await connection.execute(
                text(f"UPDATE approvals SET status = 'Invalidated' WHERE id = '{approval_id}'")
            )
            await connection.execute(
                text(
                    'INSERT INTO request_status_events (id, request_id, "to", actor_type) '
                    f"VALUES ('{event_id}', '{duplicate_request_id}', 'Draft', 'SYSTEM')"
                )
            )

        with pytest.raises(DBAPIError, match="approvals are immutable"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        f"UPDATE approvals SET signature = decode('02', 'hex') WHERE id = '{approval_id}'"
                    )
                )

        with pytest.raises(DBAPIError, match="approval status cannot change"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(f"UPDATE approvals SET status = 'Valid' WHERE id = '{approval_id}'")
                )

        # An ended approval frees the slot: the same approver can sign the revision again,
        # but not twice while the first is Valid.
        resign_sql = (
            "INSERT INTO approvals "
            "(id, request_id, revision, approver_address, typed_data, signature, expires_at) "
            f"VALUES ('{{id}}', '{duplicate_request_id}', 1, decode(repeat('33', 20), 'hex'), "
            "'{{}}'::jsonb, decode('01', 'hex'), '2027-01-01T00:00:00Z')"
        )
        async with engine.begin() as connection:
            await connection.execute(
                text(resign_sql.format(id="00000000-0000-7000-8000-000000000081"))
            )
        with pytest.raises(IntegrityError, match="uq_approvals_valid_request_revision_address"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(resign_sql.format(id="00000000-0000-7000-8000-000000000082"))
                )
        with pytest.raises(IntegrityError, match="fk_approvals_request_revision"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        resign_sql.format(id="00000000-0000-7000-8000-000000000083").replace(
                            ", 1, decode(repeat('33'", ", 2, decode(repeat('33'"
                        )
                    )
                )

        # A paying wallet must belong to the request's own treasury.
        other_treasury_id = "00000000-0000-7000-8000-000000000041"
        other_wallet_id = "00000000-0000-7000-8000-000000000042"
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES "
                    f"('{other_treasury_id}', '{org_id}', 11155111, '{asset_id}')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO treasury_wallets "
                    "(id, org_id, treasury_id, chain_id, role, label, safe_address, owners, "
                    "threshold) VALUES "
                    f"('{other_wallet_id}', '{org_id}', '{other_treasury_id}', 11155111, "
                    "'SOURCE', 'Other', decode(repeat('55', 20), 'hex'), "
                    "'[\"0x01\"]'::jsonb, 1)"
                )
            )
        with pytest.raises(IntegrityError, match="fk_payment_requests_paying_wallet_treasury"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        f"UPDATE payment_requests SET paying_wallet_id = '{other_wallet_id}' "
                        f"WHERE id = '{duplicate_request_id}'"
                    )
                )

        # Row-level checks: dates, fingerprint once past Draft, no-op status events.
        for statement, constraint in (
            (
                "UPDATE payment_requests SET due_at = '2026-09-01' "
                f"WHERE id = '{duplicate_request_id}'",
                "ck_payment_requests_due_after_issue",
            ),
            (
                "UPDATE payment_requests SET fingerprint = NULL, status = 'Approved' "
                f"WHERE id = '{duplicate_request_id}'",
                "ck_payment_requests_fingerprint_set",
            ),
            (
                'INSERT INTO request_status_events (id, request_id, "from", "to", actor_type) '
                f"VALUES ('00000000-0000-7000-8000-000000000092', '{duplicate_request_id}', "
                "'Draft', 'Draft', 'SYSTEM')",
                "ck_request_status_events_changed",
            ),
        ):
            with pytest.raises(IntegrityError, match=constraint):
                async with engine.begin() as connection:
                    await connection.execute(text(statement))

        # Tenant and chain isolation: another org's vendor, a vendor other than the
        # payee's, and an asset on another chain are all rejected.
        other_org_id = "00000000-0000-7000-8000-000000000011"
        foreign_vendor_id = "00000000-0000-7000-8000-000000000051"
        other_vendor_id = "00000000-0000-7000-8000-000000000052"
        mainnet_asset_id = "00000000-0000-7000-8000-000000000031"
        async with engine.begin() as connection:
            await connection.execute(
                text(f"INSERT INTO organizations (id, name) VALUES ('{other_org_id}', 'Other')")
            )
            await connection.execute(
                text(
                    "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES "
                    f"('{foreign_vendor_id}', '{other_org_id}', 'Foreign', 'foreign'), "
                    f"('{other_vendor_id}', '{org_id}', 'Other', 'other')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO chains (chain_id, name, is_testnet, confirmations, "
                    "explorer_url, rpc_urls) VALUES "
                    "(1, 'Ethereum', false, 12, 'https://etherscan.io', '[\"https://rpc\"]')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
                    f"VALUES ('{mainnet_asset_id}', 1, decode(repeat('11', 20), 'hex'), "
                    "'USDC', 6, 'Circle')"
                )
            )

        def request_insert(vendor: str, asset: str) -> str:
            return (
                "INSERT INTO payment_requests "
                "(id, org_id, treasury_id, chain_id, vendor_id, payee_id, invoice_no, "
                "issue_date, due_at, amount, asset_id) VALUES "
                f"('00000000-0000-7000-8000-000000000072', '{org_id}', '{treasury_id}', "
                f"11155111, '{vendor}', '{payee_id}', 'INV-003', '2026-10-02', '2026-10-31', "
                f"1000, '{asset}')"
            )

        for vendor, asset, constraint in (
            # Either composite FK may report this one first; both reject it.
            (
                foreign_vendor_id,
                asset_id,
                "fk_payment_requests_(vendor_org|payee_treasury_vendor)",
            ),
            (other_vendor_id, asset_id, "fk_payment_requests_payee_treasury_vendor"),
            (vendor_id, mainnet_asset_id, "fk_payment_requests_asset_chain"),
        ):
            with pytest.raises(IntegrityError, match=constraint):
                async with engine.begin() as connection:
                    await connection.execute(text(request_insert(vendor, asset)))

        with pytest.raises(DBAPIError, match="request_revisions are append-only"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        f"UPDATE request_revisions SET reason = 'changed' WHERE id = '{revision_id}'"
                    )
                )

        with pytest.raises(DBAPIError, match="request_status_events are append-only"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(f"DELETE FROM request_status_events WHERE id = '{event_id}'")
                )

        with pytest.raises(IntegrityError, match="fk_exceptions_request_treasury"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO exceptions "
                        "(id, org_id, treasury_id, request_id, mandate_onchain_version, amount, "
                        "payee, expiry, status) "
                        f"VALUES ('00000000-0000-7000-8000-000000000099', '{org_id}', "
                        f"'{treasury_id}', '00000000-0000-7000-8000-000000000098', 1, 1000, "
                        "decode(repeat('44', 20), 'hex'), '2027-01-01T00:00:00Z', 'Requested')"
                    )
                )
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL invoice migration cycle",
)
def test_invoice_migration_round_trip_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = alembic_config(database_url=database_url)

    command.upgrade(config, "head")
    try:
        command.check(config)
        asyncio.run(_verify_invoice_constraints(database_url))
    finally:
        command.downgrade(config, "base")
