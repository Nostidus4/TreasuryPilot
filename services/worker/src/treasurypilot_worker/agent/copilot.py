"""Treasury Copilot (F-090): read-only tool loop, cited answer, deterministic numeric post-check.

The model only reads (AI_AGENT_ARCHITECTURE A4). Two checks do not depend on it: execution
requests get a fixed refusal pointing to the approval flow, and every number in the answer
must appear in a tool result the answer cites.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from treasurypilot_worker.agent.adapter import AiAdapter
from treasurypilot_worker.agent.config import AiTask
from treasurypilot_worker.agent.errors import AiError
from treasurypilot_worker.agent.prompts.copilot import COPILOT_TEMPLATE
from treasurypilot_worker.agent.types import Tool, ToolCallRecord

REFUSAL = (
    "I can't pay, approve or change anything. To execute a payment, create a request and "
    "send it through the approval flow."
)
# An imperative verb at the start of a sentence or after "and/also/please/...".
_EXECUTION = re.compile(
    r"(?:^|[.!?;]\s+|\b(?:please|and|also|then|now|just)\s+)"
    r"(?:go ahead and\s+|can you\s+|could you\s+)?"
    r"(?:pay|send|transfer|wire|execute|approve|release|disburse)\b",
    re.IGNORECASE,
)
_GROUP_COMMA = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?!\w)")


class PostCheckFailed(AiError):
    """The answer carries a number that no cited tool result contains."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Citation(_Strict):
    tool_call_id: str
    path: str


class CopilotAnswer(_Strict):
    answer: str = Field(max_length=4_000)
    citations: list[Citation] = Field(max_length=12)


class CopilotQuestion(_Strict):
    question: str = Field(min_length=1, max_length=2_000)


@dataclass(frozen=True)
class CopilotReply:
    answer: str
    citations: tuple[Citation, ...]
    refused: bool
    ai_call_id: str


def is_execution_request(question: str) -> bool:
    return _EXECUTION.search(question) is not None


def _numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(_GROUP_COMMA.sub("", text)))


def post_check(output: CopilotAnswer, tool_calls: Sequence[ToolCallRecord]) -> None:
    """Raise `PostCheckFailed` unless each number of the answer is in a cited, successful result."""

    results = {call.id: call.result for call in tool_calls if not call.is_error}
    cited: set[str] = set()
    for citation in output.citations:
        if citation.tool_call_id not in results:
            raise PostCheckFailed(f"citation {citation.tool_call_id!r} is not a tool result")
        cited |= _numbers(results[citation.tool_call_id])
    if loose := sorted(_numbers(output.answer) - cited):
        raise PostCheckFailed(f"numbers not found in cited tool results: {loose}")


def ask_copilot(
    adapter: AiAdapter, *, org_id: str, question: str, tools: Sequence[Tool[Any]]
) -> CopilotReply:
    """One Copilot turn. Raises an `AiError` (incl. `PostCheckFailed`) when it cannot answer."""

    prompt = COPILOT_TEMPLATE.render(question=CopilotQuestion(question=question))
    result = adapter.run(
        AiTask.COPILOT, org_id=org_id, prompt=prompt, output=CopilotAnswer, tools=tools
    )
    post_check(result.output, result.tool_calls)
    refused = is_execution_request(question)
    answer = f"{REFUSAL} {result.output.answer}" if refused else result.output.answer
    return CopilotReply(answer, tuple(result.output.citations), refused, result.ai_call_id)
