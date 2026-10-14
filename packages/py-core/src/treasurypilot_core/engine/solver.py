"""The scheduler interface shared by the EDF baseline, CP-SAT and the test oracle."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, Protocol

from treasurypilot_core.domain import ApprovedRequest, PolicyView, Schedule, Snapshot
from treasurypilot_core.engine.cpsat import schedule_cpsat
from treasurypilot_core.engine.scheduler import schedule_edf, schedule_oracle

type SolverName = Literal["EDF", "CPSAT", "ORACLE"]


class Solver(Protocol):
    """A scheduler: approved requests, a snapshot and a policy in, a ``Schedule`` out."""

    def __call__(
        self,
        requests: Sequence[ApprovedRequest],
        snapshot: Snapshot,
        policy: PolicyView,
    ) -> Schedule: ...


SOLVERS: Mapping[SolverName, Solver] = {
    "EDF": schedule_edf,
    "CPSAT": schedule_cpsat,
    "ORACLE": schedule_oracle,
}


def get_solver(name: SolverName) -> Solver:
    return SOLVERS[name]
