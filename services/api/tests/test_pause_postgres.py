"""Pause, cancel and resume routes against PostgreSQL (#125)."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import SessionAccess, UserRecord
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.main import create_app
from treasurypilot_api.mandate import pause

API_ROOT = Path(__file__).parents[1]
ORG = uuid.UUID("00000000-0000-7000-8000-000000000a10")
USER = uuid.UUID("00000000-0000-7000-8000-000000000a11")
ASSET = uuid.UUID("00000000-0000-7000-8000-000000000a12")
VENDOR = uuid.UUID("00000000-0000-7000-8000-000000000a13")
PAYEE = uuid.UUID("00000000-0000-7000-8000-000000000a14")
REQUEST = uuid.UUID("00000000-0000-7000-8000-000000000a15")
MODULE = bytes.fromhex("aa" * 20)
TREASURIES = [uuid.UUID(f"00000000-0000-7000-8000-000000000b{i:02d}") for i in range(6)]


class _Governance:
    async def create(self, **_: Any) -> dict[str, Any]:
        return {"governanceTx": {"id": str(uuid.uuid4())}}


@pytest.fixture(scope="module")
def url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for the pause integration tests")
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


async def _sql(url: str, query: str, **params: Any) -> list[Any]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(query), params)
            return list(result.all()) if result.returns_rows else []
    finally:
        await engine.dispose()


async def _seed(url: str) -> None:
    await _sql(url, "INSERT INTO users (id, email) VALUES (:id, 'pause@example.test')", id=USER)
    await _sql(url, "INSERT INTO organizations (id, name) VALUES (:id, 'Acme')", id=ORG)
    await _sql(
        url,
        "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
        "VALUES (31337, 'Anvil', true, 3, 'https://explorer.invalid', '[\"http://rpc\"]')",
    )
    await _sql(
        url,
        "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
        "VALUES (:id, 31337, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
        id=ASSET,
    )
    for treasury in TREASURIES:
        await _sql(
            url,
            "INSERT INTO treasuries (id, org_id, chain_id, asset_id, module_address) "
            "VALUES (:id, :org, 31337, :asset, :module)",
            id=treasury,
            org=ORG,
            asset=ASSET,
            module=MODULE,
        )
    await _sql(
        url,
        "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES (:id, :org, 'V', 'v')",
        id=VENDOR,
        org=ORG,
    )
    await _sql(
        url,
        "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) VALUES "
        "(:id, :t, :org, :vendor, 'Main', decode(repeat('22', 20), 'hex'), 'Proposed')",
        id=PAYEE,
        t=TREASURIES[0],
        org=ORG,
        vendor=VENDOR,
    )
    await _sql(
        url,
        "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id, "
        "invoice_no, issue_date, due_at, amount, asset_id) VALUES (:id, :org, :t, 31337, "
        ":vendor, :payee, 'P-1', '2026-10-01', '2026-10-31', 1000, :asset)",
        id=REQUEST,
        org=ORG,
        t=TREASURIES[0],
        vendor=VENDOR,
        payee=PAYEE,
        asset=ASSET,
    )
    await _sql(
        url,
        "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, kind, "
        "payload, idempotency_key, status) VALUES (gen_random_uuid(), :t, gen_random_uuid(), "
        ":request, decode(repeat('33', 32), 'hex'), 'PAY', '{}'::jsonb, 'pause-op', 'Pending')",
        t=TREASURIES[0],
        request=REQUEST,
    )


def _client(url: str, monkeypatch: pytest.MonkeyPatch, role: str = "Owner") -> TestClient:
    async def sentinel(*_: object) -> dict[str, Any]:
        return {"txHash": "0x" + "ab" * 32, "alreadyPaused": False}

    monkeypatch.setattr(pause, "_call_sentinel", sentinel)
    app = create_app(settings=Settings(environment="local"))
    engine = create_async_engine(url, poolclass=NullPool)  # one loop per request
    app.state.request_sessions = async_sessionmaker(engine, expire_on_commit=False)
    app.state.governance_service = _Governance()

    async def member(organization_id: uuid.UUID) -> MemberAccess:
        access = SessionAccess(
            user=UserRecord(USER, "u@example.test", None, "active"),
            session_id=uuid.uuid4(),
            step_up_at=datetime.now(UTC),
        )
        return MemberAccess(access=access, organization_id=organization_id, roles=frozenset({role}))

    app.dependency_overrides[require_member] = member
    return TestClient(app)


def _base(treasury: uuid.UUID) -> str:
    return f"/v1/orgs/{ORG}/treasuries/{treasury}"


def _row(url: str, treasury: uuid.UUID) -> list[Any]:
    return asyncio.run(
        _sql(
            url,
            "SELECT paused, reason, onchain_status::text, version FROM backend_pause "
            "WHERE treasury_id = :t",
            t=treasury,
        )
    )


def test_pause_creates_the_row_and_status_lists_pending_transactions(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, treasury = _client(url, monkeypatch), TREASURIES[0]
    response = client.post(f"{_base(treasury)}/pause", json={"reason": "incident"})
    assert response.status_code == 202 and response.json()["onchain"] == "SENTINEL_SUBMITTED"
    assert _row(url, treasury)[0][:3] == (True, "incident", "Requested")
    status = client.get(f"{_base(treasury)}/pause").json()
    assert status["backendPaused"] is True and status["effective"] is False
    assert [p["status"] for p in status["pendingTransactions"]] == ["Pending"]


def test_pausing_an_already_paused_treasury_keeps_the_first_reason(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, treasury = _client(url, monkeypatch), TREASURIES[1]
    assert client.post(f"{_base(treasury)}/pause", json={"reason": "first"}).status_code == 202
    assert client.post(f"{_base(treasury)}/pause", json={"reason": "second"}).status_code == 202
    rows = _row(url, treasury)
    assert len(rows) == 1 and rows[0][:2] == (True, "first") and rows[0][3] == 2


def test_concurrent_first_pauses_do_not_fail(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    clients, treasury = [_client(url, monkeypatch) for _ in range(4)], TREASURIES[2]
    with ThreadPoolExecutor(4) as pool:
        codes = list(
            pool.map(
                lambda c: c.post(f"{_base(treasury)}/pause", json={"reason": "race"}).status_code,
                clients,
            )
        )
    assert codes == [202] * 4 and len(_row(url, treasury)) == 1


def test_cancel_lifts_a_backend_only_pause_but_not_an_effective_one(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, treasury = _client(url, monkeypatch), TREASURIES[3]
    assert client.post(f"{_base(treasury)}/pause/cancel").status_code == 409  # nothing to cancel
    client.post(f"{_base(treasury)}/pause", json={"reason": "oops"})
    assert client.post(f"{_base(treasury)}/pause/cancel").status_code == 200
    assert _row(url, treasury)[0][:3] == (False, "oops", "NotRequested")
    client.post(f"{_base(treasury)}/pause", json={"reason": "real"})
    asyncio.run(
        _sql(
            url,
            "UPDATE backend_pause SET onchain_status = 'Effective' WHERE treasury_id = :t",
            t=treasury,
        )
    )
    assert client.post(f"{_base(treasury)}/pause/cancel").status_code == 409
    assert _row(url, treasury)[0][0] is True


def test_resume_on_a_revoked_treasury_is_refused(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    client, treasury = _client(url, monkeypatch), TREASURIES[4]
    client.post(f"{_base(treasury)}/pause", json={"reason": "r"})
    asyncio.run(
        _sql(
            url,
            "UPDATE backend_pause SET onchain_status = 'Effective' WHERE treasury_id = :t",
            t=treasury,
        )
    )
    asyncio.run(_sql(url, "UPDATE treasuries SET status = 'Revoked' WHERE id = :t", t=treasury))
    response = client.post(f"{_base(treasury)}/resume-tx")
    assert response.status_code == 409 and response.json()["code"] == "TREASURY_REVOKED"
