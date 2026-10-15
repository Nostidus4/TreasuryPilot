"""The AI client of the planning pipeline: typed errors, no exception crosses the queue."""

import asyncio
import uuid
from typing import Any

import pytest

from treasurypilot_worker.agent.errors import AiBudgetExceeded, AiTimeout, AiUnavailable
from treasurypilot_worker.agent.plan_proposer import PlanProposal, PlanProposalRejected
from treasurypilot_worker.planner.ai import CeleryAiProposer, outcome_from_payload

CALL = str(uuid.uuid4())


def _propose(call: Any) -> Any:
    client = CeleryAiProposer(call)
    return asyncio.run(
        client.propose(org_id=uuid.uuid4(), treasury_id=uuid.uuid4(), eligible_ids=("a",))
    )


def test_proposal_payload_round_trips() -> None:
    payload = {
        "proposal": {
            "request_order": ["a"],
            "rationale": [{"claim": "due first", "evidence_ids": ["snap"]}],
        },
        "ai_call_id": CALL,
    }
    outcome = outcome_from_payload(payload)
    assert isinstance(outcome.result, PlanProposal) and str(outcome.ai_call_id) == CALL


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"error": "PLAN_REJECTED", "detail": "x"}, PlanProposalRejected),
        ({"error": "AI_TIMEOUT"}, AiTimeout),
        ({"error": "AI_BUDGET_EXCEEDED"}, AiBudgetExceeded),
        ({"error": "AI_UNAVAILABLE"}, AiUnavailable),
        ({"error": "SOMETHING_NEW"}, AiUnavailable),
    ],
)
def test_error_codes_map_to_typed_errors(payload: dict[str, str], error: type[Exception]) -> None:
    assert isinstance(outcome_from_payload(payload).result, error)


def test_timeout_and_transport_failures_are_outages() -> None:
    def timeout(_: dict[str, Any]) -> dict[str, Any]:
        raise TimeoutError

    def broker_down(_: dict[str, Any]) -> dict[str, Any]:
        raise ConnectionError

    assert isinstance(_propose(timeout).result, AiTimeout)
    assert isinstance(_propose(broker_down).result, AiUnavailable)
