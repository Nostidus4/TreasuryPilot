"""Xero adapter over the documented OAuth 2.0 and Accounting API (developer.xero.com).

Bills are created as ``ACCPAY`` invoices with ``Status: DRAFT``; this adapter has no call
that authorises (approves) an invoice. Payments are applied to a bill only once a human has
authorised it in Xero. Idempotency: ``Idempotency-Key`` header plus a lookup by invoice number
(bills) or payment reference (payments) before any create.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlencode

from treasurypilot_api.integrations.erp.http import (
    HttpClient,
    HttpRequest,
    HttpResponse,
    HttpTransportError,
)
from treasurypilot_api.integrations.erp.provider import (
    BillState,
    BillStatus,
    ErpAuthError,
    ErpBill,
    ErpContext,
    ErpObject,
    ErpPayment,
    ErpPermanentError,
    ErpTenant,
    ErpTransientError,
    TokenSet,
)

AUTHORIZE_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"  # noqa: S105 - public endpoint
CONNECTIONS_URL = "https://api.xero.com/connections"
API_BASE = "https://api.xero.com/api.xro/2.0"
SCOPES = "offline_access accounting.transactions accounting.contacts"

_STATE_MAP = {
    "DRAFT": BillState.DRAFT,
    "SUBMITTED": BillState.DRAFT,
    "AUTHORISED": BillState.APPROVED,
    "PAID": BillState.PAID,
    "VOIDED": BillState.VOIDED,
    "DELETED": BillState.VOIDED,
}


def _amount(minor: int, decimals: int) -> float:
    # Decimal -> float keeps the shortest round-trip repr (1234.56 stays 1234.56).
    return float(Decimal(minor).scaleb(-decimals))


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class XeroProvider:
    key = "xero"
    display_name = "Xero"

    def __init__(
        self,
        http: HttpClient,
        *,
        client_id: str,
        client_secret: str,
        now: Any = None,
    ) -> None:
        self._http = http
        self._client_id = client_id
        self._client_secret = client_secret
        self._now = now or (lambda: datetime.now(UTC))

    # --- OAuth ---------------------------------------------------------------------------

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "scope": SCOPES,
                "state": state,
            },
            quote_via=quote,
        )
        return f"{AUTHORIZE_URL}?{query}"

    def _basic(self) -> str:
        raw = f"{self._client_id}:{self._client_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    async def _token(self, form: dict[str, str]) -> TokenSet:
        response = await self._call(
            HttpRequest(
                "POST",
                TOKEN_URL,
                {
                    "Authorization": self._basic(),
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                urlencode(form).encode(),
            ),
            token_endpoint=True,
        )
        data = self._json(response)
        try:
            return TokenSet(
                access_token=str(data["access_token"]),
                refresh_token=str(data["refresh_token"]),
                expires_at=self._now() + timedelta(seconds=int(data.get("expires_in", 1800))),
                scopes=str(data.get("scope", "")),
            )
        except (KeyError, TypeError, ValueError):
            raise ErpPermanentError("Xero token response was malformed") from None

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenSet:
        return await self._token(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        )

    async def refresh(self, refresh_token: str) -> TokenSet:
        return await self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})

    async def resolve_tenant(self, access_token: str) -> ErpTenant:
        response = await self._call(
            HttpRequest(
                "GET",
                CONNECTIONS_URL,
                {"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
        )
        connections = self._json(response)
        if not isinstance(connections, list):
            raise ErpPermanentError("Xero connections response was malformed")
        orgs = [c for c in connections if c.get("tenantType", "ORGANISATION") == "ORGANISATION"]
        if not orgs:
            raise ErpPermanentError("No Xero organisation was authorised")
        first = orgs[0]
        return ErpTenant(str(first["tenantId"]), first.get("tenantName"))

    # --- Accounting API ------------------------------------------------------------------

    def _headers(self, ctx: ErpContext, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {ctx.access_token}",
            "xero-tenant-id": ctx.tenant_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key[:128]
        return headers

    async def _api(
        self,
        ctx: ErpContext,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        response = await self._call(
            HttpRequest(
                method,
                f"{API_BASE}{path}",
                self._headers(ctx, idempotency_key),
                json.dumps(body).encode() if body is not None else None,
            )
        )
        return self._json(response)

    async def _call(self, request: HttpRequest, *, token_endpoint: bool = False) -> HttpResponse:
        try:
            response = await self._http.send(request)
        except HttpTransportError as error:
            raise ErpTransientError(f"Xero unreachable: {error}") from None
        status = response.status
        if 200 <= status < 300:
            return response
        if status == 429:
            retry_after = response.headers.get("retry-after")
            try:
                wait = float(retry_after) if retry_after else None
            except ValueError:
                wait = None
            raise ErpTransientError("Xero rate limit reached", retry_after=wait)
        if status >= 500 or status == 408:
            raise ErpTransientError(f"Xero server error {status}")
        if status in (401, 403) or (token_endpoint and status == 400):
            # invalid_grant on the token endpoint means the refresh token is dead.
            raise ErpAuthError(f"Xero rejected the credentials ({status})")
        raise ErpPermanentError(f"Xero rejected the request ({status}){self._detail(response)}")

    @staticmethod
    def _detail(response: HttpResponse) -> str:
        try:
            data = json.loads(response.body)
            messages = [
                str(m["Message"])
                for e in data.get("Elements") or []
                for m in e.get("ValidationErrors") or []
                if "Message" in m
            ]
            if not messages and data.get("Message"):
                messages = [str(data["Message"])]
        except (ValueError, AttributeError, TypeError):
            return ""
        return ": " + "; ".join(messages)[:160] if messages else ""

    @staticmethod
    def _json(response: HttpResponse) -> Any:
        try:
            return json.loads(response.body or b"{}")
        except ValueError:
            raise ErpTransientError("Xero returned a non-JSON body") from None

    async def _contact_id(self, ctx: ErpContext, name: str) -> str:
        where = quote(f'Name=="{_escape(name)}"', safe="")
        found = await self._api(ctx, "GET", f"/Contacts?where={where}")
        contacts = found.get("Contacts") or []
        if contacts:
            return str(contacts[0]["ContactID"])
        created = await self._api(
            ctx,
            "PUT",
            "/Contacts",
            body={"Contacts": [{"Name": name, "IsSupplier": True}]},
            idempotency_key=f"contact:{ctx.tenant_id}:{name}",
        )
        return str(created["Contacts"][0]["ContactID"])

    async def create_draft_bill(self, ctx: ErpContext, bill: ErpBill) -> ErpObject:
        contact_id = await self._contact_id(ctx, bill.vendor_name)
        where = quote(
            f'Type=="ACCPAY" AND InvoiceNumber=="{_escape(bill.reference)}" '
            f'AND Contact.ContactID==Guid("{contact_id}")',
            safe="",
        )
        existing = (await self._api(ctx, "GET", f"/Invoices?where={where}")).get("Invoices") or []
        live = [i for i in existing if i.get("Status") not in ("VOIDED", "DELETED")]
        if live:
            return ErpObject(str(live[0]["InvoiceID"]), live[0].get("Status"), created=False)
        payload = {
            "Invoices": [
                {
                    "Type": "ACCPAY",
                    "Contact": {"ContactID": contact_id},
                    "InvoiceNumber": bill.reference,
                    "Date": bill.issue_date.isoformat(),
                    "DueDate": bill.due_date.isoformat(),
                    "CurrencyCode": bill.currency,
                    "LineAmountTypes": "NoTax",
                    "Status": "DRAFT",  # never AUTHORISED: a human approves in Xero
                    "LineItems": [
                        {
                            "Description": bill.description,
                            "Quantity": 1,
                            "UnitAmount": _amount(bill.amount_minor, bill.currency_decimals),
                            "AccountCode": bill.expense_account_code,
                        }
                    ],
                }
            ]
        }
        created = await self._api(
            ctx, "PUT", "/Invoices", body=payload, idempotency_key=bill.idempotency_key
        )
        invoice = (created.get("Invoices") or [{}])[0]
        if "InvoiceID" not in invoice:
            raise ErpPermanentError("Xero did not return the new bill")
        return ErpObject(str(invoice["InvoiceID"]), invoice.get("Status"))

    async def _invoice(self, ctx: ErpContext, external_id: str) -> dict[str, Any]:
        data = await self._api(ctx, "GET", f"/Invoices/{quote(external_id, safe='')}")
        invoices = data.get("Invoices") or []
        if not invoices:
            raise ErpPermanentError("The bill no longer exists in Xero")
        invoice: dict[str, Any] = invoices[0]
        return invoice

    async def bill_status(self, ctx: ErpContext, external_id: str) -> BillStatus:
        raw = str((await self._invoice(ctx, external_id)).get("Status", ""))
        return BillStatus(_STATE_MAP.get(raw, BillState.DRAFT), raw)

    async def create_payment(
        self, ctx: ErpContext, payment: ErpPayment, bill_external_id: str
    ) -> ErpObject:
        invoice = await self._invoice(ctx, bill_external_id)
        for applied in invoice.get("Payments") or []:
            if applied.get("Reference") == payment.tx_hash and applied.get("Status") != "DELETED":
                return ErpObject(str(applied["PaymentID"]), applied.get("Status"), created=False)
        body = {
            "Invoice": {"InvoiceID": bill_external_id},
            "Account": {"Code": payment.payment_account_code},
            "Date": payment.paid_on.isoformat(),
            "Amount": _amount(payment.amount_minor, payment.currency_decimals),
            "Reference": payment.tx_hash,
        }
        created = await self._api(
            ctx, "PUT", "/Payments", body=body, idempotency_key=payment.idempotency_key
        )
        row = (created.get("Payments") or [{}])[0]
        if "PaymentID" not in row:
            raise ErpPermanentError("Xero did not return the new payment")
        return ErpObject(str(row["PaymentID"]), row.get("Status"))
