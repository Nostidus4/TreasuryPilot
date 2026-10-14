"""Deterministic composition of independent per-asset CP-SAT schedules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from treasurypilot_core.domain import (
    ApprovedRequest,
    Infeasible,
    PolicyView,
    Schedule,
    ScheduledItem,
    Snapshot,
)
from treasurypilot_core.engine.cpsat import schedule_cpsat


@dataclass(frozen=True, slots=True)
class AssetScheduleInput:
    """All scheduler state and requests for one asset, in that asset's base units.

    ``objective_value_scale`` converts the asset's native base-unit savings into a
    shared integer objective unit. Use the same target unit for every asset (for
    example, scale USDC's 10**6 base units by 10**12 to express values in 10**18
    units). This affects only the combined reported value; multiplying by a positive
    constant does not change the asset-local solver's ordering.
    """

    requests: Sequence[ApprovedRequest]
    snapshot: Snapshot
    policy: PolicyView
    objective_value_scale: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.objective_value_scale, bool)
            or not isinstance(self.objective_value_scale, int)
            or self.objective_value_scale <= 0
        ):
            raise ValueError("objective_value_scale must be a positive integer")


def schedule_cpsat_multi_asset(assets: Mapping[str, AssetScheduleInput]) -> Schedule:
    """Schedule independent assets and return one deterministically merged plan.

    Each asset is solved against its own source, operational-wallet balances, usage
    counters, and policy limits. No balance, budget, or counter is shared across assets.
    The objective terms are additive after each asset's value is converted to the shared
    objective unit specified by ``objective_value_scale``. Request IDs must be unique
    across the whole plan.
    """

    if not assets:
        return Schedule(
            items=(),
            infeasible=(),
            objective=(0, 0, 0, 0),
            binding=(),
            solver="CPSAT",
            status="OPTIMAL",
        )

    request_ids: set[str] = set()
    items: list[ScheduledItem] = []
    infeasible: list[Infeasible] = []
    objective = [0, 0, 0, 0]
    binding: set[str] = set()
    status: Literal["OPTIMAL", "FEASIBLE", "FALLBACK"] = "OPTIMAL"
    solvers: set[str] = set()
    sequence_by_id: dict[str, int] = {}

    for asset_id in sorted(assets):
        if not asset_id.strip():
            raise ValueError("asset ids must not be empty")
        asset = assets[asset_id]
        ids = [request.id for request in asset.requests]
        if len(ids) != len(set(ids)) or request_ids.intersection(ids):
            raise ValueError("request ids must be unique across all assets")
        request_ids.update(ids)
        sequence_by_id.update({request.id: request.approved_seq for request in asset.requests})

        result = schedule_cpsat(asset.requests, asset.snapshot, asset.policy)
        solvers.add(result.solver)
        items.extend(item.model_copy(update={"asset_id": asset_id}) for item in result.items)
        infeasible.extend(
            item.model_copy(update={"asset_id": asset_id}) for item in result.infeasible
        )
        for index, value in enumerate(result.objective):
            objective[index] += value * asset.objective_value_scale if index == 2 else value
        binding.update(result.binding)
        if result.status == "FALLBACK":
            status = "FALLBACK"
        elif result.status == "FEASIBLE" and status == "OPTIMAL":
            status = "FEASIBLE"

    items.sort(
        key=lambda item: (item.day, sequence_by_id[item.request_id], item.request_id, item.asset_id)
    )
    infeasible.sort(key=lambda item: item.request_id)
    return Schedule(
        items=tuple(items),
        infeasible=tuple(infeasible),
        objective=(objective[0], objective[1], objective[2], objective[3]),
        binding=tuple(sorted(binding)),
        solver="EDF" if solvers == {"EDF"} else "CPSAT",
        status=status,
    )
