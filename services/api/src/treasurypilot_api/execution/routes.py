"""Read the persisted, signed execution steps for the live plan timeline."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import any_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.execution.models import (
    Attestation,
    Operation,
    Transaction,
    TransactionCrosscheck,
)
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.mandate.models import Payee, Vendor
from treasurypilot_api.treasury.models import Treasury

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


def _step_amount(operation: Operation) -> str | None:
    # Use the signed operation payload, never the invoice face value: a confirmed
    # partial payment may differ from the request amount. Missing amounts stay unavailable.
    payload = operation.payload
    return _base_units(payload.get("amountBaseUnits", payload.get("amount")))


def _step_verification(
    crosscheck: TransactionCrosscheck | None,
) -> Literal["VERIFIED", "MISMATCH"] | None:
    if crosscheck is TransactionCrosscheck.MATCH:
        return "VERIFIED"
    if crosscheck is TransactionCrosscheck.MISMATCH:
        return "MISMATCH"
    return None


def _plan_status(statuses: list[StepStatus], expected_steps: int) -> PlanStatus:
    if len(statuses) < expected_steps:
        return "Unknown"
    if any(status in {"Submitted", "Pending", "Unknown"} for status in statuses):
        return "Executing"
    if statuses and all(status == "Planned" for status in statuses):
        return "Proposed"
    # Confirmed receipts are not proof that the signed plan was paid as intended;
    # terminal failures likewise cannot be aggregated without persisted plan state.
    return "Unknown"


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
            select(Operation, PaymentRequest, Vendor, Payee)
            .join(Treasury, Treasury.id == Operation.treasury_id)
            .join(PaymentRequest, PaymentRequest.id == Operation.request_id)
            .outerjoin(Vendor, Vendor.id == PaymentRequest.vendor_id)
            .outerjoin(Payee, Payee.id == PaymentRequest.payee_id)
            .where(
                Treasury.org_id == organization_id,
                Operation.step_id.in_(attestation.step_ids),
            )
        )
    ).all()
    if not rows:
        raise _not_found()

    operation_ids = [operation.id for operation, *_ in rows]
    transactions = (
        await session.scalars(
            select(Transaction)
            .where(Transaction.operation_id.in_(operation_ids))
            .order_by(Transaction.submitted_at.desc(), Transaction.id.desc())
        )
    ).all()
    latest_transaction: dict[uuid.UUID, Transaction] = {}
    for transaction in transactions:
        latest_transaction.setdefault(transaction.operation_id, transaction)

    step_order = {step_id: index for index, step_id in enumerate(attestation.step_ids, start=1)}
    steps: list[PlanStepView] = []
    for operation, _payment_request, vendor, payee in rows:
        tx = latest_transaction.get(operation.id)
        kind = operation.kind.value
        amount = _step_amount(operation)
        payload = operation.payload
        title = {
            "PAY": f"Pay {vendor.name if vendor else 'vendor'}",
            "REFILL": "Refill treasury reserve",
            "SUPPLY": "Supply treasury reserve",
            "WITHDRAW": "Withdraw treasury reserve",
            "SWAP": "Swap treasury assets",
        }[kind]
        to_address = _address(payee.address) if kind == "PAY" and payee else None
        to_address = to_address or _address(payload.get("to")) or "Unavailable"
        from_address = _address(payload.get("from")) or "Treasury"
        updated_at = (
            tx.confirmed_at or tx.last_seen_pending_at or tx.submitted_at
            if tx is not None
            else operation.created_at
        )
        steps.append(
            PlanStepView.model_validate(
                {
                    "id": operation.plan_step_id,
                    "index": step_order.get(operation.step_id, len(steps) + 1),
                    "kind": kind,
                    "title": title,
                    "from": from_address,
                    "to": to_address,
                    "amount": amount,
                    "request_id": operation.request_id,
                    "reason": "Live status comes from the persisted operation and transaction records.",
                    "status": _step_status(operation, tx),
                    "tx_hash": ("0x" + tx.tx_hash.hex()) if tx is not None else None,
                    "confirmations": tx.confirmations if tx is not None else None,
                    "verification": _step_verification(tx.crosscheck if tx is not None else None),
                    "updated_at": updated_at,
                }
            )
        )
    steps.sort(key=lambda step: step.index)

    total_amount = (
        str(sum(int(step.amount or "0") for step in steps))
        if steps and all(step.amount is not None for step in steps)
        else None
    )
    first_operation = min((row[0] for row in rows), key=lambda item: item.created_at)
    status = _plan_status([step.status for step in steps], len(attestation.step_ids))
    return PlanDetailView(
        id=attestation.plan_id,
        treasury_id=first_operation.treasury_id,
        created_at=attestation.created_at,
        status=status,
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
        plans = (
            await session.scalars(
                select(Attestation)
                .join(Operation, Operation.step_id == any_(Attestation.step_ids))
                .join(Treasury, Treasury.id == Operation.treasury_id)
                .where(
                    Treasury.org_id == organization_id,
                    Treasury.id == treasury_id,
                )
                .order_by(Attestation.created_at.desc())
                .limit(100)
            )
        ).all()
        seen: set[uuid.UUID] = set()
        items: list[PlanView] = []
        for attestation in plans:
            if attestation.plan_id in seen:
                continue
            seen.add(attestation.plan_id)
            detail = await _plan_detail(
                session, organization_id=organization_id, plan_id=attestation.plan_id
            )
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
