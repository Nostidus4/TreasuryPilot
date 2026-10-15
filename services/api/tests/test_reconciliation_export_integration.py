"""Reconciliation export against PostgreSQL (REC-004): seeded rows, built lines, HTTP route."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import SessionAccess, UserRecord
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.main import create_app
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.reconcile.build import build_reconciliation

pytestmark = pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

API_ROOT = Path(__file__).parents[1]
CHAIN = 31337
FEE = 21_000 * 10**9
USDC = bytes.fromhex("11" * 20)
UNKNOWN = bytes.fromhex("dd" * 20)
ORG_A, ORG_B = uuid.uuid4(), uuid.uuid4()
T_A, T_B = uuid.uuid4(), uuid.uuid4()
ASSET, NATIVE = uuid.uuid4(), uuid.uuid4()
EXPORT = f"/v1/orgs/{ORG_A}/reconciliation/export"


async def _org(pool: Any, org: uuid.UUID, treasury: uuid.UUID, name: str) -> tuple[uuid.UUID, ...]:
    vendor, payee = uuid.uuid4(), uuid.uuid4()
    await pool.execute("INSERT INTO organizations (id, name) VALUES ($1, $2)", org, name)
    await pool.execute(
        "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES ($1, $2, $3, $4)",
        treasury,
        org,
        CHAIN,
        ASSET,
    )
    await pool.execute(
        "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES ($1, $2, $3, $4)",
        vendor,
        org,
        name + " Vendor",
        name.lower(),
    )
    await pool.execute(
        "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) "
        "VALUES ($1, $2, $3, $4, 'Main', $5, 'Proposed')",
        payee,
        treasury,
        org,
        vendor,
        b"\x22" * 20,
    )
    return vendor, payee


async def _request(
    pool: Any,
    org: uuid.UUID,
    treasury: uuid.UUID,
    ids: tuple[uuid.UUID, ...],
    invoice: str,
    ops: list[tuple[str, int, bytes]],
    confirmed: str,
) -> uuid.UUID:
    request, attestation = uuid.uuid4(), uuid.uuid4()
    when = datetime.fromisoformat(confirmed).replace(tzinfo=UTC)
    await pool.execute(
        "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id, "
        "invoice_no, issue_date, due_at, amount, asset_id, status, fingerprint) VALUES "
        "($1, $2, $3, $4, $5, $6, $7, '2026-10-01', '2026-10-31', 1000, $8, 'Paid', $9)",
        request, org, treasury, CHAIN, ids[0], ids[1], invoice, ASSET, request.bytes * 2,
    )  # fmt: skip
    await pool.execute(
        "INSERT INTO attestations (id, plan_id, request_id, plan_hash, step_ids, policy_version, "
        "executor, nonce, valid_until, evidence_digest, typed_data, signature, policy_signer) "
        "VALUES ($1, $2, $3, $4, $5, $4, '0x', $6, now(), $4, '{}', $4, '0x')",
        attestation, uuid.uuid4(), request.bytes * 2, attestation.bytes * 2, [], attestation.int,
    )  # fmt: skip
    for seq, (kind, amount, asset) in enumerate(ops):
        step_id, step_row, op, tx = (uuid.uuid4() for _ in range(4))
        await pool.execute(
            "INSERT INTO plan_steps (id, attestation_id, plan_id, seq, step_id, action, "
            "request_id, treasury_address, chain_id, from_address, to_address, asset_address, "
            "amount) VALUES ($1, $2, $3, $4, $5, 1, $6, $7, $8, $9, $10, $11, $12)",
            step_row, attestation, uuid.uuid4(), seq, step_id.bytes * 2, request.bytes * 2,
            b"\x0a" * 20, CHAIN, b"\x0b" * 20, b"\x0c" * 20, asset, amount,
        )  # fmt: skip
        await pool.execute(
            "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, kind, "
            "payload, idempotency_key, status) VALUES ($1, $2, $3, $4, $5, $6::operation_kind, "
            "'{}', $7, 'Confirmed')",
            op, treasury, step_row, request, step_id.bytes * 2, kind, "rec:" + op.hex,
        )  # fmt: skip
        await pool.execute(
            "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, from_address, "
            "status, block_number, fee_wei, confirmed_at) VALUES ($1, $2, $3, $4, $5, $6, "
            "'Confirmed', 100, $7, $8)",
            tx, op, CHAIN, tx.bytes * 2, seq, b"\xee" * 20, FEE, when,
        )  # fmt: skip
        await pool.execute(
            "INSERT INTO gas_ledger (id, treasury_id, transaction_id, payer, payer_address, "
            "fee_wei, reverted, day) VALUES (gen_random_uuid(), $1, $2, 'EXECUTOR', $3, $4, "
            "false, $5)",
            treasury, tx, b"\xee" * 20, FEE, when.date(),
        )  # fmt: skip
    async with pool.acquire() as connection:
        await build_reconciliation(connection, request)
    return request


async def _seed(url: str) -> None:
    pool = await create_worker_pool(url.replace("+asyncpg", ""), min_size=1, max_size=1)
    try:
        await pool.execute(
            "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, "
            "rpc_urls) VALUES ($1, 'Anvil', true, 3, 'https://explorer.invalid', '[\"http://rpc\"]')",
            CHAIN,
        )
        await pool.execute(
            "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
            "VALUES ($1, $2, $3, 'USDC', 6, 'Circle')",
            ASSET, CHAIN, USDC,
        )  # fmt: skip
        await pool.execute(
            "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label, "
            "is_native) VALUES ($1, $2, NULL, 'ETH', 18, 'Native', true)",
            NATIVE, CHAIN,
        )  # fmt: skip
        a, b = await _org(pool, ORG_A, T_A, "Acme"), await _org(pool, ORG_B, T_B, "Beta")
        r1 = await _request(
            pool, ORG_A, T_A, a, "INV-A1", [("PAY", 600, USDC), ("REFILL", 700, USDC)],
            "2026-10-02 23:59:00",
        )  # fmt: skip
        await _request(pool, ORG_A, T_A, a, "=INV-A2", [("PAY", 50, USDC)], "2026-10-01 00:00:00")
        await _request(pool, ORG_A, T_A, a, "INV-A3", [("PAY", 99, USDC)], "2026-10-03 00:00:00")
        await _request(pool, ORG_B, T_B, b, "INV-B1", [("PAY", 777, USDC)], "2026-10-02 12:00:00")
        await _request(pool, ORG_A, T_A, a, "INV-A4", [("PAY", 5, UNKNOWN)], "2026-11-05 10:00:00")
        await _request(
            pool, ORG_A, T_A, a, "INV-S1", [("SUPPLY", 100, USDC)], "2026-09-15 10:00:00"
        )
        for stamp, balance in (("2026-08-31 12:00:00", 1000), ("2026-09-30 12:00:00", 1250)):
            await pool.execute(
                "INSERT INTO snapshots (id, org_id, treasury_id, purpose, block_number, "
                "block_hash, block_timestamp, provider, data, coverage, missing) VALUES "
                "(gen_random_uuid(), $1, $2, 'DASHBOARD', 1, $3, $4, 'p', $5::jsonb, 'COMPLETE', "
                "'[]')",
                ORG_A, T_A, b"\x01" * 32, datetime.fromisoformat(stamp).replace(tzinfo=UTC),
                json.dumps({"aave": {"a_token_balance": str(balance)}}),
            )  # fmt: skip
        await pool.execute(
            "UPDATE reconciliations SET status = 'Matched', matched_by = 'USER' "
            "WHERE request_id = $1",
            r1,
        )
    finally:
        await pool.close()


@pytest.fixture(scope="module")
def url() -> Iterator[str]:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed(database_url))
        yield database_url
    finally:
        command.downgrade(config, "base")


def _client(url: str, role: str) -> TestClient:
    app = create_app(settings=Settings(environment="local"))
    engine = create_async_engine(url, poolclass=NullPool)  # one loop per request
    app.state.request_sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def member(organization_id: uuid.UUID) -> MemberAccess:
        access = SessionAccess(
            user=UserRecord(uuid.uuid4(), "u@example.test", None, "active"),
            session_id=uuid.uuid4(),
            step_up_at=datetime.now(UTC),
        )
        return MemberAccess(access=access, organization_id=organization_id, roles=frozenset({role}))

    app.dependency_overrides[require_member] = member
    return TestClient(app)


def _get(url: str, start: str, end: str, fmt: str = "csv", role: str = "Finance") -> Any:
    return _client(url, role).get(EXPORT, params={"from": start, "to": end, "format": fmt})


def _rows(response: Any) -> list[list[str]]:
    return list(csv.reader(io.StringIO(response.text)))[1:]


def test_csv_columns_boundaries_unmatched_and_isolation(url: str) -> None:
    response = _get(url, "2026-10-01", "2026-10-02")
    assert response.status_code == 200
    assert "reconciliation-2026-10-01-2026-10-02-csv.csv" in response.headers["content-disposition"]
    rows = _rows(response)
    assert len(rows) == 6  # r1: PAY, REFILL, 2 fees; r2: PAY, 1 fee. r3 (10-03) and org B absent.
    assert not any(r[5] == "777" or r[3] == "INV-B1" or r[3] == "INV-A3" for r in rows)
    pay = next(r for r in rows if r[4] == "EXTERNAL_EXPENSE" and r[3] == "INV-A1")
    assert pay[0] == "2026-10-02"  # the 23:59 UTC edge is inside the period
    assert (pay[2], pay[5], pay[6], pay[8], pay[9], pay[10]) == (
        "Acme Vendor", "0.000600", "USDC", "0.000021000000000000", "Matched", "USER",
    )  # fmt: skip
    assert pay[1] and pay[7].startswith("0x")
    unmatched = next(r for r in rows if r[4] == "EXTERNAL_EXPENSE" and r[3] == "'=INV-A2")
    assert (unmatched[9], unmatched[10]) == ("Pending", "")
    fees = [r for r in rows if r[4] == "FEE"]
    assert len(fees) == 3 and all(r[8] == "" and r[5] == "0.000021000000000000" for r in fees)


def test_period_boundaries_are_inclusive_on_both_ends(url: str) -> None:
    assert len(_rows(_get(url, "2026-10-02", "2026-10-02"))) == 4  # r1 only (23:59 edge)
    assert len(_rows(_get(url, "2026-10-01", "2026-10-01"))) == 2  # r2 at 00:00 UTC
    assert len(_rows(_get(url, "2026-10-03", "2026-10-03"))) == 2  # r3 only


def test_journal_balances(url: str) -> None:
    rows = _rows(_get(url, "2026-10-01", "2026-10-02", "journal"))
    assert len(rows) == 12
    assert sum(int(r[5].replace(".", "")) for r in rows) == sum(
        int(r[6].replace(".", "")) for r in rows
    )


def test_roles(url: str) -> None:
    assert _get(url, "2026-10-01", "2026-10-02", role="OrgAdmin").status_code == 200
    for role in ("Operator", "Owner"):
        assert _get(url, "2026-10-01", "2026-10-02", role=role).status_code == 403


def test_invalid_and_too_long_periods(url: str) -> None:
    assert _get(url, "2026-10-02", "2026-10-01").status_code == 422
    assert _get(url, "2025-09-30", "2026-10-01").status_code == 422  # 367 days inclusive
    assert _get(url, "2025-10-01", "2026-10-01").status_code == 200  # 366 days inclusive


def test_totals_mismatch_returns_409_with_differences(url: str) -> None:
    async def bump(delta: int) -> None:
        pool = await create_worker_pool(url.replace("+asyncpg", ""), min_size=1, max_size=1)
        try:
            await pool.execute(
                "UPDATE reconciliation_lines SET amount = amount + $1 "
                "WHERE classification = 'EXTERNAL_EXPENSE' AND amount IN (50, 51)",
                delta,
            )
        finally:
            await pool.close()

    asyncio.run(bump(1))
    try:
        response = _get(url, "2026-10-01", "2026-10-02")
        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "EXPORT_TOTALS_MISMATCH"
        assert body["differences"] == [
            {"class": "EXTERNAL_EXPENSE", "asset": "USDC", "expected": "650", "exported": "651"}
        ]
    finally:
        asyncio.run(bump(-1))
    assert _get(url, "2026-10-01", "2026-10-02").status_code == 200


def test_unknown_erc20_is_a_distinct_error(url: str) -> None:
    response = _get(url, "2026-11-01", "2026-11-30")
    assert response.status_code == 409 and response.json()["code"] == "EXPORT_ASSET_UNKNOWN"


def test_supply_interest_is_aToken_growth_minus_net_supplied(url: str) -> None:
    rows = _rows(_get(url, "2026-09-01", "2026-09-30"))
    interest = [r for r in rows if r[4] == "SUPPLY_INTEREST"]
    assert [(r[0], r[5], r[6], r[9]) for r in interest] == [
        ("2026-09-30", "0.000150", "USDC", "Computed")
    ]
    assert any(r[4] == "LENDING_TRANSFER" and r[5] == "0.000100" for r in rows)
    journal = _rows(_get(url, "2026-09-01", "2026-09-30", "journal"))
    legs = [(r[3], r[5], r[6]) for r in journal if r[2] == "SUPPLY_INTEREST"]
    assert legs == [("1300", "0.000150", "0"), ("4100", "0", "0.000150")]
    assert not any(r[4] == "SUPPLY_INTEREST" for r in _rows(_get(url, "2026-10-01", "2026-10-02")))


def test_org_account_mappings_override_journal_and_are_scoped(url: str) -> None:
    client = _client(url, "Finance")
    mappings = f"/v1/orgs/{ORG_A}/reconciliation/account-mappings"
    body = {"items": [{"classification": "EXTERNAL_EXPENSE", "side": "DEBIT",
                       "accountCode": "=7000", "accountName": "Vendor costs"}]}  # fmt: skip
    put = client.put(mappings, json=body)
    assert put.status_code == 200
    by_slot = {(i["classification"], i["side"]): i for i in put.json()["items"]}
    assert by_slot[("EXTERNAL_EXPENSE", "DEBIT")]["source"] == "ORG"
    assert by_slot[("EXTERNAL_EXPENSE", "CREDIT")]["source"] == "DEFAULT"
    journal = _rows(_get(url, "2026-10-01", "2026-10-02", "journal"))
    pay = [r for r in journal if r[2] == "EXTERNAL_EXPENSE"]
    assert {r[3] for r in pay} == {"'=7000", "1110"}  # overridden debit, default credit
    assert (
        client.put(
            mappings, json={"items": [{**body["items"][0], "classification": "NOPE"}]}
        ).status_code
        == 422
    )
    assert _client(url, "Owner").get(mappings).status_code == 403
    assert client.put(mappings, json={"items": []}).status_code == 200  # reset to defaults
    assert client.get(mappings).json()["items"][0]["source"] == "DEFAULT"
