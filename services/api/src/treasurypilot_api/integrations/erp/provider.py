"""The connector interface every ERP adapter implements (Xero, QuickBooks, NetSuite).

Contract, in short:
  * OAuth: ``authorize_url`` -> user consents -> ``exchange_code`` gives a ``TokenSet``
    and ``resolve_tenant`` names the ERP company; ``refresh`` rotates tokens. The framework
    encrypts and stores tokens; adapters never persist anything.
  * Export is idempotent: every create call carries ``idempotency_key`` and the adapter must
    first look for an existing object carrying the same ``reference`` and return that instead
    of creating a second one.
  * Bills are created as DRAFT only. Nothing here approves, authorises or posts a bill.
  * Payments reference an existing bill and carry the on-chain tx hash as the reference.
    ``bill_status`` lets the framework wait until a human has approved the bill in the ERP.
  * Errors: raise ``ErpTransientError`` (network, 429, 5xx; retried with backoff),
    ``ErpAuthError`` (401/403; the connection needs reauthorisation) or
    ``ErpPermanentError`` (validation; not retried until the data changes).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class ErpError(Exception):
    """Base class. Messages must never contain tokens or response bodies with PII."""


class ErpTransientError(ErpError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ErpAuthError(ErpError):
    pass


class ErpPermanentError(ErpError):
    pass


class BillState(StrEnum):
    DRAFT = "DRAFT"  # not yet approved by a human in the ERP
    APPROVED = "APPROVED"  # authorised in the ERP: payments may be applied
    PAID = "PAID"
    VOIDED = "VOIDED"  # voided or deleted: nothing may be applied


@dataclass(frozen=True, slots=True)
class TokenSet:
    access_token: str
    refresh_token: str
    expires_at: datetime
    scopes: str = ""
    # Set when the ERP names the company in the OAuth redirect (QuickBooks ``realmId``), so the
    # framework needs no ``resolve_tenant`` round trip.
    tenant_hint: str | None = None


@dataclass(frozen=True, slots=True)
class ErpTenant:
    tenant_id: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class ErpContext:
    """Per-call credentials, decrypted by the framework just before use."""

    tenant_id: str
    access_token: str


@dataclass(frozen=True, slots=True)
class ErpBill:
    """A reconciled payment request as a supplier bill. Amounts are integer minor units."""

    reference: str  # the invoice number; the natural idempotency anchor in the ERP
    idempotency_key: str
    vendor_name: str
    issue_date: date
    due_date: date
    currency: str  # ISO 4217
    amount_minor: int
    currency_decimals: int
    description: str
    expense_account_code: str


@dataclass(frozen=True, slots=True)
class ErpPayment:
    bill_reference: str
    idempotency_key: str
    paid_on: date
    currency: str
    amount_minor: int
    currency_decimals: int
    tx_hash: str  # 0x... shown as the payment reference in the ERP
    payment_account_code: str


@dataclass(frozen=True, slots=True)
class ErpObject:
    external_id: str
    status: str | None = None
    created: bool = True  # False when an existing object was found and reused


@dataclass(frozen=True, slots=True)
class BillStatus:
    state: BillState
    raw: str


@runtime_checkable
class ErpProvider(Protocol):
    key: str  # stable id used in URLs and the database: "xero", "quickbooks", "netsuite"
    display_name: str

    def authorize_url(self, state: str, redirect_uri: str) -> str: ...

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenSet: ...

    async def refresh(self, refresh_token: str) -> TokenSet: ...

    async def resolve_tenant(self, access_token: str) -> ErpTenant: ...

    async def create_draft_bill(self, ctx: ErpContext, bill: ErpBill) -> ErpObject: ...

    async def bill_status(self, ctx: ErpContext, external_id: str) -> BillStatus: ...

    async def create_payment(
        self, ctx: ErpContext, payment: ErpPayment, bill_external_id: str
    ) -> ErpObject: ...
