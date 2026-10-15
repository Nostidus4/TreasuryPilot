"""Read the persisted, signed execution steps for the live plan timeline."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Header, Request
from pydantic import Field
from sqlalchemy import exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.events.models import DomainEvent
from treasurypilot_api.events.writer import append_execution_cycle_requested
from treasurypilot_api.execution.models import (
    Attestation,
    ExecutionPlanStep,
    IndexStream,
    ObservedEvent,
    Operation,
    OperationStatus,
    Transaction,
    TransactionStatus,
)
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_member, require_role
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.mandate.models import (
    BackendPause,
    MandateVersion,
    MandateVersionStatus,
    Vendor,
)
from treasurypilot_api.treasury.models import Coverage, Treasury, TreasuryStatus
from treasurypilot_core.eip712 import PAY, REFILL, SUPPLY, SWAP_IN, WITHDRAW, plan_hash

logger = logging.getLogger(__name__)
_BASE_UNITS = re.compile(r"^(0|[1-9][0-9]*)$")

PlanStatus = Literal[
    "Proposed", "Validated", "Executing", "Completed", "PartiallyCompleted", "Rejected", "Unknown"
]
StepStatus = Literal[
    "Planned",
    "Submitted",
    "Pending",
    "Confirmed",
    "Verified",
    "Final",
    "Dropped",
    "Replaced",
    "Unknown",
    "Failed",
    "Skipped",
]
StepKind = Literal["REFILL", "PAY", "SUPPLY", "WITHDRAW", "SWAP"]
_ACTION_KIND: dict[int, StepKind] = {
    PAY: "PAY",
    REFILL: "REFILL",
    SWAP_IN: "SWAP",
    SUPPLY: "SUPPLY",
    WITHDRAW: "WITHDRAW",
}
_EVENT_ACTION = {
    "PAY": "PaymentExecuted",
    "REFILL": "RefillExecuted",
    "SUPPLY": "Supplied",
    "WITHDRAW": "Withdrawn",
}


class PlanView(ApiModel):
    id: uuid.UUID
    treasury_id: uuid.UUID
    created_at: datetime
    status: PlanStatus
    planner_source: Literal["AI", "RULE_BASED", "UNKNOWN"]
    expected_saving: str | None
    total_amount: str | None
    step_count: int


class PlanStepView(ApiModel):
    id: uuid.UUID
    index: int
    kind: StepKind
    title: str
    from_: str = Field(alias="from")
    to_: str = Field(alias="to")
    amount: str | None
    request_id: uuid.UUID | None
    reason: str
    status: StepStatus
    tx_hash: str | None
    confirmations: int | None
    verification: Literal["VERIFIED", "MISMATCH"] | None = None
    updated_at: datetime


class AttestationView(ApiModel):
    plan_hash: str
    signer: str
    signed_at: datetime


class PlanDetailView(PlanView):
    steps: list[PlanStepView]
    validations: list[dict[str, object]]
    binding_constraints: list[dict[str, str]]
    attestation: AttestationView


class PlanList(ApiModel):
    items: list[PlanView]


router = APIRouter(prefix="/v1", tags=["execution"])


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    factory = getattr(request.app.state, "request_sessions", None)
    if factory is None:
        raise AuthFailure(
            status=503,
            code="EXECUTION_UNAVAILABLE",
            title="Execution unavailable",
            detail="Execution storage is not configured.",
        )
    return cast(async_sessionmaker[AsyncSession], factory)


def _base_units(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return str(value)
    if isinstance(value, Decimal) and value >= 0 and value == value.to_integral_value():
        return str(int(value))
    if isinstance(value, str) and _BASE_UNITS.fullmatch(value):
        return value
    return None


def _address(value: object) -> str | None:
    if isinstance(value, bytes) and len(value) == 20:
        return "0x" + value.hex()
    if isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", value):
        return value
    return None


def _step_status(operation: Operation, transaction: Transaction | None) -> StepStatus:
    if transaction is not None:
        status = transaction.status.value
        if status == "Dropped":
            return "Replaced" if transaction.replaced_by_tx_id else "Dropped"
        if status == "Reverted":
            return "Failed"
        if status in {"Submitted", "Pending", "Confirmed", "Unknown"}:
            return cast(StepStatus, status)
    if operation.status.value == "NotSubmitted":
        return "Planned"
    if operation.status.value == "Abandoned":
        return "Skipped"
    if operation.status.value in {"Submitted", "Pending", "Confirmed", "Unknown"}:
        return cast(StepStatus, operation.status.value)
    if operation.status.value == "Reverted":
        return "Failed"
    return "Planned"


def _step_verification(
    step: ExecutionPlanStep,
    events: list[ObservedEvent],
) -> Literal["VERIFIED", "MISMATCH"] | None:
    """Compare the signed plan with the canonical module log for this transaction."""
    step_id = "0x" + step.step_id.hex()
    matches = [event for event in events if str(event.payload.get("stepId", "")).lower() == step_id]
    if not matches:
        return None
    if len(matches) != 1:
        return "MISMATCH"

    event = matches[0]
    kind = _ACTION_KIND.get(step.action)
    if kind is None:
        return "MISMATCH"
    expected_event = _EVENT_ACTION.get(kind)
    if expected_event is None:
        # No module event is currently mapped for swaps, so their signed fields
        # cannot be verified from the indexed event stream.
        return None
    if event.event_name != expected_event:
        return "MISMATCH"
    payload = event.payload
    expected_request = "0x" + step.request_id.hex()
    expected_to = "0x" + step.to_address.hex()
    expected_from = "0x" + step.from_address.hex()
    expected_amount = str(int(step.amount))
    amount_matches = str(payload.get("amount", "")) == expected_amount
    if kind == "PAY":
        return (
            "VERIFIED"
            if amount_matches
            and str(payload.get("requestId", "")).lower() == expected_request
            and str(payload.get("payingWallet", "")).lower() == expected_from
            and str(payload.get("payee", "")).lower() == expected_to
            else "MISMATCH"
        )
    if kind == "REFILL":
        return (
            "VERIFIED"
            if amount_matches
            and str(payload.get("requestId", "")).lower() == expected_request
            and str(payload.get("toWallet", "")).lower() == expected_to
            else "MISMATCH"
        )
    # Supply/withdraw module events carry an amount and step id, but no recipient.
    # A matching amount is not enough to assert the signed destination.
    if not amount_matches:
        return "MISMATCH"
    return None


# Supply, withdraw and swap steps never get a destination check (see _step_verification),
# so a confirmed transaction is as final as they can be.
_UNVERIFIABLE_KINDS = frozenset({"SUPPLY", "WITHDRAW", "SWAP"})


def _plan_status(steps: list[PlanStepView], expected_steps: int) -> PlanStatus:
    if len(steps) < expected_steps:
        return "Unknown"
    if all(step.status == "Planned" for step in steps):
        return "Proposed"

    def complete(step: PlanStepView) -> bool:
        return step.status == "Verified" or (
            step.status == "Confirmed" and step.kind in _UNVERIFIABLE_KINDS
        )

    if all(complete(step) for step in steps):
        return "Completed"
    # A confirmed PAY/REFILL without a verification result is still waiting for the indexer.
    if any(
        step.status in {"Planned", "Submitted", "Pending", "Unknown"}
        or (step.status == "Confirmed" and step.verification is None and not complete(step))
        for step in steps
    ):
        return "Executing"
    if any(complete(step) for step in steps) and all(
        complete(step) or step.status in {"Failed", "Skipped", "Dropped", "Replaced", "Final"}
        for step in steps
    ):
        return "PartiallyCompleted"
    return "Unknown"


def _total_amount(amounts: list[str | None], expected_steps: int) -> str | None:
    if not amounts or len(amounts) != expected_steps or any(amount is None for amount in amounts):
        return None
    return str(sum(int(amount) for amount in amounts if amount is not None))


async def _plan_detail(
    session: AsyncSession, *, organization_id: uuid.UUID, plan_id: uuid.UUID
) -> PlanDetailView:
    attestation = await session.scalar(
        select(Attestation)
        .where(Attestation.plan_id == plan_id)
        .order_by(Attestation.created_at.desc())
    )
    if attestation is None:
        raise _not_found()

    rows = (
        await session.execute(
            select(ExecutionPlanStep, Treasury)
            .join(Treasury, Treasury.module_address == ExecutionPlanStep.treasury_address)
            .where(
                ExecutionPlanStep.attestation_id == attestation.id,
                Treasury.chain_id == ExecutionPlanStep.chain_id,
                Treasury.org_id == organization_id,
            )
            .order_by(ExecutionPlanStep.seq)
        )
    ).all()
    if not rows or [row.step_id for row, _treasury in rows] != attestation.step_ids:
        raise _not_found()

    signed_steps = [row for row, _treasury in rows]
    treasury = rows[0][1]
    first_step = signed_steps[0]
    if any(
        step.plan_id != attestation.plan_id
        or step.chain_id != treasury.chain_id
        or step.request_id != first_step.request_id
        or step.treasury_address != first_step.treasury_address
        for step in signed_steps
    ):
        raise _not_found()
    treasury_candidates = (
        await session.scalars(
            select(Treasury).where(
                Treasury.chain_id == first_step.chain_id,
                Treasury.module_address == first_step.treasury_address,
            )
        )
    ).all()
    if len(treasury_candidates) != 1 or treasury_candidates[0].id != treasury.id:
        raise _not_found()
    plan = [
        {
            "seq": step.seq,
            "stepId": "0x" + step.step_id.hex(),
            "action": step.action,
            "from": "0x" + step.from_address.hex(),
            "to": "0x" + step.to_address.hex(),
            "asset": "0x" + step.asset_address.hex(),
            "amount": int(step.amount),
        }
        for step in signed_steps
    ]
    # The durable rows must still hash to the planHash that the signer attested.
    if (
        plan_hash(
            "0x" + signed_steps[0].request_id.hex(),
            "0x" + signed_steps[0].treasury_address.hex(),
            signed_steps[0].chain_id,
            plan,
        )
        != attestation.plan_hash
    ):
        raise _not_found()

    operations = (
        await session.execute(
            select(Operation, Vendor)
            .join(PaymentRequest, PaymentRequest.id == Operation.request_id, isouter=True)
            .outerjoin(Vendor, Vendor.id == PaymentRequest.vendor_id)
            .where(
                Operation.treasury_id == treasury.id,
                Operation.step_id.in_([step.step_id for step in signed_steps]),
            )
        )
    ).all()
    operations_by_step = {
        operation.step_id: (operation, vendor) for operation, vendor in operations
    }

    operation_ids = [operation.id for operation, _vendor in operations]
    transactions: list[Transaction] = []
    if operation_ids:
        transactions = list(
            (
                await session.scalars(
                    select(Transaction)
                    .where(
                        Transaction.operation_id.in_(operation_ids),
                        Transaction.chain_id == first_step.chain_id,
                    )
                    .order_by(Transaction.submitted_at.desc(), Transaction.id.desc())
                )
            ).all()
        )
    latest_transaction: dict[uuid.UUID, Transaction] = {}
    # Prefer the newest live transaction; a Dropped one only shows when nothing else exists.
    for transaction in sorted(transactions, key=lambda tx: tx.status.value == "Dropped"):
        latest_transaction.setdefault(transaction.operation_id, transaction)

    steps: list[PlanStepView] = []
    for signed_step in signed_steps:
        operation, vendor = operations_by_step.get(signed_step.step_id, (None, None))
        tx = latest_transaction.get(operation.id) if operation is not None else None
        kind = _ACTION_KIND.get(signed_step.action)
        if kind is None:
            raise _not_found()
        title = {
            "PAY": f"Pay {vendor.name if vendor else 'vendor'}",
            "REFILL": "Refill treasury reserve",
            "SUPPLY": "Supply treasury reserve",
            "WITHDRAW": "Withdraw treasury reserve",
            "SWAP": "Swap treasury assets",
        }[kind]
        event_rows: list[ObservedEvent] = []
        if tx is not None:
            event_rows = list(
                (
                    await session.scalars(
                        select(ObservedEvent)
                        .where(
                            ObservedEvent.treasury_id == treasury.id,
                            ObservedEvent.chain_id == signed_step.chain_id,
                            ObservedEvent.stream == IndexStream.MODULE,
                            ObservedEvent.removed.is_(False),
                            ObservedEvent.tx_hash == tx.tx_hash,
                        )
                        .order_by(ObservedEvent.block_number, ObservedEvent.log_index)
                    )
                ).all()
            )
        verification = _step_verification(signed_step, list(event_rows))
        status = _step_status(operation, tx) if operation is not None else "Planned"
        if status == "Confirmed" and verification == "VERIFIED":
            status = "Verified"
        updated_at = (
            tx.confirmed_at or tx.last_seen_pending_at or tx.submitted_at
            if tx is not None
            else operation.created_at
            if operation is not None
            else signed_step.created_at
        )
        steps.append(
            PlanStepView.model_validate(
                {
                    "id": operation.plan_step_id if operation is not None else signed_step.id,
                    "index": signed_step.seq + 1,
                    "kind": kind,
                    "title": title,
                    "from": _address(signed_step.from_address) or "Unavailable",
                    "to": _address(signed_step.to_address) or "Unavailable",
                    "amount": _base_units(signed_step.amount),
                    "request_id": operation.request_id if operation is not None else None,
                    "reason": "Expected fields come from the signed plan; live status uses persisted execution records.",
                    "status": status,
                    "tx_hash": ("0x" + tx.tx_hash.hex()) if tx is not None else None,
                    "confirmations": tx.confirmations if tx is not None else None,
                    "verification": verification,
                    "updated_at": updated_at,
                }
            )
        )
    steps.sort(key=lambda step: step.index)

    total_amount = _total_amount([step.amount for step in steps], len(attestation.step_ids))
    plan_status = _plan_status(steps, len(attestation.step_ids))
    return PlanDetailView(
        id=attestation.plan_id,
        treasury_id=treasury.id,
        created_at=attestation.created_at,
        status=plan_status,
        planner_source="UNKNOWN",
        expected_saving=None,
        total_amount=total_amount,
        step_count=len(attestation.step_ids),
        steps=steps,
        validations=[],
        binding_constraints=[],
        attestation=AttestationView(
            plan_hash="0x" + attestation.plan_hash.hex(),
            signer=attestation.policy_signer,
            signed_at=attestation.created_at,
        ),
    )


def _not_found() -> AuthFailure:
    return AuthFailure(
        status=404,
        code="PLAN_NOT_FOUND",
        title="Plan not found",
        detail="The plan does not exist or is not available to this organization.",
    )


@router.get(
    "/orgs/{organization_id}/treasuries/{treasury_id}/plans",
    response_model=PlanList,
    openapi_extra={"x-organization-scoped": True},
)
async def list_execution_plans(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_member)],
) -> PlanList:
    if member.organization_id != organization_id:
        raise _not_found()
    async with _sessions(request)() as session:
        plan_ids = (
            await session.scalars(
                select(Attestation.plan_id)
                .where(
                    exists().where(
                        ExecutionPlanStep.attestation_id == Attestation.id,
                        Treasury.module_address == ExecutionPlanStep.treasury_address,
                        Treasury.chain_id == ExecutionPlanStep.chain_id,
                        Treasury.org_id == organization_id,
                        Treasury.id == treasury_id,
                    )
                )
                .group_by(Attestation.plan_id)
                .order_by(func.max(Attestation.created_at).desc())
                .limit(100)
            )
        ).all()
        items: list[PlanView] = []
        for plan_id in plan_ids:
            try:
                detail = await _plan_detail(
                    session, organization_id=organization_id, plan_id=plan_id
                )
            except AuthFailure as failure:
                # One inconsistent plan must not hide the rest of the list.
                logger.warning("Skipping unreadable plan %s: %s", plan_id, failure.code)
                continue
            items.append(
                PlanView(
                    **detail.model_dump(
                        exclude={
                            "steps",
                            "validations",
                            "binding_constraints",
                            "attestation",
                        }
                    )
                )
            )
        return PlanList(items=items)


@router.get(
    "/orgs/{organization_id}/plans/{plan_id}",
    response_model=PlanDetailView,
    openapi_extra={"x-organization-scoped": True},
)
async def get_execution_plan(
    organization_id: uuid.UUID,
    plan_id: uuid.UUID,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_member)],
) -> PlanDetailView:
    if member.organization_id != organization_id:
        raise _not_found()
    async with _sessions(request)() as session:
        return await _plan_detail(session, organization_id=organization_id, plan_id=plan_id)


class RunNowResponse(ApiModel):
    job_id: uuid.UUID


# Operator or Owner (docs/modules/execution README, identity README).
_require_run_now = require_role(OrganizationRole.OPERATOR, OrganizationRole.OWNER)
_RUN_NOW_ENTITY = "RunNow"
_RUN_NOW_NAMESPACE = uuid.UUID("5d0a2c7e-3c3b-4c0a-9a43-1f1f6b7f0e48")


def _run_now_blocked(code: str, detail: str) -> AuthFailure:
    return AuthFailure(
        status=409, code=code, title=code.replace("_", " ").capitalize(), detail=detail
    )


async def _run_now_gate(session: AsyncSession, treasury: Treasury) -> None:
    """The scheduler's gates (worker trigger/cycles.py), mapped to API error codes.

    The order is deliberate: paused is checked first, so a paused treasury always says so.
    """
    paused = await session.scalar(
        select(BackendPause.paused).where(BackendPause.treasury_id == treasury.id)
    )
    if treasury.status is TreasuryStatus.PAUSED or paused:
        raise _run_now_blocked("TREASURY_PAUSED", "The treasury is paused.")
    if treasury.status is not TreasuryStatus.READY:
        raise _run_now_blocked("TREASURY_NOT_READY", "The treasury is not ready.")
    now = datetime.now(UTC)
    if not await session.scalar(
        select(
            exists().where(
                MandateVersion.treasury_id == treasury.id,
                MandateVersion.org_id == treasury.org_id,
                MandateVersion.status == MandateVersionStatus.ACTIVE,
                MandateVersion.valid_from <= now,
                MandateVersion.expires_at > now,
            )
        )
    ):
        raise _run_now_blocked("MANDATE_NOT_ACTIVE", "The treasury has no active mandate.")
    acknowledged = (
        treasury.coverage is Coverage.PARTIAL
        and treasury.coverage_ack_by is not None
        and treasury.coverage_ack_at is not None
        and bool((treasury.coverage_ack_reason or "").strip())
    )
    if treasury.coverage is not Coverage.COMPLETE and not acknowledged:
        raise _run_now_blocked("COVERAGE_INCOMPLETE", "Treasury coverage is incomplete.")
    if await session.scalar(
        select(
            exists().where(
                Operation.treasury_id == treasury.id,
                (Operation.status == OperationStatus.UNKNOWN)
                | exists().where(
                    Transaction.operation_id == Operation.id,
                    Transaction.status == TransactionStatus.UNKNOWN,
                ),
            )
        )
    ):
        raise _run_now_blocked("UNKNOWN_OPERATION_PENDING", "An operation has an unknown outcome.")
    executing = await session.scalar(
        select(
            exists().where(
                Operation.treasury_id == treasury.id,
                Operation.status.in_(
                    [
                        OperationStatus.NOT_SUBMITTED,
                        OperationStatus.SUBMITTED,
                        OperationStatus.PENDING,
                    ]
                ),
            )
        )
    ) or await session.scalar(
        text("SELECT EXISTS (SELECT 1 FROM plans WHERE treasury_id = :t AND status = 'Executing')"),
        {"t": treasury.id},
    )
    if executing:
        raise _run_now_blocked("EXECUTING_PLAN_EXISTS", "A plan is already executing.")


@router.post(
    "/orgs/{organization_id}/treasuries/{treasury_id}/run-now",
    response_model=RunNowResponse,
    status_code=202,
    openapi_extra={"x-organization-scoped": True},
)
async def run_now(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    request: Request,
    member: Annotated[MemberAccess, Depends(_require_run_now)],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=255)
    ] = None,
) -> RunNowResponse:
    """Enqueue one execution cycle through the outbox, behind the scheduler's gates."""
    if idempotency_key is None:
        raise AuthFailure(
            status=400,
            code="IDEMPOTENCY_KEY_REQUIRED",
            title="Idempotency key required",
            detail="Provide an Idempotency-Key for this run-now request.",
        )
    if member.organization_id != organization_id:
        raise _not_found_treasury()
    # One event per (treasury, key): its id is the job id, so a replay returns the same job.
    # Idempotency relies on the advisory lock below: domain_events has no unique constraint.
    entity_id = uuid.uuid5(_RUN_NOW_NAMESPACE, f"{treasury_id}:{idempotency_key}")
    async with _sessions(request)() as session, session.begin():
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": str(entity_id)}
        )
        treasury = await session.scalar(
            select(Treasury).where(Treasury.id == treasury_id, Treasury.org_id == organization_id)
        )
        if treasury is None:
            raise _not_found_treasury()
        existing = await session.scalar(
            select(DomainEvent.id).where(
                DomainEvent.org_id == organization_id,
                DomainEvent.entity_type == _RUN_NOW_ENTITY,
                DomainEvent.entity_id == entity_id,
            )
        )
        if existing is not None:
            return RunNowResponse(job_id=existing)
        await _run_now_gate(session, treasury)
        event = append_execution_cycle_requested(
            session,
            organization_id=organization_id,
            treasury_id=treasury_id,
            entity_type=_RUN_NOW_ENTITY,
            entity_id=entity_id,
        )
        await session.flush()
        return RunNowResponse(job_id=event.id)


def _not_found_treasury() -> AuthFailure:
    return AuthFailure(
        status=404,
        code="TREASURY_NOT_FOUND",
        title="Treasury not found",
        detail="The treasury does not exist or is not available to this organization.",
    )
