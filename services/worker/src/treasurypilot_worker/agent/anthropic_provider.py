"""Anthropic Messages API implementation of `Provider` (ADR-005, M09-D1)."""

from typing import Any, cast

import anthropic
from anthropic.types import Message as AnthropicMessage
from anthropic.types import MessageParam, TextBlockParam, ToolParam

from treasurypilot_worker.agent.errors import AiTimeout, AiUnavailable
from treasurypilot_worker.agent.types import (
    Message,
    ProviderRequest,
    ProviderResponse,
    StopReason,
    TextBlock,
    ToolCall,
    ToolResult,
    Usage,
)

_STOP_REASONS = {
    "end_turn": StopReason.END_TURN,
    "stop_sequence": StopReason.END_TURN,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "refusal": StopReason.REFUSAL,
}
_RETRYABLE_STATUS = {408, 409, 429}
# Not retryable, but the next provider has its own credentials and account.
_FAILOVER_STATUS = {401, 403}


class AnthropicProvider:
    """One Messages API request per call. Retries belong to the adapter, which owns the deadline."""

    def __init__(
        self,
        client: anthropic.Anthropic | anthropic.AnthropicBedrockMantle | None = None,
        *,
        name: str,
        model_prefix: str = "",
    ) -> None:
        self._client = (client or anthropic.Anthropic()).with_options(max_retries=0)
        self.name = name
        # shortcut: plain prefix covers "anthropic." ids; Bedrock cross-region or versioned ids
        # would need a per-model map in config.
        self._model_prefix = model_prefix

    def complete(self, request: ProviderRequest, *, timeout_s: float) -> ProviderResponse:
        tools: list[ToolParam] = [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": cast(Any, anthropic.transform_schema(spec.input_schema)),
                "strict": True,
            }
            for spec in request.tools
        ]
        # Tools render before the system prompt, so one breakpoint here caches both;
        # the (untrusted, per-call) messages after it are never cached.
        system: list[TextBlockParam] = [
            {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}
        ]
        try:
            message = self._client.with_options(timeout=timeout_s).messages.create(
                model=self._model_prefix + request.model,
                max_tokens=request.max_output_tokens,
                system=system,
                messages=[_to_param(m) for m in request.messages],
                tools=tools if tools else anthropic.omit,
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": anthropic.transform_schema(request.output_schema),
                    }
                },
            )
        except anthropic.APITimeoutError as error:
            raise AiTimeout(f"{self.name} request timed out after {timeout_s:.1f}s") from error
        except anthropic.APIConnectionError as error:
            raise AiUnavailable(
                f"{self.name} connection failed: {error}", retryable=True
            ) from error
        except anthropic.APIStatusError as error:
            retryable = error.status_code in _RETRYABLE_STATUS or error.status_code >= 500
            raise AiUnavailable(
                f"{self.name} returned {error.status_code} (request {error.request_id}): "
                f"{error.message}",
                retryable=retryable,
                failover=retryable or error.status_code in _FAILOVER_STATUS,
            ) from error
        return _from_message(message)


def _to_param(message: Message) -> MessageParam:
    if message.role == "assistant" and message.provider_content is not None:
        # Echo assistant blocks verbatim so thinking blocks stay valid across tool turns.
        return {"role": "assistant", "content": cast(Any, message.provider_content)}
    blocks: list[Any] = []
    for block in message.content:
        match block:
            case TextBlock(text=text):
                blocks.append({"type": "text", "text": text})
            case ToolCall(id=id_, name=name, input=input_):
                blocks.append({"type": "tool_use", "id": id_, "name": name, "input": input_})
            case ToolResult(tool_call_id=id_, content=content, is_error=is_error):
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": id_,
                        "content": content,
                        "is_error": is_error,
                    }
                )
    return {"role": message.role, "content": blocks}


def _from_message(message: AnthropicMessage) -> ProviderResponse:
    usage = Usage(
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
        cache_write_tokens=message.usage.cache_creation_input_tokens or 0,
        cache_read_tokens=message.usage.cache_read_input_tokens or 0,
    )
    stop_reason = _STOP_REASONS.get(message.stop_reason or "")
    if stop_reason is None:
        raise AiUnavailable(
            f"unsupported stop reason {message.stop_reason!r} (request {message._request_id})",
            retryable=False,
            usage=usage,
        )
    texts = [block.text for block in message.content if block.type == "text"]
    calls = tuple(
        ToolCall(block.id, block.name, dict(cast(dict[str, Any], block.input)))
        for block in message.content
        if block.type == "tool_use"
    )
    return ProviderResponse(
        stop_reason=stop_reason,
        text="".join(texts) if texts else None,
        tool_calls=calls,
        usage=usage,
        provider_content=list(message.content),
    )
