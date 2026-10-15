"""Dashboard treasury state (TRS-009): GET /orgs/{o}/treasuries/{t} against PostgreSQL."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import text

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.api import problem_response
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.treasury.api import router
from treasurypilot_api.treasury.service import TreasuryService
from treasurypilot_api.treasury.sync import asset_id

API_ROOT = Path(__file__).parents[1]
CHAIN = 31337
TOKEN = "0x" + "11" * 20
ORG, USER, TREASURY, VENDOR, PAYEE = (uuid.uuid4() for _ in range(5))
ASSET = asset_id(CHAIN, TOKEN)
ADDRESS = {"T": "0x" + "aa" * 20, "O1": "0x" + "bb" * 20, "O2": "0x" + "cc" * 20}
MODULE = "0x" + "99" * 20
TODAY = int(datetime.now(UTC).timestamp()) // 86_400
PATH = f"/v1/orgs/{ORG}/treasuries/{TREASURY}"


def _chain_data() -> dict[str, Any]:
    return {
        "balances": {ADDRESS["T"]: "50000", ADDRESS["O1"]: "1000", ADDRESS["O2"]: "500"},
        "buffers": {ADDRESS["T"]: "5000", ADDRESS["O1"]: "500", ADDRESS["O2"]: "100"},
        "targets": {ADDRESS["T"]: "0", ADDRESS["O1"]: "1500", ADDRESS["O2"]: "300"},
        "module": {
            "mandate": {
                "pay": {"per_request": "2000", "daily": "10000"},
                "refill": {"per_request": "3000", "daily": "6000"},
                "supply": {"per_request": "9000", "daily": "20000"},
            },
            "used_today": {"PAY": "1200", "REFILL": "0", "SUPPLY": "0"},
        },
        "aave": {
            "a_token_balance": "20000",
            "available_liquidity": "15000",
            "reserve": {"liquidity_rate": str(4 * 10**25), "variable_borrow_rate": "0"},
        },
    }


def _config(url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


async def _sql(url: str, sql: str, **params: object) -> None:
    engine, _ = create_session_factory(url)
    try:
        async with engine.begin() as c:
            await c.execute(text("SET LOCAL session_replication_role = replica"))
            await c.execute(text(sql), params)
    finally:
        await engine.dispose()


async def _seed(url: str) -> None:
    mandate = {"minSupply": "100", "reserveHorizonDays": 30}
    engine, _ = create_session_factory(url)
    try:
        async with engine.begin() as c:
            await c.execute(text("SET LOCAL session_replication_role = replica"))

            async def run(sql: str, **p: object) -> None:
                await c.execute(text(sql), p)

            await run("INSERT INTO organizations (id, name) VALUES (:o, 'st')", o=ORG)
            await run("INSERT INTO users (id, email) VALUES (:u, 'st@example.test')", u=USER)
            await run(
                "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, "
                "rpc_urls) VALUES (31337, 'Anvil', true, 3, 'https://e.invalid', '[\"http://r\"]')"
            )
            await run(
                "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
                "VALUES (:a, 31337, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
                a=ASSET,
            )
            await run(
                "INSERT INTO treasuries (id, org_id, chain_id, asset_id, status, coverage, "
                "module_address) VALUES (:t, :o, 31337, :a, 'Ready', 'COMPLETE', "
                "decode(repeat('99', 20), 'hex'))",
                t=TREASURY,
                o=ORG,
                a=ASSET,
            )
            for label, address in ADDRESS.items():
                await run(
                    "INSERT INTO treasury_wallets (id, org_id, treasury_id, chain_id, role, "
                    "label, safe_address, owners, threshold) VALUES (gen_random_uuid(), :o, :t, "
                    "31337, CAST(:role AS treasury_wallet_role), :label, "
                    "decode(substr(:addr, 3), 'hex'), '[\"0x1\"]'::jsonb, 1)",
                    o=ORG,
                    t=TREASURY,
                    role="SOURCE" if label == "T" else "OPERATIONAL",
                    label=label,
                    addr=address,
                )
            await run(
                "INSERT INTO vendors (id, org_id, name, normalized_ref, version) "
                "VALUES (:v, :o, 'Acme', 'acme', 1)",
                v=VENDOR,
                o=ORG,
            )
            await run(
                "INSERT INTO payees (id, org_id, treasury_id, vendor_id, label, address, status, "
                "active_from, oob_verified_by, oob_verified_at, oob_method, oob_note, version) "
                "VALUES (:p, :o, :t, :v, 'Acme', decode(repeat('44', 20), 'hex'), 'Active', "
                "now() - interval '30 days', :u, now(), 'PHONE', 'ok', 1)",
                p=PAYEE,
                o=ORG,
                t=TREASURY,
                v=VENDOR,
                u=USER,
            )
            # Reserve: the Approved 800 (due in 1 day) counts; the one due in 90 days is past the
            # 30-day horizon; the AwaitingApproval one is not an approved obligation.
            for status, amount, due in (
                ("Approved", 800, 1),
                ("Scheduled", 700, 90),
                ("AwaitingApproval", 300, 2),
                ("AwaitingApproval", 400, 2),
            ):
                await run(
                    "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, "
                    "payee_id, invoice_no, issue_date, due_at, amount, asset_id, status, terms, "
                    "terms_confirmed_by, terms_confirmed_at, fingerprint, onchain_request_id, "
                    "paying_wallet_id) "
                    "VALUES (gen_random_uuid(), :o, :t, 31337, :v, :p, :n, current_date, "
                    "current_date + 3, :amt, :a, :s, CAST(:terms AS jsonb), :u, now(), :fp, :oid, "
                    "(SELECT id FROM treasury_wallets WHERE label = 'O1'))",
                    o=ORG,
                    t=TREASURY,
                    v=VENDOR,
                    p=PAYEE,
                    n=f"INV-{status}-{amount}",
                    fp=hashlib.sha256(f"{status}{amount}".encode()).digest(),
                    amt=amount,
                    a=ASSET,
                    s=status,
                    terms=json.dumps({"net_due_day": TODAY + due}),
                    u=USER,
                    oid=hashlib.sha256(f"id{status}{amount}".encode()).digest(),
                )
            await run(
                "INSERT INTO mandate_versions (id, org_id, treasury_id, version, onchain_version, "
                "status, config, config_hash, valid_from, expires_at, created_by, activated_at) "
                "VALUES (gen_random_uuid(), :o, :t, 1, 1, 'Active', CAST(:cfg AS jsonb), "
                "decode(repeat('22', 32), 'hex'), now() - interval '1 day', "
                "now() + interval '30 days', :u, now())",
                o=ORG,
                t=TREASURY,
                u=USER,
                cfg=json.dumps(mandate),
            )
            # Queues: 1 governance (Collecting) + 1 Submitted (not counted), review items for
            # Owner and for Finance, 1 reconciliation Pending + 1 Matched (not counted).
            for status in ("Collecting", "Submitted"):
                await run(
                    "INSERT INTO governance_txs (id, org_id, treasury_id, chain_id, safe_address, "
                    'purpose, calls, "to", value, data, operation, safe_nonce, safe_tx_hash, '
                    "threshold, owners_snapshot, status) VALUES (gen_random_uuid(), :o, :t, "
                    "31337, decode(repeat('aa', 20), 'hex'), 'MANDATE', '[]'::jsonb, "
                    "decode(repeat('aa', 20), 'hex'), 0, decode('00', 'hex'), 0, :n, :h, 1, "
                    "ARRAY[decode('aa', 'hex')], CAST(:s AS governance_tx_status))",
                    o=ORG,
                    t=TREASURY,
                    n=1 if status == "Collecting" else 2,
                    h=hashlib.sha256(status.encode()).digest(),
                    s=status,
                )
            for roles in (["Owner"], ["Finance"]):
                await run(
                    "INSERT INTO review_items (id, org_id, treasury_id, request_id, request_version, "
                    "type, primary_code, reason_codes, completed_steps, assigned_roles, "
                    "sla_due_at) VALUES "
                    "(gen_random_uuid(), :o, :t, gen_random_uuid(), 1, 'POLICY_BLOCK', 'X', ARRAY['X'], '[]'::jsonb, "
                    ":r, now() + interval '1 day')",
                    o=ORG,
                    t=TREASURY,
                    r=roles,
                )
            for status in ("Pending", "Matched"):
                await run(
                    "INSERT INTO reconciliations (id, org_id, treasury_id, request_id, status) "
                    "VALUES (gen_random_uuid(), :o, :t, gen_random_uuid(), :s)",
                    o=ORG,
                    t=TREASURY,
                    s=status,
                )
            await run(
                'INSERT INTO request_status_events (id, request_id, "from", "to", actor_type, '
                "reason, at) SELECT gen_random_uuid(), id, 'Draft', 'AwaitingApproval', 'USER', "
                "NULL, now() - interval '5 minutes' FROM payment_requests WHERE invoice_no = "
                "'INV-AwaitingApproval-300'"
            )
            await run(
                "INSERT INTO token_movements (id, treasury_id, event_id, wallet, direction, "
                'counterparty, amount, "class", created_at) VALUES (gen_random_uuid(), :t, '
                "gen_random_uuid(), decode(repeat('aa', 20), 'hex'), 'IN', "
                "decode(repeat('55', 20), 'hex'), 2500000, 'INFLOW', now() - interval '1 minute')",
                t=TREASURY,
            )
    finally:
        await engine.dispose()


async def _snapshot(url: str, *, age: timedelta, block: int, data: dict[str, Any]) -> None:
    await _sql(
        url,
        "INSERT INTO snapshots (id, org_id, treasury_id, purpose, block_number, block_hash, "
        "block_timestamp, observed_at, provider, data, coverage, missing) VALUES "
        "(gen_random_uuid(), :o, :t, 'DASHBOARD', :b, decode(repeat('01', 32), 'hex'), "
        "now() - make_interval(secs => :age), now() - make_interval(secs => :age), 'rpc', "
        "CAST(:d AS jsonb), 'COMPLETE', '[]'::jsonb)",
        o=ORG,
        t=TREASURY,
        b=block,
        age=int(age.total_seconds()),
        d=json.dumps(data),
    )


def _app(roles: set[str]) -> FastAPI:
    async def member() -> MemberAccess:
        return MemberAccess(
            access=SimpleNamespace(user=SimpleNamespace(id=USER)),  # type: ignore[arg-type]
            organization_id=ORG,
            roles=frozenset(roles),
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine, sessions = create_session_factory(os.environ["TP_TEST_DATABASE_URL"])
        app.state.request_sessions = sessions
        app.state.treasury_service = TreasuryService(sessions, None, None)  # type: ignore[arg-type]
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.state.platform_configuration = SimpleNamespace(
        chains=[
            SimpleNamespace(
                chain_id=CHAIN,
                assets=[SimpleNamespace(address=TOKEN, symbol="USDC", decimals=6)],
            )
        ]
    )
    app.dependency_overrides[require_member] = member
    app.include_router(router)

    async def handle(request: Request, error: Exception) -> Response:
        assert isinstance(error, AuthFailure)
        return problem_response(request, error)

    app.add_exception_handler(AuthFailure, handle)
    return app


def _no_snapshot_and_no_mandate(url: str) -> None:
    with TestClient(_app({"Owner"})) as client:
        body = client.get(PATH).json()
        # Nothing was read from the chain, so no chain-backed number is returned.
        assert not {"staleness", "position", "budgets"} & set(body)
        assert all("balance" not in wallet for wallet in body["wallets"])
        assert body["mandate"]["version"] == 1 and body["mandate"]["status"] == "Active"
        assert body["queues"] == {"approvals": 2, "governance": 1, "review": 1, "reconciliation": 1}

        asyncio.run(_sql(url, "UPDATE mandate_versions SET status = 'Draft'"))
        body = client.get(PATH).json()
        assert "mandate" in body and body["mandate"] is None  # none set
        asyncio.run(_sql(url, "UPDATE mandate_versions SET status = 'Active'"))


def _full_state(url: str) -> None:
    asyncio.run(_snapshot(url, age=timedelta(seconds=10), block=120, data=_chain_data()))
    with TestClient(_app({"Owner"})) as client:
        body = client.get(PATH).json()
        # Coverage stays nested in `treasury` (no Safe config snapshot here, so it is UNKNOWN).
        assert body["treasury"]["coverage"]["status"] == "UNKNOWN" and "coverage" not in body
        assert body["staleness"]["blockNumber"] == 120 and body["staleness"]["stale"] is False
        assert body["mandate"]["expiresAt"]
        by_label = {w["label"]: w for w in body["wallets"]}
        assert [by_label["T"][k] for k in ("balance", "buffer", "target")] == [
            "50000",
            "5000",
            "5000",  # Safe T has no target: never below its buffer
        ]
        assert [by_label["O1"][k] for k in ("balance", "buffer", "target")] == [
            "1000",
            "500",
            "1500",
        ]
        assert body["budgets"] == [
            {"action": "PAY", "usedToday": "1200", "dailyLimit": "10000", "perRequest": "2000"},
            {"action": "REFILL", "usedToday": "0", "dailyLimit": "6000", "perRequest": "3000"},
        ]
        position = body["position"]
        assert position["requiredReserve"] == {
            "paymentReserve": "800",  # only the Approved 800 is inside the 30-day horizon
            "floor": "5000",
            "holds": "0",
            "total": "5800",
        }
        assert position["safeUsdc"] == "50000" and position["aUsdc"] == "20000"
        assert position["poolLiquidity"] == "15000"
        assert position["availableForSupply"] == "44200"  # 50000 - 5800
        assert position["supplyApyBps"] == 400
        assert position["lastAction"]["kind"] == "NONE" and position["lastAction"]["amount"] == "0"
        assert body["queues"] == {"approvals": 2, "governance": 1, "review": 1, "reconciliation": 1}
        activity = body["activity"]
        assert [a["actor"] for a in activity] == ["chain", "user"]
        assert activity[0]["text"] == "Received 2.500000 USDC"
        assert activity[1]["href"].startswith("requests/")
        assert "balance" not in body["treasury"]


def _roles(url: str) -> None:
    # Queues respect the caller's roles, like the inbox endpoints.
    expected = {
        "Approver": {"approvals": 2, "governance": 1, "review": 0, "reconciliation": 0},
        "Finance": {"approvals": 0, "governance": 1, "review": 1, "reconciliation": 1},
        "Auditor": {"approvals": 0, "governance": 1, "review": 0, "reconciliation": 0},
    }
    for role, queues in expected.items():
        with TestClient(_app({role})) as client:
            assert client.get(PATH).json()["queues"] == queues, role


def _last_action_and_staleness(url: str) -> None:
    plan, step, op = (uuid.uuid4() for _ in range(3))
    asyncio.run(
        _sql(
            url,
            "INSERT INTO plans (id, org_id, treasury_id, request_id, liquidity_cycle_id, status, "
            "chosen_reason) VALUES (:p, :o, :t, NULL, decode(repeat('07', 32), 'hex'), "
            "'Completed', 'SUPPLY_AVAILABLE')",
            p=plan,
            o=ORG,
            t=TREASURY,
        )
    )
    asyncio.run(
        _sql(
            url,
            "INSERT INTO plan_steps (id, attestation_id, plan_id, seq, step_id, action, "
            "request_id, treasury_address, chain_id, from_address, to_address, asset_address, "
            "amount) VALUES (:s, gen_random_uuid(), :p, 0, decode(repeat('08', 32), 'hex'), 4, "
            "decode(repeat('00', 32), 'hex'), decode(repeat('99', 20), 'hex'), 31337, "
            "decode(repeat('aa', 20), 'hex'), decode(repeat('aa', 20), 'hex'), "
            "decode(repeat('11', 20), 'hex'), 9000)",
            s=step,
            p=plan,
        )
    )
    asyncio.run(
        _sql(
            url,
            "INSERT INTO operations (id, treasury_id, plan_step_id, step_id, kind, payload, "
            "idempotency_key) VALUES (:op, :t, :s, decode(repeat('08', 32), 'hex'), 'SUPPLY', "
            "'{}'::jsonb, 'k1')",
            op=op,
            t=TREASURY,
            s=step,
        )
    )
    asyncio.run(
        _sql(
            url,
            "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, from_address, "
            "confirmed_at) VALUES (gen_random_uuid(), :op, 31337, decode(repeat('ab', 32), "
            "'hex'), 1, decode(repeat('dd', 20), 'hex'), now())",
            op=op,
        )
    )
    # A newer snapshot that is 10 minutes old: the balances stay, flagged stale.
    asyncio.run(_sql(url, "UPDATE snapshots SET observed_at = now() - interval '10 minutes'"))
    with TestClient(_app({"Owner"})) as client:
        body = client.get(PATH).json()
        last = body["position"]["lastAction"]
        assert (last["kind"], last["amount"], last["explanation"]) == (
            "SUPPLY",
            "9000",
            "SUPPLY_AVAILABLE",
        )
        assert last["txHash"] == "0x" + "ab" * 32
        assert body["staleness"]["stale"] is True and body["staleness"]["blockNumber"] == 120

        # A mandate read that failed leaves its parts out, not zero.
        data = _chain_data()
        del data["module"]["mandate"], data["aave"]
        asyncio.run(_snapshot(url, age=timedelta(seconds=1), block=130, data=data))
        body = client.get(PATH).json()
        assert body["staleness"]["blockNumber"] == 130 and body["budgets"] == []
        assert body["position"]["aUsdc"] == "0" and body["position"]["supplyApyBps"] == 0


def test_treasury_state_serves_the_dashboard() -> None:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for treasury state integration tests")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = _config(url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed(url))
        _no_snapshot_and_no_mandate(url)
        _full_state(url)
        _roles(url)
        _last_action_and_staleness(url)
    finally:
        # Liquidity plans are evidence: the 0085 downgrade refuses while any exists.
        for table in ("transactions", "operations", "plan_steps", "plans"):
            asyncio.run(_sql(url, f"DELETE FROM {table}"))
        command.downgrade(config, "base")
