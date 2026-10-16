"""The model's tools: facts and simulations, nothing else (AI_AGENT_ARCHITECTURE §3).

Every tool is bound to one organisation when it is built; the organisation is never a model
input. Tools only read: they take a `ToolBackend` (no write method) and pure engine code. Never
add a tool with side effects (CONTRIBUTING).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from treasurypilot_core.domain import ApprovedRequest, PolicyView
from treasurypilot_core.domain import Snapshot as EngineSnapshot
from treasurypilot_core.engine import binding_constraints, schedule_edf
from treasurypilot_core.policy import REASON_CODES, Decision
from treasurypilot_worker.agent.errors import ToolError
from treasurypilot_worker.agent.tools.backend import (
    MAX_REQUESTS,
    OPEN_STATUSES,
    RequestRow,
    SnapshotRow,
    ToolBackend,
)
from treasurypilot_worker.agent.types import Tool
from treasurypilot_worker.agent.untrusted import SourceKind, UntrustedSource, wrap_untrusted

TOOL_NAMES = (
    "get_snapshot",
    "list_requests",
    "get_policy_summary",
    "simulate_schedule",
    "get_evidence",
    "explain_decision",
)
# Vendor and invoice text is data, not instructions (BR-070): short caps, wrapped.
_TEXT_CHARS = 200
_NOTE_CHARS = 500
_MANDATE_KEYS = (
    "actions",
    "refillPaths",
    "limits",
    "buffers",
    "validFrom",
    "expiresAt",
    "payeeCoolingSeconds",
    "supplyLimits",
    "minSupply",
    "reserveHorizonDays",
)

type RequestStatus = Literal[
    "AwaitingApproval",
    "Approved",
    "Scheduled",
    "Planning",
    "AwaitingAuthority",
    "Preparing",
    "Paying",
    "Paid",
    "NeedsReview",
]


class UnknownToolError(ValueError):
    """A tool name that is not in the allowlist, or whose data source is not wired."""


@dataclass(frozen=True)
class SimulationInputs:
    """What the engine needs for one treasury, built by the planner from stored state."""

    requests: tuple[ApprovedRequest, ...]
    snapshot: EngineSnapshot
    policy: PolicyView


# (org_id, treasury_id) -> inputs; None when the treasury is not the organisation's.
SimulationSource = Callable[[UUID, UUID], SimulationInputs | None]
# (org_id, validation_id) -> the stored validator decision; None when not the organisation's.
DecisionSource = Callable[[UUID, UUID], Decision | None]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TreasuryIn(_In):
    treasury_id: UUID


class ListRequestsIn(_In):
    treasury_id: UUID
    # Empty means every request still in play (not a draft, not terminal).
    statuses: list[RequestStatus] = Field(default_factory=list, max_length=len(OPEN_STATUSES) + 1)


class SimulateIn(_In):
    treasury_id: UUID
    defer: list[str] = Field(default_factory=list, max_length=50)
    day: int | None = Field(default=None, ge=0)


class EvidenceIn(_In):
    evidence_id: UUID


class ExplainIn(_In):
    validation_id: UUID


class SnapshotOut(_Out):
    snapshot_id: str
    evidence_id: str  # the id to cite: `snapshot:<snapshot_id>`
    block_number: int
    block_timestamp: str
    coverage: str
    data: dict[str, Any]


class RequestOut(_Out):
    id: str
    evidence_id: str  # the id to cite: `request:<id>`
    invoice_no: str | None
    vendor: str | None
    amount: str | None
    due_date: str
    status: str
    terms: dict[str, Any] | None
    flags: list[str]


class RequestsOut(_Out):
    requests: list[RequestOut]
    truncated: bool


class PayeeOut(_Out):
    label: str
    address: str
    status: str


class PolicyOut(_Out):
    evidence_id: str  # the id to cite: `policy:v<mandate_version>`
    mandate_version: int
    mandate: dict[str, Any]
    payees: list[PayeeOut]


class ScheduledOut(_Out):
    request_id: str
    day: int
    refill: str
    value: str


class InfeasibleOut(_Out):
    request_id: str
    reason: str
    detail: str


class BindingOut(_Out):
    name: str
    request_id: str
    day: int
    used: str
    limit: str


class SimulationOut(_Out):
    items: list[ScheduledOut]
    infeasible: list[InfeasibleOut]
    total_value: str
    binding_constraints: list[BindingOut]
    status: str


class EvidenceOut(_Out):
    kind: Literal["snapshot", "validation"]
    id: str
    evidence_id: str  # `snapshot:<id>` or `validation:<id>`
    summary: dict[str, Any]


class CheckOut(_Out):
    name: str
    passed: bool
    skipped: bool
    code: str | None
    expected: str | None
    observed: str | None


class DecisionOut(_Out):
    decision: str
    primary: str | None
    codes: list[str]
    warnings: list[str]
    checks: list[CheckOut]
    stage: str
    snapshot_block: int
    rules: dict[str, str]


def build_tools(
    backend: ToolBackend,
    org_id: str,
    *,
    simulation: SimulationSource | None = None,
    decisions: DecisionSource | None = None,
    only: Sequence[str] | None = None,
) -> tuple[Tool[Any], ...]:
    """The tools of one organisation, for `AiAdapter.run(tools=...)`.

    `simulate_schedule` and `explain_decision` need stored plans and validations that the
    planner owns, so they exist only when their source is passed. `only` narrows the set and
    raises `UnknownToolError` for a name that is not offered.
    """

    org = UUID(org_id)

    def own(treasury_id: UUID) -> None:
        # Same words for "missing" and "someone else's": a refusal leaks nothing.
        if not backend.treasury_in_org(org, treasury_id):
            raise ToolError("REFUSED: treasury not found in this organisation")

    def get_snapshot(args: TreasuryIn) -> SnapshotOut:
        own(args.treasury_id)
        row = backend.latest_complete_snapshot(org, args.treasury_id)
        if row is None:
            raise ToolError("NO_COMPLETE_SNAPSHOT: no snapshot with COMPLETE coverage exists")
        # Owners and modules of the Safes stay out: the plan does not need them.
        data = {key: value for key, value in row.data.items() if key != "safes"}
        return SnapshotOut(
            snapshot_id=str(row.id),
            evidence_id=f"snapshot:{row.id}",
            block_number=row.block_number,
            block_timestamp=row.block_timestamp.isoformat(),
            coverage=row.coverage,
            data=data,
        )

    def list_requests(args: ListRequestsIn) -> RequestsOut:
        own(args.treasury_id)
        rows = backend.list_requests(org, args.treasury_id, args.statuses or OPEN_STATUSES)
        return RequestsOut(
            requests=[_request(row) for row in rows[:MAX_REQUESTS]],
            truncated=len(rows) > MAX_REQUESTS,
        )

    def get_policy_summary(args: TreasuryIn) -> PolicyOut:
        own(args.treasury_id)
        row = backend.active_policy(org, args.treasury_id)
        if row is None:
            raise ToolError("NO_ACTIVE_MANDATE: the treasury has no active mandate")
        return PolicyOut(
            evidence_id=f"policy:v{row.mandate_version}",
            mandate_version=row.mandate_version,
            mandate={key: row.config[key] for key in _MANDATE_KEYS if key in row.config},
            payees=[
                PayeeOut(
                    label=_untrusted(SourceKind.VENDOR, p.id, p.label, _TEXT_CHARS),
                    address=f"{p.address[:6]}...{p.address[-4:]}",
                    status=p.status,
                )
                for p in row.payees
            ],
        )

    def simulate_schedule(args: SimulateIn) -> SimulationOut:
        own(args.treasury_id)
        inputs = simulation(org, args.treasury_id) if simulation else None
        if inputs is None:
            raise ToolError("NO_SIMULATION_INPUTS: this treasury cannot be simulated now")
        known = {request.id for request in inputs.requests}
        if unknown := sorted(set(args.defer) - known):
            raise ToolError(f"UNKNOWN_REQUEST: {unknown} are not schedulable requests")
        snapshot = inputs.snapshot
        if args.day is not None:
            if args.day < snapshot.day:
                raise ToolError(f"INVALID_DAY: day must be at least {snapshot.day}")
            snapshot = snapshot.model_copy(update={"day": args.day})
        requests = tuple(r for r in inputs.requests if r.id not in args.defer)
        schedule = schedule_edf(requests, snapshot, inputs.policy)
        details = binding_constraints(schedule, requests, snapshot, inputs.policy)
        return SimulationOut(
            items=[
                ScheduledOut(
                    request_id=i.request_id, day=i.day, refill=str(i.refill), value=str(i.value)
                )
                for i in schedule.items
            ],
            infeasible=[
                InfeasibleOut(request_id=i.request_id, reason=i.reason, detail=i.detail)
                for i in schedule.infeasible
            ],
            total_value=str(sum(i.value for i in schedule.items)),
            binding_constraints=[
                BindingOut(
                    name=d.name,
                    request_id=d.request_id,
                    day=d.day,
                    used=str(d.used),
                    limit=str(d.limit),
                )
                for d in details
            ],
            status=schedule.status,
        )

    def get_evidence(args: EvidenceIn) -> EvidenceOut:
        snapshot = backend.snapshot_by_id(org, args.evidence_id)
        if snapshot is not None:
            return _snapshot_evidence(snapshot)
        decision = decisions(org, args.evidence_id) if decisions else None
        if decision is None:
            raise ToolError("REFUSED: evidence not found in this organisation")
        return EvidenceOut(
            kind="validation",
            id=str(args.evidence_id),
            evidence_id=f"validation:{args.evidence_id}",
            summary={
                "decision": decision.decision,
                "primary": decision.primary,
                "stage": decision.stage,
                "snapshot_block": decision.snapshot_block,
            },
        )

    def explain_decision(args: ExplainIn) -> DecisionOut:
        decision = decisions(org, args.validation_id) if decisions else None
        if decision is None:
            raise ToolError("REFUSED: validation not found in this organisation")
        codes = [*decision.codes, *decision.warnings]
        return DecisionOut(
            decision=decision.decision,
            primary=decision.primary,
            codes=[str(c) for c in decision.codes],
            warnings=[str(c) for c in decision.warnings],
            checks=[
                CheckOut(
                    name=c.name,
                    passed=c.passed,
                    skipped=c.skipped,
                    code=None if c.code is None else str(c.code),
                    expected=c.expected,
                    observed=c.observed,
                )
                for c in decision.checks
            ],
            stage=decision.stage,
            snapshot_block=decision.snapshot_block,
            rules={str(c): REASON_CODES[c].rules for c in codes},
        )

    offered: dict[str, Tool[Any]] = {
        "get_snapshot": Tool(
            "get_snapshot",
            "Latest COMPLETE chain snapshot of a treasury: balances, buffers, targets, "
            "today's usage counters, mandate state and the block it was read at.",
            TreasuryIn,
            get_snapshot,
        ),
        "list_requests": Tool(
            "list_requests",
            "Payment requests of a treasury (amounts in base units as strings, due dates, "
            "confirmed terms, open flag codes). Vendor text comes wrapped as untrusted data.",
            ListRequestsIn,
            list_requests,
        ),
        "get_policy_summary": Tool(
            "get_policy_summary",
            "Active mandate limits, buffers, refill paths and payees (label and short address).",
            TreasuryIn,
            get_policy_summary,
        ),
        "get_evidence": Tool(
            "get_evidence",
            "Stored evidence record (snapshot or validation excerpt) by id.",
            EvidenceIn,
            get_evidence,
        ),
    }
    if simulation is not None:
        offered["simulate_schedule"] = Tool(
            "simulate_schedule",
            "Pure what-if run of the deterministic scheduler: optionally defer request ids "
            "or move the day. Returns the feasible schedule, value and binding constraints. "
            "Nothing is stored or executed.",
            SimulateIn,
            simulate_schedule,
        )
    if decisions is not None:
        offered["explain_decision"] = Tool(
            "explain_decision",
            "Validator reason codes and checks of a stored validation, with the rule of each.",
            ExplainIn,
            explain_decision,
        )

    names = TOOL_NAMES if only is None else tuple(only)
    missing = [name for name in names if name not in offered]
    if only is not None and missing:
        raise UnknownToolError(f"unknown or unwired tools: {missing}")
    return tuple(offered[name] for name in TOOL_NAMES if name in offered and name in names)


def _untrusted(kind: SourceKind, ref: object, text: str, max_chars: int) -> str:
    return wrap_untrusted(UntrustedSource(kind, str(ref)), text, max_chars=max_chars).render()


def _request(row: RequestRow) -> RequestOut:
    terms = None if row.terms is None else dict(row.terms)
    if terms is not None and isinstance(terms.get("priority_note"), str):
        terms["priority_note"] = _untrusted(
            SourceKind.TERMS, row.id, terms["priority_note"], _NOTE_CHARS
        )
    return RequestOut(
        id=str(row.id),
        evidence_id=f"request:{row.id}",
        invoice_no=(
            None
            if row.invoice_no is None
            else _untrusted(SourceKind.INVOICE, row.id, row.invoice_no, _TEXT_CHARS)
        ),
        vendor=(
            None
            if row.vendor_name is None
            else _untrusted(SourceKind.VENDOR, row.id, row.vendor_name, _TEXT_CHARS)
        ),
        amount=None if row.amount is None else str(row.amount),
        due_date=row.due_at.isoformat(),
        status=row.status,
        terms=terms,
        flags=list(row.flags),
    )


def _snapshot_evidence(row: SnapshotRow) -> EvidenceOut:
    return EvidenceOut(
        kind="snapshot",
        id=str(row.id),
        evidence_id=f"snapshot:{row.id}",
        summary={
            "treasury_id": str(row.treasury_id),
            "purpose": row.purpose,
            "block_number": row.block_number,
            "block_hash": row.block_hash,
            "block_timestamp": row.block_timestamp.isoformat(),
            "coverage": row.coverage,
            "missing": list(row.missing),
        },
    )
