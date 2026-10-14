"""Server-side construction of invoice approval signatures (INV-010).

The API routes and database approval lifecycle are implemented with INV-009 and
INV-010. This module is the single builder those routes should use; callers must
load the current request revision and chain configuration before invoking it.
"""

from __future__ import annotations

from typing import Any, Protocol, cast

from pydantic import TypeAdapter

from treasurypilot_api.invoices.models import RequestStatus
from treasurypilot_core.eip712 import payment_approval_typed_data
from treasurypilot_core.policy.context import Address, RequestView

# M05-D12: approval expiry is capped at deadline + 14 days.
_MAX_DEADLINE_GRACE_SECONDS = 14 * 24 * 60 * 60
# Mandate approvalMaxAge range (1-60 days), see mandate/configuration.py.
_MIN_APPROVAL_MAX_AGE = 86_400
_MAX_APPROVAL_MAX_AGE = 60 * 86_400
_UINT64_MAX = 2**64 - 1
# Pydantic accepts the PEP 695 alias at runtime; TypeAdapter's annotation still requires `type[T]`.
_ADDRESS: TypeAdapter[str] = TypeAdapter(cast(Any, Address))


class ApprovalExpiryError(ValueError):
    """The client-pinned approval expiry is outside the allowed window."""


class ApprovalChainReader(Protocol):
    """Read current module approval state and ERC-1271 signatures from the chain."""

    async def is_approver(self, *, chain_id: int, module: str, signer: str) -> bool: ...

    async def is_valid_erc1271_signature(
        self, *, chain_id: int, wallet: str, digest: bytes, signature: bytes
    ) -> bool: ...


def build_approval_typed_data(
    request: RequestView,
    *,
    chain_id: int,
    module_address: str,
    now: int,
    approval_max_age: int,
    asset: str,
    expiry: int | None = None,
) -> dict[str, object]:
    """Build exactly the contract's 13-field PaymentApproval for a current request.

    ``request_id`` must be the stable on-chain ID, not the database UUID. Early
    payment fields are already normalized and bound to the confirmed request
    terms by the invoice request service. ``expiry`` pins the signed expiry to the
    value issued by the typed-data endpoint; it must be in ``(now, cap]`` where
    ``cap = min(deadline + 14d, now + approval_max_age)``. Without it the cap is used.
    """
    if request.status != RequestStatus.AWAITING_APPROVAL:
        raise ValueError("request must be AwaitingApproval")
    if isinstance(now, bool) or now < 0:
        raise ValueError("now must be a non-negative Unix timestamp")
    if (
        isinstance(approval_max_age, bool)
        or not _MIN_APPROVAL_MAX_AGE <= approval_max_age <= _MAX_APPROVAL_MAX_AGE
    ):
        raise ValueError("approval_max_age must be between 1 and 60 days")
    if isinstance(chain_id, bool) or chain_id <= 0:
        raise ValueError("chain_id must be positive")
    if request.deadline <= 0:
        raise ValueError("request deadline must be positive")
    if request.early_amount > request.amount:
        raise ValueError("early_amount must not exceed amount")
    _ADDRESS.validate_python(module_address)
    _ADDRESS.validate_python(asset)

    cap = min(request.deadline + _MAX_DEADLINE_GRACE_SECONDS, now + approval_max_age)
    if cap <= now:
        raise ValueError("approval window has closed")
    if expiry is None:
        expiry = cap
    elif isinstance(expiry, bool) or not now < expiry <= cap:
        raise ApprovalExpiryError("expiry is outside the allowed approval window")
    if max(request.early_pay_by, request.deadline, expiry) > _UINT64_MAX:
        raise ValueError("timestamps must fit in uint64")

    message = {
        "requestId": "0x" + request.request_id.hex(),
        "invoiceHash": "0x" + request.invoice_hash.hex(),
        "fingerprint": "0x" + request.fingerprint.hex(),
        "treasury": module_address,
        "payingWallet": request.paying_wallet,
        "asset": asset,
        "payee": request.payee,
        "amount": str(request.amount),
        "earlyAmount": str(request.early_amount),
        "earlyPayBy": request.early_pay_by,
        "deadline": request.deadline,
        "termsHash": "0x" + request.terms_hash.hex(),
        "expiry": expiry,
    }
    return payment_approval_typed_data(
        message, chain_id=chain_id, verifying_contract=module_address
    )
