"""Runway forecast route (WEB-021): engine projection serialized to the documented shape."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
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
from treasurypilot_api.treasury.forecast import router
from treasurypilot_api.treasury.service import TreasuryService
from treasurypilot_api.treasury.sync import asset_id

API_ROOT = Path(__file__).parents[1]
CHAIN = 31337
TOKEN = "0x" + "11" * 20
ORG, USER, TREASURY, VENDOR, PAYEE = (uuid.uuid4() for _ in range(5))
ASSET = asset_id(CHAIN, TOKEN)
WALLETS = {"T": "aa", "O1": "bb", "O2": "cc"}
ADDRESS = {label: "0x" + byte * 20 for label, byte in WALLETS.items()}
BALANCE = {"T": 10_000, "O1": 1_000, "O2": 500}
BUFFER = {"T": 1_000, "O1": 500, "O2": 100}
TODAY = int(datetime.now(UTC).timestamp()) // 86_400


def _iso(offset: int) -> str:
    return (date(1970, 1, 1) + timedelta(days=TODAY + offset)).isoformat()


class _Rpc:
    fail = False

    async def call(self, chain_id: int, method: str, params: list[Any]) -> str:
        assert (chain_id, method) == (CHAIN, "eth_call") and params[0]["to"] == TOKEN
        if self.fail:
            raise RuntimeError("rpc down")
        holder = "0x" + params[0]["data"][-40:]
        label = next(k for k, v in ADDRESS.items() if v == holder)
        return hex(BALANCE[label])


class _Governance:
    used = {1: 0, 2: 0}

    async def read_used_today(
        self, chain_id: int, module: bytes, asset: bytes, action: int = 1
    ) -> int:
        assert (chain_id, module, asset) == (
            CHAIN,
            bytes.fromhex("99" * 20),
            bytes.fromhex("11" * 20),
        )
        return self.used[action]


GOVERNANCE = _Governance()


def _config(url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


async def _seed(url: str) -> None:
    mandate = {
        "limits": {
            "PAY": {"perRequest": "5000", "daily": "5000"},
            "REFILL": {"perRequest": "5000", "daily": "5000"},
        },
        "buffers": [
            {"wallet": ADDRESS[k], "minimum": str(BUFFER[k]), "target": str(BUFFER[k] * 3)}
            for k in WALLETS
        ],
    }

    def terms(offset: int) -> str:
        return json.dumps({"net_due_day": TODAY + offset})

    engine, _ = create_session_factory(url)
    try:
        async with engine.begin() as c:
            await c.execute(text("SET LOCAL session_replication_role = replica"))

            async def run(sql: str, **p: object) -> None:
                await c.execute(text(sql), p)

            await run("INSERT INTO organizations (id, name) VALUES (:o, 'fc')", o=ORG)
            await run("INSERT INTO users (id, email) VALUES (:u, 'fc@example.test')", u=USER)
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
            for label, byte in WALLETS.items():
                await run(
                    "INSERT INTO treasury_wallets (id, org_id, treasury_id, chain_id, role, "
                    "label, safe_address, owners, threshold) VALUES (gen_random_uuid(), :o, :t, "
                    "31337, CAST(:role AS treasury_wallet_role), :label, decode(repeat(:b, 20), "
                    "'hex'), '[\"0x1\"]'::jsonb, 1)",
                    o=ORG,
                    t=TREASURY,
                    role="SOURCE" if label == "T" else "OPERATIONAL",
                    label=label,
                    b=byte,
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
            for status, amount, offset in (("Approved", 800, 1), ("Draft", 300, 2)):
                await run(
                    "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, "
                    "payee_id, invoice_no, issue_date, due_at, amount, asset_id, status, terms, "
                    "terms_confirmed_by, terms_confirmed_at, fingerprint) VALUES (gen_random_uuid(), :o, :t, "
                    "31337, :v, :p, :n, current_date, current_date + 3, :amt, :a, :s, "
                    "CAST(:terms AS jsonb), :u, now(), :fp)",
                    o=ORG,
                    t=TREASURY,
                    v=VENDOR,
                    p=PAYEE,
                    n=f"INV-{status}",
                    fp=hashlib.sha256(status.encode()).digest(),
                    amt=amount,
                    a=ASSET,
                    s=status,
                    terms=terms(offset),
                    u=USER,
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
    finally:
        await engine.dispose()


def _app(*, real_member: bool = False) -> tuple[FastAPI, _Rpc, list[uuid.UUID]]:
    rpc = _Rpc()
    org = [ORG]

    async def member() -> MemberAccess:
        return MemberAccess(
            access=SimpleNamespace(user=SimpleNamespace(id=USER)),  # type: ignore[arg-type]
            organization_id=org[0],
            roles=frozenset({"Auditor"}),
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine, sessions = create_session_factory(os.environ["TP_TEST_DATABASE_URL"])
        app.state.request_sessions = sessions
        app.state.treasury_service = TreasuryService(sessions, None, None)  # type: ignore[arg-type]
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.state.fee_history_provider = rpc
    app.state.platform_configuration = SimpleNamespace(
        chains=[SimpleNamespace(chain_id=CHAIN, assets=[SimpleNamespace(address=TOKEN)])]
    )
    app.state.governance_service = GOVERNANCE
    if not real_member:
        app.dependency_overrides[require_member] = member
    app.include_router(router)

    async def handle(request: Request, error: Exception) -> Response:
        assert isinstance(error, AuthFailure)
        return problem_response(request, error)

    app.add_exception_handler(AuthFailure, handle)
    return app, rpc, org


def _checks() -> None:
    app, rpc, org = _app()
    path = f"/v1/orgs/{ORG}/treasuries/{TREASURY}/forecast"
    with TestClient(app) as client:
        body = client.get(path).json()
        assert [d["date"] for d in body["days"]] == [_iso(i) for i in range(7)]
        # O1 pays 800 on its due day from 1000, below its 500 buffer, so the engine refills it.
        refill = body["suggestedRefills"]
        assert len(refill) == 1 and refill[0]["date"] <= _iso(1)
        assert refill[0]["sourceAddress"].lower() == ADDRESS["T"]
        assert refill[0]["targetAddress"].lower() == ADDRESS["O1"]
        assert int(refill[0]["amount"]) > 0 and refill[0]["requestId"]
        assert sum(int(d["outflow"]) for d in body["days"]) == 800  # the draft is excluded
        assert {d["buffer"] for d in body["days"]} == {"500"}
        assert [w["role"] for w in body["wallets"]] == ["O1", "O2"]
        assert [w["safeAddress"].lower() for w in body["wallets"]] == [
            ADDRESS["O1"],
            ADDRESS["O2"],
        ]
        assert [w["buffer"] for w in body["wallets"]] == ["500", "100"]
        assert [d["balance"] for d in body["wallets"][1]["days"]] == ["500"] * 7
        assert [d["balance"] for d in body["wallets"][0]["days"]] == [
            d["balance"] for d in body["days"]
        ]
        assert body["alerts"] == []  # the refill keeps O1 above its buffer

        drafts = client.get(path, params={"includeDrafts": "true"}).json()
        assert sum(int(d["outflow"]) for d in drafts["days"]) == 1_100

        # Other org's treasury is invisible; a treasury without an active mandate is a 409.
        org[0] = uuid.uuid4()
        assert client.get(path).status_code == 404
        org[0] = ORG
        rpc.fail = True
        failed = client.get(path)
        assert (failed.status_code, failed.json()["code"]) == (503, "FORECAST_UNAVAILABLE")
        rpc.fail = False


async def _mandate_status(url: str, status: str) -> None:
    engine, _ = create_session_factory(url)
    async with engine.begin() as c:
        await c.execute(text("UPDATE mandate_versions SET status = :s"), {"s": status})
    await engine.dispose()


async def _sql(url: str, sql: str, **params: object) -> None:
    engine, _ = create_session_factory(url)
    async with engine.begin() as c:
        await c.execute(text("SET LOCAL session_replication_role = replica"))  # skip immutability
        await c.execute(text(sql), params)
    await engine.dispose()


def _edge_cases(url: str) -> None:
    app, _, _ = _app()
    path = f"/v1/orgs/{ORG}/treasuries/{TREASURY}/forecast"
    limits = {"PAY": {"perRequest": "5000", "daily": "5000"}}
    buffers = [
        {"wallet": ADDRESS[k], "minimum": str(BUFFER[k]), "target": str(BUFFER[k] * 3)}
        for k in WALLETS
    ]

    def mandate(**override: object) -> None:
        config = {"limits": {**limits, "REFILL": limits["PAY"]}, "buffers": buffers, **override}
        asyncio.run(
            _sql(
                url, "UPDATE mandate_versions SET config = CAST(:c AS jsonb)", c=json.dumps(config)
            )
        )

    def failure(client: TestClient) -> tuple[int, str]:
        response = client.get(path)
        return response.status_code, response.json().get("code", "")

    with TestClient(app) as client:
        refill = client.get(path).json()["suggestedRefills"][0]
        assert (refill["date"], refill["amount"]) == (_iso(0), "1300")  # target 1500 - (1000 - 800)

        # PAY usage already on chain shrinks the cap: the 800 payment no longer lands today.
        GOVERNANCE.used = {1: 4_900, 2: 0}
        capped = client.get(path).json()
        assert [d["outflow"] for d in capped["days"]][:2] == ["0", "800"]
        GOVERNANCE.used = {1: 0, 2: 0}

        # A refill that cannot be funded leaves O1 under its buffer, which raises an alert.
        mandate(limits={**limits, "REFILL": {"perRequest": "1", "daily": "1"}})
        alerts = client.get(path).json()["alerts"]
        assert len(alerts) == 1 and alerts[0]["message"].startswith("O1 ")

        # Requests without a paying wallet use O1; an assigned O2 request hits O2 instead.
        mandate()
        asyncio.run(
            _sql(
                url,
                "UPDATE payment_requests SET paying_wallet_id = (SELECT id FROM treasury_wallets "
                "WHERE label = 'O2') WHERE status = 'Approved'",
            )
        )
        body = client.get(path).json()
        assert sum(int(d["outflow"]) for d in body["days"]) == 0
        assert body["wallets"][1]["days"][1]["balance"] != "500"  # O2 paid / was refilled

        # Mandates the forecast cannot use are 409, not 500.
        mandate(buffers=buffers[:2])
        assert failure(client) == (409, "MANDATE_NOT_ACTIVE")  # O2 has no buffer entry
        mandate(limits=limits)
        assert failure(client) == (409, "MANDATE_NOT_ACTIVE")  # no REFILL limits
        mandate(limits={})
        assert failure(client) == (409, "MANDATE_NOT_ACTIVE")  # no PAY limits
        mandate(buffers="nope")
        assert failure(client) == (409, "MANDATE_NOT_ACTIVE")  # does not validate
    mandate()
    asyncio.run(_sql(url, "UPDATE payment_requests SET paying_wallet_id = NULL"))


def test_forecast_route_serializes_engine_projection() -> None:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for forecast integration tests")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = _config(url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed(url))
        _checks()
        _edge_cases(url)
        asyncio.run(_mandate_status(url, "Revoked"))
        app, _, _ = _app()
        with TestClient(app) as client:
            response = client.get(f"/v1/orgs/{ORG}/treasuries/{TREASURY}/forecast")
            assert (response.status_code, response.json()["code"]) == (409, "MANDATE_NOT_ACTIVE")
    finally:
        command.downgrade(config, "base")
