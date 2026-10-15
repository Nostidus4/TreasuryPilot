"""AI exception-request draft (AGT-011): engine numbers in, numeric post-check, template fallback."""

import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from typing import Literal

import asyncpg  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from treasurypilot_worker.agent.adapter import AiAdapter
from treasurypilot_worker.agent.config import AiTask
from treasurypilot_worker.agent.errors import AiError, PostCheckFailed
from treasurypilot_worker.agent.prompts.exception_draft import EXCEPTION_DRAFT_TEMPLATE
from treasurypilot_worker.locks import _asyncpg_database_url

# Grouped (1,234 / 1,234.50) or plain digits, optionally signed. "1,2500" does not parse as one number.
# shortcut: percentages ("25%") are rejected deliberately (never an engine number) and numbers
# written as words are not checked; the prompt tells the model to quote digits. Upgrade if drafts need them.
_NUMBER = re.compile(r"[-+\u2212]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+\u2212]?\d+(?:\.\d+)?")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExceptionFacts(_Strict):
    """Engine numbers as the Owner sees them (display strings, e.g. "3,000"); the only numbers allowed."""

    amount: str
    cap: str
    excess: str
    daily_used: str
    daily_remaining_after: str


class Reason(_Strict):
    text: str = Field(min_length=1, max_length=500)
    evidence_ids: tuple[str, ...] = ()


class ExceptionDraft(_Strict):
    summary: str = Field(min_length=1, max_length=600)
    reasons: tuple[Reason, ...] = Field(max_length=10)
    alternatives: tuple[str, ...] = Field(max_length=10)


@dataclass(frozen=True)
class DraftOutcome:
    draft: ExceptionDraft
    source: Literal["AI", "TEMPLATE"]
    ai_call_id: str | None  # the call that produced `draft`; None for a template


def template_draft(facts: ExceptionFacts) -> ExceptionDraft:
    return ExceptionDraft(
        summary=f"The payment of {facts.amount} exceeds the per-payment cap of {facts.cap} "
        f"by {facts.excess}.",
        reasons=(
            Reason(
                text=f"The payment is {facts.amount} against a cap of {facts.cap}.",
                evidence_ids=("amount", "cap"),
            ),
            Reason(
                text=f"{facts.daily_used} of the daily limit is already used; "
                f"{facts.daily_remaining_after} would remain after this payment.",
                evidence_ids=("daily_used", "daily_remaining_after"),
            ),
        ),
        alternatives=(
            "Split the payment into parts that are each within the cap.",
            "Change the mandate cap, then pay without an exception.",
        ),
    )


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").replace("\u2212", "-").lstrip("+") for n in _NUMBER.findall(text)}


def _matches_engine(draft: ExceptionDraft, facts: ExceptionFacts) -> bool:
    """Every number in the prose is an engine number (exact), every cited fact exists."""

    prose = " ".join([draft.summary, *(r.text for r in draft.reasons), *draft.alternatives])
    allowed = {n for value in facts.model_dump().values() for n in _numbers(value)}
    cited = {e for r in draft.reasons for e in r.evidence_ids}
    return _numbers(prose) <= allowed and cited <= set(ExceptionFacts.model_fields)


def draft_exception(adapter: AiAdapter, *, org_id: str, facts: ExceptionFacts) -> DraftOutcome:
    """AI draft if its numbers match the engine's, else the template (BR-043). Never raises `AiError`."""

    def post_check(output: ExceptionDraft, _tool_calls: object) -> None:
        if not _matches_engine(output, facts):
            raise PostCheckFailed("draft numbers or evidence ids do not match the engine facts")

    try:
        result = adapter.run(
            AiTask.EXCEPTION_DRAFT,
            org_id=org_id,
            prompt=EXCEPTION_DRAFT_TEMPLATE.render(facts=facts),
            output=ExceptionDraft,
            post_check=post_check,
        )
    except AiError:
        return DraftOutcome(template_draft(facts), "TEMPLATE", None)
    return DraftOutcome(result.output, "AI", result.ai_call_id)


_ATTACH = "UPDATE exceptions SET draft = $3::jsonb, draft_ai_call_id = $4 WHERE id = $1 AND org_id = $2 AND draft IS NULL"


def attach_draft(
    exception_id: uuid.UUID, org_id: uuid.UUID, outcome: DraftOutcome, *, database_url: str
) -> bool:
    """Store the draft once. False if the record is not in this organisation or already has a draft."""

    ai_call_id = None if outcome.ai_call_id is None else uuid.UUID(outcome.ai_call_id)
    payload = json.dumps({"source": outcome.source, "draft": outcome.draft.model_dump(mode="json")})

    async def run() -> bool:
        connection = await asyncpg.connect(_asyncpg_database_url(database_url))
        try:
            status = await connection.execute(_ATTACH, exception_id, org_id, payload, ai_call_id)
        finally:
            await connection.close()
        return bool(status == "UPDATE 1")

    return asyncio.run(run())
