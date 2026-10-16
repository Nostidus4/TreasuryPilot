"""Read-only tools the model may call for one scenario.

They serve the scenario's *inputs* as the planner sees them after B1's liquidity action (the
same state B2 is scored on). Results are built from engine objects, so nothing from the
`expected*` ground truth can reach the model (M09-D14).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from treasurypilot_worker.agent.errors import ToolError
from treasurypilot_worker.agent.types import Tool
from treasurypilot_worker.planner_bench.arms import Position
from treasurypilot_worker.planner_bench.scenarios import Scenario


class _TreasuryIn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    treasury_id: str


def build_tools(scenario: Scenario, position: Position) -> tuple[Tool[Any], ...]:
    """Tools bound to one scenario; asking for another treasury is refused."""

    def check(args: _TreasuryIn) -> None:
        if args.treasury_id != scenario.id:
            raise ToolError("REFUSED: treasury not found in this organisation")

    def get_snapshot(args: _TreasuryIn) -> dict[str, Any]:
        check(args)
        return {
            "snapshot_id": f"snapshot:{scenario.id}",
            "evidence_id": f"snapshot:{scenario.id}",
            "as_of": scenario.as_of.isoformat(),
            "horizon_days": scenario.horizon_days,
            "day_numbers": "UTC days since 1970-01-01; amounts are integer base units",
            "data": position.snapshot.model_dump(mode="json"),
        }

    def list_requests(args: _TreasuryIn) -> dict[str, Any]:
        check(args)
        return {
            "requests": [
                {**r.model_dump(mode="json"), "evidence_id": f"request:{r.id}"}
                for r in scenario.requests
            ],
            "truncated": False,
        }

    def get_policy_summary(args: _TreasuryIn) -> dict[str, Any]:
        check(args)
        return {
            "evidence_id": f"policy:{scenario.id}",
            "policy": scenario.policy.model_dump(mode="json"),
        }

    return (
        Tool(
            "get_snapshot", "Balances, buffers, usage and payee state.", _TreasuryIn, get_snapshot
        ),
        Tool("list_requests", "Approved requests with their terms.", _TreasuryIn, list_requests),
        Tool("get_policy_summary", "Pay and refill limits.", _TreasuryIn, get_policy_summary),
    )
