"""Provider-neutral messages and the `Provider` seam the adapter drives."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class TextBlock:
    text: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


ContentBlock = TextBlock | ToolCall | ToolResult


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: tuple[ContentBlock, ...]
    # Raw provider blocks of an assistant turn (e.g. thinking blocks) echoed back verbatim.
    provider_content: object | None = field(default=None, compare=False)


class StopReason(StrEnum):
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    REFUSAL = "refusal"


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
        )


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ProviderRequest:
    model: str
    system: str
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...]
    output_schema: dict[str, Any]
    max_output_tokens: int


@dataclass(frozen=True)
class ProviderResponse:
    stop_reason: StopReason
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = Usage(0, 0)
    provider_content: object | None = None


class Provider(Protocol):
    def complete(self, request: ProviderRequest, *, timeout_s: float) -> ProviderResponse:
        """Run one model turn. Raises `AiTimeout` or `AiUnavailable` on failure."""
        ...


@dataclass(frozen=True)
class Tool[I: BaseModel]:
    """Read-only tool. The handler result must be JSON-serialisable or a Pydantic model."""

    name: str
    description: str
    input_model: type[I]
    handler: Callable[[I], object]


@dataclass(frozen=True)
class ToolCallRecord:
    id: str
    name: str
    input: dict[str, Any]
    result: str
    is_error: bool
    truncated: bool


@dataclass(frozen=True)
class AiResult[T: BaseModel]:
    output: T
    task: str
    model: str
    prompt_version: str
    usage: Usage
    cost_usd_micros: int
    latency_ms: int
    provider_calls: int
    schema_retries: int
    tool_calls: tuple[ToolCallRecord, ...]
