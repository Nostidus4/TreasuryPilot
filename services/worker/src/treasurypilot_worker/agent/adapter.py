"""The single entry point for LLM calls: routing, deadline, budget, tool loop, schema retry."""

import json
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from treasurypilot_worker.agent.budget import BudgetLedger, cost_usd_micros
from treasurypilot_worker.agent.call_log import (
    PREVIEW_CHARS,
    AiCallEntry,
    AiCallLog,
    ValidationResult,
)
from treasurypilot_worker.agent.config import AiConfig, AiTask, TaskConfig
from treasurypilot_worker.agent.errors import (
    AiBudgetExceeded,
    AiSchemaError,
    AiTimeout,
    AiToolLimitExceeded,
    AiUnavailable,
    ToolError,
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
from treasurypilot_worker.metrics import LLM_COST, LLM_LATENCY

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
        call_log: AiCallLog,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        scanner: SecretScanner | None = None,
    ) -> None:
        self._provider = provider
        self._config = config
        self._ledger = ledger
        self._call_log = call_log
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
        turns, provider retries and the schema retry. The system prompt and every message,
        tool call and tool result are secret-scanned before they are sent; a match raises
        `AiInputRejected` (FR-804). Tool descriptions and the output schema are code, not
        scanned. Messages may carry `0x` bytes32 ids and hashes; untrusted blocks inside
        them were already scanned strictly by `wrap_untrusted`.
        """

        task_config = self._config.tasks[task]
        if tools and task_config.max_tool_calls == 0:
            raise ValueError(f"task {task} has no tool-call budget in the AI config")
        started = self._clock()
        run = _Run(task_config, started=started, deadline=started + task_config.timeout_s)
        try:
            parsed = self._run(task, org_id, prompt, output, tools, run)
        except Exception as error:
            # Any failure is logged before re-raising; a failed write raises AiCallLogError.
            self._log(task, org_id, prompt, run, None, error)
            raise
        ai_call_id = self._log(task, org_id, prompt, run, parsed, None)
        return AiResult(
            output=parsed,
            ai_call_id=ai_call_id,
            task=task.value,
            model=task_config.model,
            prompt_version=prompt.version,
            usage=run.usage,
            cost_usd_micros=run.cost,
            latency_ms=run.latency_ms,
            provider_calls=run.provider_calls,
            schema_retries=run.schema_retries,
            tool_calls=tuple(run.tool_calls),
        )

    def _run[T: BaseModel](
        self,
        task: AiTask,
        org_id: str,
        prompt: RenderedPrompt,
        output: type[T],
        tools: Sequence[Tool[Any]],
        run: "_Run",
    ) -> T:
        task_config = run.task
        month = self._now().strftime("%Y-%m")
        if self._ledger.spent(org_id, month) >= self._config.monthly_budget_usd_micros:
            raise AiBudgetExceeded(f"monthly AI budget spent for org {org_id} in {month}")

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
            try:
                response = self._complete(request, run)
            except AiUnavailable as error:
                if error.usage is not None:
                    self._charge(org_id, month, error.usage, run)
                raise
            self._charge(org_id, month, response.usage, run)
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
                return output.model_validate_json(text)
            except ValidationError as error:
                if run.schema_retries >= MAX_SCHEMA_RETRIES:
                    raise AiSchemaError(f"{task} output failed validation: {error}") from error
                run.schema_retries += 1
                conversation.append(Message("user", (TextBlock(_correction(error)),)))

    def _charge(self, org_id: str, month: str, usage: Usage, run: "_Run") -> None:
        cost = cost_usd_micros(self._config.prices[run.task.model], usage)
        self._ledger.record(org_id, month, cost)
        run.usage += usage
        run.cost += cost

    def _log(
        self,
        task: AiTask,
        org_id: str,
        prompt: RenderedPrompt,
        run: "_Run",
        parsed: BaseModel | None,
        error: Exception | None,
    ) -> str:
        run.latency_ms = round((self._clock() - run.started) * 1000)  # also read by AiResult
        LLM_LATENCY.labels(task=task.value).observe(run.latency_ms / 1000)
        LLM_COST.labels(task=task.value).inc(run.cost / 1_000_000)
        if parsed is not None:
            validation: ValidationResult | None = ValidationResult.OK
        elif isinstance(error, AiSchemaError):
            validation = ValidationResult.SCHEMA_ERROR
        else:
            validation = None
        return self._call_log.record(
            AiCallEntry(
                org_id=org_id,
                purpose=task.value,
                model=run.task.model,
                prompt_version=prompt.version,
                input_refs=prompt.input_refs,
                tool_calls=tuple(run.tool_calls),
                output=None if parsed is None else parsed.model_dump(mode="json"),
                validation_result=validation,
                latency_ms=run.latency_ms,
                input_tokens=run.usage.input_tokens,
                output_tokens=run.usage.output_tokens,
                cost_usd_micros=run.cost,
                # A preview: messages can quote model output (schema errors) or document text.
                error=None if error is None else f"{type(error).__name__}: {error}"[:PREVIEW_CHARS],
            )
        )

    def _scan_new_messages(self, conversation: Sequence[Message], run: "_Run") -> None:
        for index in range(run.scanned_messages, len(conversation)):
            for block in conversation[index].content:
                match block:
                    case TextBlock(text=text):
                        self._scanner.check(text, source=f"message[{index}]", allow_bytes32=True)
                    case ToolCall(id=call_id, input=args):
                        self._scanner.check(
                            json.dumps(args), source=f"tool_call:{call_id}", allow_bytes32=True
                        )
                    case ToolResult(tool_call_id=call_id, content=content):
                        self._scanner.check(
                            content, source=f"tool_result:{call_id}", allow_bytes32=True
                        )
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
    def __init__(self, task: TaskConfig, *, started: float, deadline: float) -> None:
        self.task = task
        self.started = started
        self.deadline = deadline
        self.latency_ms = 0
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
    try:
        result = tool.handler(args)
    except ToolError as error:
        return str(error), True
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
