"""The AI decision log (F-093): one append-only `ai_calls` row per adapter call."""

import asyncio
import json
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_worker.agent.types import ToolCallRecord

# Tool results can quote document text; the log keeps only a preview of each.
TOOL_RESULT_PREVIEW_CHARS = 200


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
        return str(uuid.uuid4())


_INSERT = """
INSERT INTO ai_calls (
    org_id, purpose, model, prompt_version, input_refs, tool_calls, output,
    validation_result, latency_ms, input_tokens, output_tokens, cost_usd_micros, error
) VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8, $9, $10, $11, $12, $13)
RETURNING id
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
        # shortcut: one connection per AI call (calls take seconds); pool it if volume grows.
        connection = await asyncpg.connect(self._dsn)
        try:
            row_id = await connection.fetchval(
                _INSERT,
                uuid.UUID(entry.org_id),
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
    return {
        "id": call.id,
        "name": call.name,
        "input": call.input,
        "result_preview": call.result[:TOOL_RESULT_PREVIEW_CHARS],
        "result_chars": len(call.result),
        "is_error": call.is_error,
        "truncated": call.truncated,
    }
