"""AGT-007 against real Postgres: org scoping and read-only transactions of the agent tools."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic import command
from alembic.config import Config
from pydantic import BaseModel, ConfigDict

from treasurypilot_worker.agent import (
    AiAdapter,
    AiTask,
    FakeProvider,
    InMemoryAiCallLog,
    InMemoryBudgetLedger,
    PromptTemplate,
    ToolCall,
    fake_text,
    fake_tool_use,
    load_ai_config,
)
from treasurypilot_worker.agent.tools import TOOL_NAMES, PostgresToolBackend, build_tools

REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = REPO_ROOT / "services" / "api"
_USER = uuid.UUID("00000000-0000-7000-8000-000000000001")
_ORG = uuid.UUID("00000000-0000-7000-8000-000000000010")
_OTHER_ORG = uuid.UUID("00000000-0000-7000-8000-000000000011")
_ASSET = uuid.UUID("00000000-0000-7000-8000-000000000030")
_TREASURY = uuid.UUID("00000000-0000-7000-8000-000000000040")
_OTHER_TREASURY = uuid.UUID("00000000-0000-7000-8000-000000000041")
_VENDOR = uuid.UUID("00000000-0000-7000-8000-000000000050")
_PAYEE = uuid.UUID("00000000-0000-7000-8000-000000000060")
_SNAPSHOT = uuid.UUID("00000000-0000-7000-8000-000000000070")
_REQUEST = uuid.UUID("00000000-0000-7000-8000-000000000080")


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


PROMPT = PromptTemplate(
    version="tools.it.v1", system="You plan payments.", instructions="Plan.", slots=()
).render()


async def _execute(url: str, statements: list[tuple[str, tuple[object, ...]]]) -> None:
    connection = await asyncpg.connect(url)
    try:
        for sql, args in statements:
            await connection.execute(sql, *args)
    finally:
        await connection.close()


def _snapshot_insert(snapshot_id: uuid.UUID, treasury_id: uuid.UUID, org_id: uuid.UUID, n: int):
    return (
        "INSERT INTO snapshots (id, org_id, treasury_id, purpose, block_number, block_hash, "
        "block_timestamp, provider, data, coverage, missing) VALUES ($1, $2, $3, 'PLAN', $4, "
        "decode(repeat('ab', 32), 'hex'), now(), 'rpc', $5::jsonb, 'COMPLETE', '[]'::jsonb)",
        (snapshot_id, org_id, treasury_id, n, json.dumps({"balances": {"0xsafe": "5000"}})),
    )


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for agent tool integration tests")
    alembic_url = os.environ["TP_TEST_DATABASE_URL"]
    url = alembic_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", alembic_url.replace("%", "%%"))
    command.upgrade(config, "head")
    statements: list[tuple[str, tuple[object, ...]]] = [
        ("INSERT INTO users (id, email) VALUES ($1, 'tools@example.com')", (_USER,)),
        ("INSERT INTO organizations (id, name) VALUES ($1, 'Org A')", (_ORG,)),
        ("INSERT INTO organizations (id, name) VALUES ($1, 'Org B')", (_OTHER_ORG,)),
        (
            "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, "
            "rpc_urls) VALUES (11155111, 'Sepolia', true, 3, 'https://e.io', '[\"https://rpc\"]')",
            (),
        ),
        (
            "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
            "VALUES ($1, 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
            (_ASSET,),
        ),
        (
            "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES ($1, $2, 11155111, $3)",
            (_TREASURY, _ORG, _ASSET),
        ),
        (
            "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES ($1, $2, 11155111, $3)",
            (_OTHER_TREASURY, _OTHER_ORG, _ASSET),
        ),
        _snapshot_insert(_SNAPSHOT, _TREASURY, _ORG, 77),
        _snapshot_insert(uuid.uuid4(), _OTHER_TREASURY, _OTHER_ORG, 99),
        (
            "INSERT INTO vendors (id, org_id, name, normalized_ref) "
            "VALUES ($1, $2, 'Acme Design Ltd', 'acme design ltd')",
            (_VENDOR, _ORG),
        ),
        (
            "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) "
            "VALUES ($1, $2, $3, $4, 'Main', decode(repeat('22', 20), 'hex'), 'Proposed')",
            (_PAYEE, _TREASURY, _ORG, _VENDOR),
        ),
        (
            "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, "
            "payee_id, invoice_no, issue_date, due_at, amount, asset_id, status, fingerprint, "
            "onchain_request_id) VALUES ($1, $2, $3, 11155111, $4, $5, 'INV-7', '2026-10-01', "
            "'2026-10-31', 1250500000, $6, 'Approved', decode(repeat('01', 32), 'hex'), "
            "decode(repeat('ab', 32), 'hex'))",
            (_REQUEST, _ORG, _TREASURY, _VENDOR, _PAYEE, _ASSET),
        ),
        (
            "INSERT INTO mandate_versions (id, org_id, treasury_id, version, onchain_version, "
            "status, config, config_hash, valid_from, expires_at, created_by, activated_at) "
            "VALUES ($1, $2, $3, 1, 1, 'Active', $4::jsonb, decode(repeat('cd', 32), 'hex'), "
            "now(), now() + interval '30 days', $5, now())",
            (
                uuid.uuid4(),
                _ORG,
                _TREASURY,
                json.dumps({"limits": {"PAY": {"perRequest": "1000"}}, "executor": "0xsecret"}),
                _USER,
            ),
        ),
    ]
    try:
        asyncio.run(_execute(url, statements))
        yield url
    finally:
        command.downgrade(config, "base")


class SpyBackend(PostgresToolBackend):
    """Records `transaction_read_only` of every transaction a tool opens."""

    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.read_only: list[str] = []

    async def _execute[T](self, read: Callable[[asyncpg.Connection], Awaitable[T]]) -> T:
        async def checked(connection: asyncpg.Connection) -> T:
            self.read_only.append(await connection.fetchval("SHOW transaction_read_only"))
            return await read(connection)

        return await super()._execute(checked)


def _run_tool(tools: Any, name: str, **args: Any) -> tuple[str, bool]:
    provider = FakeProvider([fake_tool_use(ToolCall("t1", name, args)), fake_text('{"answer":""}')])
    adapter = AiAdapter(
        provider=provider,
        config=load_ai_config(REPO_ROOT / "config" / "ai.yaml"),
        ledger=InMemoryBudgetLedger(),
        call_log=InMemoryAiCallLog(),
    )
    result = adapter.run(AiTask.PLAN, org_id=str(_ORG), prompt=PROMPT, output=Answer, tools=tools)  # type: ignore[arg-type]
    (record,) = result.tool_calls
    return record.result, record.is_error


def test_tools_read_their_own_orgs_rows(database_url: str) -> None:
    tools = build_tools(PostgresToolBackend(database_url), str(_ORG))
    treasury = {"treasury_id": str(_TREASURY)}

    snapshot, _ = _run_tool(tools, "get_snapshot", **treasury)
    requests, _ = _run_tool(tools, "list_requests", **treasury)
    policy, _ = _run_tool(tools, "get_policy_summary", **treasury)
    evidence, _ = _run_tool(tools, "get_evidence", evidence_id=str(_SNAPSHOT))

    assert json.loads(snapshot)["block_number"] == 77
    (row,) = json.loads(requests)["requests"]
    assert row["amount"] == "1250500000" and "Acme Design Ltd" in row["vendor"]
    body = json.loads(policy)
    assert body["mandate"] == {"limits": {"PAY": {"perRequest": "1000"}}}
    assert body["payees"][0]["address"] == "0x2222...2222"
    assert json.loads(evidence)["summary"]["coverage"] == "COMPLETE"


def test_another_orgs_treasury_and_evidence_are_refused(database_url: str) -> None:
    tools = build_tools(PostgresToolBackend(database_url), str(_ORG))

    for name in ("get_snapshot", "list_requests", "get_policy_summary"):
        result, is_error = _run_tool(tools, name, treasury_id=str(_OTHER_TREASURY))
        assert is_error and result.startswith("REFUSED"), name
    other = asyncio.run(
        _fetch(database_url, "SELECT id FROM snapshots WHERE treasury_id = $1", _OTHER_TREASURY)
    )
    result, is_error = _run_tool(tools, "get_evidence", evidence_id=str(other))
    assert is_error and result.startswith("REFUSED")


async def _fetch(url: str, sql: str, *args: object) -> uuid.UUID:
    connection = await asyncpg.connect(url)
    try:
        return await connection.fetchval(sql, *args)  # type: ignore[no-any-return]
    finally:
        await connection.close()


def test_every_tool_runs_in_a_read_only_transaction(database_url: str) -> None:
    backend = SpyBackend(database_url)
    tools = build_tools(
        backend,
        str(_ORG),
        simulation=lambda org, treasury: None,
        decisions=lambda org, validation: None,
    )
    assert tuple(tool.name for tool in tools) == TOOL_NAMES
    arguments = {
        "get_snapshot": {"treasury_id": str(_TREASURY)},
        "list_requests": {"treasury_id": str(_TREASURY)},
        "get_policy_summary": {"treasury_id": str(_TREASURY)},
        "simulate_schedule": {"treasury_id": str(_TREASURY)},
        "get_evidence": {"evidence_id": str(_SNAPSHOT)},
        "explain_decision": {"validation_id": str(uuid.uuid4())},
    }

    for tool in tools:
        backend.read_only.clear()
        _run_tool([tool], tool.name, **arguments[tool.name])
        # explain_decision reads a decision store, not this database.
        assert backend.read_only or tool.name == "explain_decision", tool.name
        assert set(backend.read_only) <= {"on"}, tool.name


def test_the_database_refuses_a_write_through_the_backend(database_url: str) -> None:
    backend = PostgresToolBackend(database_url)

    async def write(connection: asyncpg.Connection) -> None:
        await connection.execute("UPDATE organizations SET name = 'hijacked'")

    with pytest.raises(asyncpg.exceptions.ReadOnlySQLTransactionError):
        asyncio.run(backend._execute(write))
