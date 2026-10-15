"""The AI half of the planning pipeline: the `ai`-queue proposal and the core-side client."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Sequence
from typing import Any

from celery.exceptions import TimeoutError as CeleryTimeoutError

from treasurypilot_worker.agent.adapter import AiAdapter
from treasurypilot_worker.agent.errors import (
    AiBudgetExceeded,
    AiError,
    AiInputRejected,
    AiSchemaError,
    AiTimeout,
    AiToolLimitExceeded,
    AiUnavailable,
)
from treasurypilot_worker.agent.plan_proposer import (
    PlanProposal,
    PlanProposalRejected,
    propose_plan,
)
from treasurypilot_worker.agent.tools.read_only import build_tools
from treasurypilot_worker.planner.pipeline import AiOutcome

PROPOSE_TASK = "treasurypilot.planning.propose"
_ERRORS: dict[str, Callable[[], AiError]] = {
    "AI_TIMEOUT": lambda: AiTimeout("AI proposal timed out"),
    "AI_BUDGET_EXCEEDED": lambda: AiBudgetExceeded("AI budget exceeded"),
    "AI_SCHEMA": lambda: AiSchemaError("AI proposal failed its schema"),
    "AI_TOOL_LIMIT": lambda: AiToolLimitExceeded("AI used too many tools"),
}


def run_proposal(
    adapter: AiAdapter,
    backend: Any,
    *,
    org_id: str,
    treasury_id: str,
    eligible_ids: Sequence[str],
) -> dict[str, Any]:
    """Body of the `ai` task. No exception crosses Celery: failures come back as a code."""

    try:
        result = propose_plan(
            adapter,
            org_id=org_id,
            treasury_id=treasury_id,
            eligible_request_ids=eligible_ids,
            tools=build_tools(backend, org_id),
        )
    except (PlanProposalRejected, AiInputRejected) as error:
        return {"error": "PLAN_REJECTED", "detail": str(error)}
    except AiTimeout:
        return {"error": "AI_TIMEOUT"}
    except AiBudgetExceeded:
        return {"error": "AI_BUDGET_EXCEEDED"}
    except AiSchemaError:
        return {"error": "AI_SCHEMA"}
    except AiToolLimitExceeded:
        return {"error": "AI_TOOL_LIMIT"}
    except AiError:
        return {"error": "AI_UNAVAILABLE"}
    return {"proposal": result.output.model_dump(mode="json"), "ai_call_id": result.ai_call_id}


def outcome_from_payload(payload: dict[str, Any]) -> AiOutcome:
    if "proposal" in payload:
        call_id = payload.get("ai_call_id")
        return AiOutcome(
            PlanProposal.model_validate(payload["proposal"]),
            uuid.UUID(call_id) if call_id else None,
        )
    code = payload.get("error", "AI_UNAVAILABLE")
    if code == "PLAN_REJECTED":
        return AiOutcome(PlanProposalRejected(payload.get("detail", "proposal rejected")))
    make = _ERRORS.get(code, lambda: AiUnavailable("AI worker unavailable", retryable=False))
    return AiOutcome(make())


class CeleryAiProposer:
    """Ask the `ai` queue for a proposal; any timeout or transport failure is an outage."""

    def __init__(self, call: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        # `call` blocks for at most the proposal timeout (BR-055: 20 s) and raises on expiry.
        self._call = call

    async def propose(
        self, *, org_id: uuid.UUID, treasury_id: uuid.UUID, eligible_ids: tuple[str, ...]
    ) -> AiOutcome:
        request = {
            "org_id": str(org_id),
            "treasury_id": str(treasury_id),
            "eligible_ids": list(eligible_ids),
        }
        try:
            payload = await asyncio.to_thread(self._call, request)
        except (TimeoutError, CeleryTimeoutError):
            return AiOutcome(AiTimeout("AI proposal timed out"))
        except Exception:  # broker or backend down: the deterministic path must still run
            return AiOutcome(AiUnavailable("AI queue unavailable", retryable=False))
        return outcome_from_payload(payload)
