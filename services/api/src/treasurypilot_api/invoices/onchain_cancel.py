"""Confirm an on-chain request cancellation from an observed `RequestCancelled` event (BR-077)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from treasurypilot_api.audit.models import AuditActorType
from treasurypilot_api.audit.writer import AuditActor, AuditEntity
from treasurypilot_api.audit.writer import write as write_audit
from treasurypilot_api.invoices.models import CancelOnchainStatus, PaymentRequest
from treasurypilot_api.treasury.models import Treasury


async def confirm_onchain_cancel(
    session: AsyncSession, *, module_address: bytes, request_id: bytes, tx_hash: bytes
) -> bool:
    """Move a Pending cancellation to Confirmed; the caller commits.

    Called by the chain event indexer (CHN-005) for each observed `RequestCancelled`, scoped by
    the emitting module so a request id from another treasury's module cannot match. Replays and
    events for requests that owe no on-chain cancel return False without changing anything.
    """
    row = await session.scalar(
        select(PaymentRequest)
        .join(Treasury, Treasury.id == PaymentRequest.treasury_id)
        .where(
            Treasury.module_address == module_address,
            PaymentRequest.onchain_request_id == request_id,
            PaymentRequest.cancel_onchain == CancelOnchainStatus.PENDING.value,
        )
        .with_for_update(of=PaymentRequest)
    )
    if row is None:
        return False
    row.cancel_onchain = CancelOnchainStatus.CONFIRMED.value
    row.cancel_tx_hash = tx_hash
    await write_audit(
        session,
        org_id=row.org_id,
        actor=AuditActor(AuditActorType.CONTRACT, "0x" + module_address.hex()),
        action="request.cancel_onchain_confirmed",
        entity=AuditEntity("payment_request", row.id),
        data={"txHash": "0x" + tx_hash.hex()},
    )
    return True
