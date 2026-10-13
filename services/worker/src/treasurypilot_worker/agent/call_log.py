"""The AI decision log (F-093): one append-only `ai_calls` row per adapter call."""

import asyncio
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.ids import uuid7
from treasurypilot_worker.agent.types import ToolCallRecord

# Tool inputs, tool results and error messages can quote document text; the log keeps only a
# preview.
PREVIEW_CHARS = 200
# A hung database must fail the task fast, not hold it for asyncpg's 60 s connect default.
DB_TIMEOUT_S = 5


class ValidationResult(StrEnum):
    OK = "OK"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    POSTCHECK_FAILED = "POSTCHECK_FAILED"
    REJECTED = "REJECTED"


class AiCallLogError(RuntimeError):
    """The `ai_calls` row could not be written, so the call's result is discarded.

    Not an `AiError`: callers map those to fallbacks, and an unlogged call must fail
    the task instead (fail closed).
    """


@dataclass(frozen=True)
class AiCallEntry:
    org_id: str
    purpose: str
    model: str
    prompt_version: str
    input_refs: tuple[str, ...]
    tool_calls: tuple[ToolCallRecord, ...]
    output: dict[str, Any] | None
    validation_result: ValidationResult | None
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost_usd_micros: int
    error: str | None


class AiCallLog(Protocol):
    def record(self, entry: AiCallEntry) -> str:
        """Append `entry` and return its id. Raise `AiCallLogError` if it was not stored."""
        ...


class InMemoryAiCallLog:
    """Log for tests and local runs without a database."""

    def __init__(self) -> None:
        self.entries: list[AiCallEntry] = []

    def record(self, entry: AiCallEntry) -> str:
        self.entries.append(entry)
        return str(uuid7())


_INSERT = """
INSERT INTO ai_calls (
    id, org_id, purpose, model, prompt_version, input_refs, tool_calls, output,
    validation_result, latency_ms, input_tokens, output_tokens, cost_usd_micros, error
) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, $9, $10, $11, $12, $13, $14)
"""


class PostgresAiCallLog:
    def __init__(self, database_url: str) -> None:
        # Compose hands out the SQLAlchemy form of the URL.
        self._dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    def record(self, entry: AiCallEntry) -> str:
        try:
            return asyncio.run(self._insert(entry))
        except Exception as error:
            raise AiCallLogError(f"ai_calls write failed: {type(error).__name__}") from error

    async def _insert(self, entry: AiCallEntry) -> str:
        # shortcut: one connection per AI call (calls take seconds), and `record` must not run
        # inside an event loop (sync Celery tasks only); pool it and go async if that changes.
        row_id = uuid7()
        connection = await asyncpg.connect(
            self._dsn, timeout=DB_TIMEOUT_S, command_timeout=DB_TIMEOUT_S
        )
        try:
            await connection.execute(
                _INSERT,
                row_id,
                UUID(entry.org_id),
                entry.purpose,
                entry.model,
                entry.prompt_version,
                json.dumps(list(entry.input_refs)),
                json.dumps([_tool_call_json(call) for call in entry.tool_calls]),
                None if entry.output is None else json.dumps(entry.output),
                entry.validation_result,
                entry.latency_ms,
                entry.input_tokens,
                entry.output_tokens,
                entry.cost_usd_micros,
                entry.error,
            )
        finally:
            await connection.close()
        return str(row_id)


def _tool_call_json(call: ToolCallRecord) -> dict[str, Any]:
    input_json = json.dumps(call.input)
    return {
        "id": call.id,
        "name": call.name,
        "input_preview": input_json[:PREVIEW_CHARS],
        "input_chars": len(input_json),
        "result_preview": call.result[:PREVIEW_CHARS],
        "result_chars": len(call.result),
        "is_error": call.is_error,
        "truncated": call.truncated,
    }
