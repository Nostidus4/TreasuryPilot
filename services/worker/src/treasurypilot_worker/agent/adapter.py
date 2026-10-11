"""The single entry point for LLM calls: routing, deadline, budget, tool loop, schema retry."""

import json
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from treasurypilot_worker.agent.budget import BudgetLedger, cost_usd_micros
from treasurypilot_worker.agent.config import AiConfig, AiTask, TaskConfig
from treasurypilot_worker.agent.errors import (
    AiBudgetExceeded,
    AiSchemaError,
    AiTimeout,
    AiToolLimitExceeded,
    AiUnavailable,
)
from treasurypilot_worker.agent.prompts import RenderedPrompt
from treasurypilot_worker.agent.secret_scan import SecretScanner, default_scanner
from treasurypilot_worker.agent.types import (
    AiResult,
    ContentBlock,
    Message,
    Provider,
    ProviderRequest,
    ProviderResponse,
    StopReason,
    TextBlock,
    Tool,
    ToolCall,
    ToolCallRecord,
    ToolResult,
    ToolSpec,
    Usage,
)

MAX_PROVIDER_RETRIES = 2
RETRY_BACKOFF_S = 0.5
MAX_SCHEMA_RETRIES = 1  # M09-D9


class AiAdapter:
    def __init__(
        self,
        *,
        provider: Provider,
        config: AiConfig,
        ledger: BudgetLedger,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        scanner: SecretScanner | None = None,
    ) -> None:
        self._provider = provider
        self._config = config
        self._ledger = ledger
        self._clock = clock
        self._sleep = sleep
        self._now = now
        self._scanner = scanner or default_scanner()

    @property
    def config(self) -> AiConfig:
        return self._config

    def run[T: BaseModel](
        self,
        task: AiTask,
        *,
        org_id: str,
        prompt: RenderedPrompt,
        output: type[T],
        tools: Sequence[Tool[Any]] = (),
    ) -> AiResult[T]:
        """Run `task` to a validated `output`, or raise a subclass of `AiError`.

        The task's timeout is a wall-clock deadline for the whole call, including tool
        turns, provider retries and the schema retry. Every input is secret-scanned before
        it is sent; a match raises `AiInputRejected` (FR-804).
        """

        task_config = self._config.tasks[task]
        if tools and task_config.max_tool_calls == 0:
            raise ValueError(f"task {task} has no tool-call budget in the AI config")
        month = self._now().strftime("%Y-%m")
        if self._ledger.spent(org_id, month) >= self._config.monthly_budget_usd_micros:
            raise AiBudgetExceeded(f"monthly AI budget spent for org {org_id} in {month}")

        started = self._clock()
        run = _Run(task_config, deadline=started + task_config.timeout_s)
        tools_by_name = {tool.name: tool for tool in tools}
        conversation = list(prompt.messages)
        specs = tuple(
            ToolSpec(t.name, t.description, t.input_model.model_json_schema()) for t in tools
        )
        schema = output.model_json_schema()

        self._scanner.check(prompt.system, source="system")
        while True:
            self._scan_new_messages(conversation, run)
            request = ProviderRequest(
                model=task_config.model,
                system=prompt.system,
                messages=tuple(conversation),
                tools=specs,
                output_schema=schema,
                max_output_tokens=task_config.max_output_tokens,
            )
            response = self._complete(request, run)
            cost = cost_usd_micros(self._config.prices[task_config.model], response.usage)
            self._ledger.record(org_id, month, cost)
            run.usage += response.usage
            run.cost += cost
            if self._clock() > run.deadline:
                raise AiTimeout(f"{task} exceeded its {task_config.timeout_s}s deadline")

            if response.stop_reason in (StopReason.MAX_TOKENS, StopReason.REFUSAL):
                raise AiSchemaError(f"{task} output unusable: stop reason {response.stop_reason}")

            conversation.append(_assistant_turn(response))
            if response.stop_reason is StopReason.TOOL_USE:
                conversation.append(self._run_tools(response.tool_calls, tools_by_name, run))
                continue

            text = response.text or ""
            try:
                parsed = output.model_validate_json(text)
            except ValidationError as error:
                if run.schema_retries >= MAX_SCHEMA_RETRIES:
                    raise AiSchemaError(f"{task} output failed validation: {error}") from error
                run.schema_retries += 1
                conversation.append(Message("user", (TextBlock(_correction(error)),)))
                continue

            return AiResult(
                output=parsed,
                task=task.value,
                model=task_config.model,
                prompt_version=prompt.version,
                usage=run.usage,
                cost_usd_micros=run.cost,
                latency_ms=round((self._clock() - started) * 1000),
                provider_calls=run.provider_calls,
                schema_retries=run.schema_retries,
                tool_calls=tuple(run.tool_calls),
            )

    def _scan_new_messages(self, conversation: Sequence[Message], run: "_Run") -> None:
        for index in range(run.scanned_messages, len(conversation)):
            for block in conversation[index].content:
                match block:
                    case TextBlock(text=text):
                        self._scanner.check(text, source=f"message[{index}]")
                    case ToolCall(id=call_id, input=args):
                        self._scanner.check(json.dumps(args), source=f"tool_call:{call_id}")
                    case ToolResult(tool_call_id=call_id, content=content):
                        self._scanner.check(content, source=f"tool_result:{call_id}")
        run.scanned_messages = len(conversation)

    def _complete(self, request: ProviderRequest, run: "_Run") -> ProviderResponse:
        attempt = 0
        while True:
            remaining = run.deadline - self._clock()
            if remaining <= 0:
                raise AiTimeout("deadline passed before the provider call")
            run.provider_calls += 1
            try:
                return self._provider.complete(request, timeout_s=remaining)
            except AiUnavailable as error:
                if not error.retryable or attempt >= MAX_PROVIDER_RETRIES:
                    raise
                backoff = RETRY_BACKOFF_S * 2**attempt
                if self._clock() + backoff >= run.deadline:
                    raise AiTimeout("deadline leaves no time to retry the provider") from error
                attempt += 1
                self._sleep(backoff)

    def _run_tools(
        self,
        calls: Sequence[ToolCall],
        tools_by_name: dict[str, Tool[Any]],
        run: "_Run",
    ) -> Message:
        if len(run.tool_calls) + len(calls) > run.task.max_tool_calls:
            raise AiToolLimitExceeded(
                f"model asked for more than {run.task.max_tool_calls} tool calls"
            )
        results: list[ContentBlock] = []
        for call in calls:
            content, is_error = _execute(call, tools_by_name)
            content, truncated = _cap(content, run.task.tool_result_max_bytes)
            results.append(ToolResult(call.id, content, is_error=is_error))
            run.tool_calls.append(
                ToolCallRecord(call.id, call.name, call.input, content, is_error, truncated)
            )
        return Message("user", tuple(results))


class _Run:
    def __init__(self, task: TaskConfig, deadline: float) -> None:
        self.task = task
        self.deadline = deadline
        self.usage = Usage(0, 0)
        self.cost = 0
        self.provider_calls = 0
        self.schema_retries = 0
        self.scanned_messages = 0
        self.tool_calls: list[ToolCallRecord] = []


def _assistant_turn(response: ProviderResponse) -> Message:
    content: list[ContentBlock] = []
    if response.text:
        content.append(TextBlock(response.text))
    content.extend(response.tool_calls)
    return Message("assistant", tuple(content), provider_content=response.provider_content)


def _execute(call: ToolCall, tools_by_name: dict[str, Tool[Any]]) -> tuple[str, bool]:
    tool = tools_by_name.get(call.name)
    if tool is None:
        return f"Unknown tool {call.name!r}. Available: {sorted(tools_by_name)}", True
    try:
        args = tool.input_model.model_validate(call.input)
    except ValidationError as error:
        return f"Invalid input for {call.name}: {error}", True
    result = tool.handler(args)
    if isinstance(result, BaseModel):
        return result.model_dump_json(), False
    return json.dumps(result), False


def _cap(content: str, max_bytes: int) -> tuple[str, bool]:
    encoded = content.encode()
    if len(encoded) <= max_bytes:
        return content, False
    head = encoded[:max_bytes].decode(errors="ignore")
    return f"{head}\n[truncated: result was {len(encoded)} bytes, limit {max_bytes}]", True


def _correction(error: ValidationError) -> str:
    return (
        "Your previous output failed validation against the required schema:\n"
        f"{error}\n"
        "Reply again with only a JSON object that satisfies the schema."
    )
