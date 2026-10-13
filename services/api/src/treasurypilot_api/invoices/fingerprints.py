"""Shared fingerprint persistence and active duplicate checks for payment requests."""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from treasurypilot_api.invoices.models import (
    TERMINAL_REQUEST_STATUSES,
    PaymentRequest,
)
from treasurypilot_api.mandate.models import Vendor
from treasurypilot_api.treasury.models import Asset, Treasury
from treasurypilot_core.fingerprint import fingerprint
from treasurypilot_core.money import BaseUnits


class DuplicateFingerprintConflict(Exception):
    """An active request in the same treasury already uses this fingerprint."""

    status_code = 409
    code = "DUPLICATE_FINGERPRINT"

    def __init__(self, existing_request_id: uuid.UUID) -> None:
        self.existing_request_id = existing_request_id
        self.existingRequestId = existing_request_id
        self.detail = "An active payment request already uses this invoice fingerprint."
        super().__init__(self.detail)


class DuplicateAllowance(Protocol):
    """Checks an Owner's on-chain allowance for exactly one request and fingerprint."""

    async def allows(
        self,
        *,
        session: AsyncSession,
        request_id: uuid.UUID,
        fingerprint: bytes,
    ) -> bool: ...


class DenyDuplicateAllowance:
    async def allows(
        self,
        *,
        session: AsyncSession,
        request_id: uuid.UUID,
        fingerprint: bytes,
    ) -> bool:
        return False


async def request_fingerprint(session: AsyncSession, request: PaymentRequest) -> bytes:
    """Recompute the canonical fingerprint from the request's current bound fields."""
    vendor_ref, asset_address = (
        await session.execute(
            select(Vendor.normalized_ref, Asset.address)
            .join(Asset, Asset.id == request.asset_id)
            .where(Vendor.id == request.vendor_id)
        )
    ).one()
    if asset_address is None or len(asset_address) != 20:
        raise ValueError("Invoice fingerprints require an ERC-20 asset address.")
    value = fingerprint(
        vendor_ref,
        request.invoice_no,
        BaseUnits(int(request.amount)),
        "0x" + asset_address.hex(),
    )
    request.fingerprint = value
    return value


async def find_active_duplicate(
    session: AsyncSession,
    *,
    treasury_id: uuid.UUID,
    value: bytes,
    exclude_request_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Find a matching request in this treasury, ignoring terminal requests."""
    query = select(PaymentRequest.id).where(
        PaymentRequest.treasury_id == treasury_id,
        PaymentRequest.fingerprint == value,
        PaymentRequest.status.not_in(
            [status.value for status in TERMINAL_REQUEST_STATUSES]
        ),
    )
    if exclude_request_id is not None:
        query = query.where(PaymentRequest.id != exclude_request_id)
    return await session.scalar(query.order_by(PaymentRequest.id).limit(1))


async def assert_no_active_duplicate(
    session: AsyncSession,
    request: PaymentRequest,
    *,
    allowance: DuplicateAllowance | None = None,
) -> bytes:
    """Refresh and check a request's fingerprint inside its current transaction.

    Locking the treasury serializes create, edit and submit checks for that
    treasury. The partial unique index remains the final safeguard for writers
    that do not use this service.
    """
    await session.scalar(
        select(Treasury.id)
        .where(Treasury.id == request.treasury_id)
        .with_for_update()
    )
    value = await request_fingerprint(session, request)
    existing_id = await find_active_duplicate(
        session,
        treasury_id=request.treasury_id,
        value=value,
        exclude_request_id=request.id,
    )
    if existing_id is not None:
        effective_allowance = allowance or DenyDuplicateAllowance()
        if not await effective_allowance.allows(
            session=session,
            request_id=request.id,
            fingerprint=value,
        ):
            raise DuplicateFingerprintConflict(existing_id)
    return value
