import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import BaseModel, ConfigDict

from treasurypilot_worker.agent import (
    AiAdapter,
    AiCallEntry,
    AiCallLogError,
    AiConfig,
    AiError,
    AiSchemaError,
    AiTask,
    AiUnavailable,
    FakeClock,
    FakeProvider,
    InMemoryAiCallLog,
    InMemoryBudgetLedger,
    PostgresAiCallLog,
    PromptTemplate,
    Slot,
    SourceKind,
    Tool,
    ToolCall,
    UntrustedSource,
    Usage,
    ValidationResult,
    fake_text,
    fake_tool_use,
    wrap_untrusted,
)
from treasurypilot_worker.agent.call_log import _tool_call_json
from treasurypilot_worker.agent.types import ToolCallRecord

API_ROOT = Path(__file__).resolve().parents[3] / "api"
ORG_ID = "00000000-0000-7000-8000-000000000010"


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


class NoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


EXTRACT = PromptTemplate(
    version="extract.test.v1",
    system="You read invoices.",
    instructions="Extract the vendor.",
    slots=(Slot.untrusted("invoice"),),
)
PROMPT = EXTRACT.render(
    invoice=wrap_untrusted(UntrustedSource(SourceKind.INVOICE, "INV-7"), "Acme Ltd, 6000 USDC")
)
DOCUMENT_TOOL = Tool(
    name="read_document",
    description="Read the document text.",
    input_model=NoInput,
    handler=lambda _: {"text": "x" * 5_000},
)


class FailingLog:
    def record(self, entry: AiCallEntry) -> str:
        raise AiCallLogError("ai_calls write failed: ConnectionRefusedError")


def _adapter(provider: FakeProvider, config: AiConfig, clock: FakeClock, now: datetime, log):
    return AiAdapter(
        provider=provider,
        config=config,
        ledger=InMemoryBudgetLedger(),
        call_log=log,
        clock=clock,
        sleep=clock.sleep,
        now=lambda: now,
    )


def test_successful_call_writes_one_row_with_refs_not_text(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    log = InMemoryAiCallLog()
    provider = FakeProvider(
        [
            fake_tool_use(ToolCall("t1", "read_document", {}), usage=Usage(100, 10)),
            fake_text('{"answer": "Acme Ltd"}', Usage(200, 20)),
        ]
    )

    result = _adapter(provider, repo_config, clock, october, log).run(
        AiTask.PLAN, org_id=ORG_ID, prompt=PROMPT, output=Answer, tools=[DOCUMENT_TOOL]
    )

    [entry] = log.entries
    assert result.ai_call_id
    assert entry.purpose == "PLAN"
    assert entry.model == result.model
    assert entry.prompt_version == "extract.test.v1+policy.1"
    assert entry.input_refs == ("invoice:INV-7",)
    assert entry.output == {"answer": "Acme Ltd"}
    assert entry.validation_result is ValidationResult.OK
    assert (entry.input_tokens, entry.output_tokens) == (300, 30)
    assert entry.cost_usd_micros == result.cost_usd_micros
    assert entry.error is None
    assert entry.tool_calls[0].name == "read_document"


def test_failed_call_writes_one_row_and_reraises(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    log = InMemoryAiCallLog()
    provider = FakeProvider([fake_text("not json"), fake_text("still not json")])

    with pytest.raises(AiSchemaError):
        _adapter(provider, repo_config, clock, october, log).run(
            AiTask.EXPLAIN, org_id=ORG_ID, prompt=PROMPT, output=Answer
        )

    [entry] = log.entries
    assert entry.validation_result is ValidationResult.SCHEMA_ERROR
    assert entry.output is None
    assert entry.error is not None and entry.error.startswith("AiSchemaError:")


def test_provider_failure_is_logged_without_a_validation_result(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    log = InMemoryAiCallLog()
    provider = FakeProvider([AiUnavailable("bad request", retryable=False)])

    with pytest.raises(AiUnavailable):
        _adapter(provider, repo_config, clock, october, log).run(
            AiTask.EXPLAIN, org_id=ORG_ID, prompt=PROMPT, output=Answer
        )

    [entry] = log.entries
    assert entry.validation_result is None
    assert entry.error == "AiUnavailable: bad request"


def test_unexpected_exception_is_logged_too(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    def broken(_: NoInput) -> object:
        raise KeyError("missing snapshot")

    log = InMemoryAiCallLog()
    tool = Tool("read_document", "Read the document text.", NoInput, broken)
    provider = FakeProvider([fake_tool_use(ToolCall("t1", "read_document", {}))])

    with pytest.raises(KeyError):
        _adapter(provider, repo_config, clock, october, log).run(
            AiTask.PLAN, org_id=ORG_ID, prompt=PROMPT, output=Answer, tools=[tool]
        )

    [entry] = log.entries
    assert entry.error == "KeyError: 'missing snapshot'"


def test_error_text_is_cut_to_a_preview(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    log = InMemoryAiCallLog()
    provider = FakeProvider([AiUnavailable("x" * 1_000, retryable=False)])

    with pytest.raises(AiUnavailable):
        _adapter(provider, repo_config, clock, october, log).run(
            AiTask.EXPLAIN, org_id=ORG_ID, prompt=PROMPT, output=Answer
        )

    assert len(log.entries[0].error or "") == 200


def test_tool_input_is_cut_to_a_preview() -> None:
    call = ToolCallRecord("t1", "lookup", {"quote": "y" * 1_000}, "ok", False, False)

    logged = _tool_call_json(call)

    assert len(logged["input_preview"]) == 200
    assert logged["input_chars"] == len(json.dumps(call.input))
    assert "input" not in logged


def test_purpose_and_validation_values_match_the_api_model() -> None:
    # Tests may import both services; a value missing from the DB enum would fail every call.
    from treasurypilot_api.agent.models import AiPurpose, AiValidationResult

    assert [task.value for task in AiTask] == [purpose.value for purpose in AiPurpose]
    assert [v.value for v in ValidationResult] == [v.value for v in AiValidationResult]


@pytest.mark.parametrize(
    "response", [fake_text('{"answer": "ok"}'), AiUnavailable("down", retryable=False)]
)
def test_log_write_failure_discards_the_result_and_is_not_an_ai_error(
    repo_config: AiConfig, clock: FakeClock, october: datetime, response: object
) -> None:
    adapter = _adapter(FakeProvider([response]), repo_config, clock, october, FailingLog())

    with pytest.raises(AiCallLogError) as raised:
        adapter.run(AiTask.EXPLAIN, org_id=ORG_ID, prompt=PROMPT, output=Answer)

    # Callers map AiError to fallbacks; an unlogged call must fail the task instead.
    assert not isinstance(raised.value, AiError)


def test_unreachable_database_raises_ai_call_log_error(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    log = PostgresAiCallLog("postgresql+asyncpg://ai:pw@127.0.0.1:1/treasurypilot")
    adapter = _adapter(
        FakeProvider([fake_text('{"answer": "ok"}')]), repo_config, clock, october, log
    )

    with pytest.raises(AiCallLogError, match="ai_calls write failed"):
        adapter.run(AiTask.EXPLAIN, org_id=ORG_ID, prompt=PROMPT, output=Answer)


@pytest.mark.integration
def test_postgres_log_writes_one_append_only_row(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for the ai_calls integration test")
    from alembic import command
    from alembic.config import Config

    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed_org(database_url))
        log = PostgresAiCallLog(database_url)
        provider = FakeProvider(
            [
                fake_tool_use(ToolCall("t1", "read_document", {})),
                fake_text('{"answer": "Acme Ltd"}', Usage(200, 20)),
            ]
        )
        result = _adapter(provider, repo_config, clock, october, log).run(
            AiTask.PLAN, org_id=ORG_ID, prompt=PROMPT, output=Answer, tools=[DOCUMENT_TOOL]
        )
        asyncio.run(_verify_row(database_url, result.ai_call_id))
    finally:
        command.downgrade(config, "base")


async def _seed_org(database_url: str) -> None:
    import asyncpg  # type: ignore[import-untyped]

    connection = await asyncpg.connect(database_url.replace("+asyncpg", "", 1))
    try:
        await connection.execute(
            "INSERT INTO organizations (id, name) VALUES ($1, 'Org A')", UUID(ORG_ID)
        )
    finally:
        await connection.close()


async def _verify_row(database_url: str, ai_call_id: str) -> None:
    import asyncpg  # type: ignore[import-untyped]

    connection = await asyncpg.connect(database_url.replace("+asyncpg", "", 1))
    try:
        rows = await connection.fetch("SELECT * FROM ai_calls")
        assert [row["id"] for row in rows] == [UUID(ai_call_id)]
        row = rows[0]
        assert row["purpose"] == "PLAN"
        assert row["validation_result"] == "OK"
        assert row["input_refs"] == '["invoice:INV-7"]'
        assert '"result_chars": 5012' in row["tool_calls"]
        assert "x" * 201 not in row["tool_calls"]
        for statement in ("UPDATE ai_calls SET error = 'x'", "DELETE FROM ai_calls"):
            with pytest.raises(asyncpg.RaiseError, match="append-only"):
                await connection.execute(statement)
    finally:
        await connection.close()
