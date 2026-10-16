"""QuickBooks Online adapter over the documented OAuth 2.0 and Accounting API (developer.intuit.com).

QuickBooks has no draft or approval state for bills, so a bill is posted immediately and carries
the ``PENDING_MARKER`` in ``PrivateNote``. It stays DRAFT until a human removes that marker in
QuickBooks; only then does ``bill_status`` report APPROVED and a payment may be applied. This
adapter has no call that removes the marker. Idempotency: ``requestid`` query parameter plus a
lookup by DocNumber (bills) or BillPayment ``PrivateNote`` = tx hash (payments) before any create.

The company (``realmId``) arrives in the OAuth redirect, not from an API: the web app posts the
callback ``code`` as ``"<code>#<realmId>"`` and ``exchange_code`` returns it as ``tenant_hint``.
Account codes in this adapter are QuickBooks account Ids.
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

AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"  # noqa: S105 - public
API_BASE = "https://quickbooks.api.intuit.com/v3/company"
SANDBOX_API_BASE = "https://sandbox-quickbooks.api.intuit.com/v3/company"
SCOPES = "com.intuit.quickbooks.accounting"
MINOR_VERSION = "75"
PENDING_MARKER = "[TP-PENDING-APPROVAL]"
DOC_NUMBER_MAX = 21  # QuickBooks limit; never truncated silently, the bill is refused instead


def _amount(minor: int, decimals: int) -> float:
    return float(Decimal(minor).scaleb(-decimals))


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class QuickBooksProvider:
    key = "quickbooks"
    display_name = "QuickBooks Online"

    def __init__(
        self,
        http: HttpClient,
        *,
        client_id: str,
        client_secret: str,
        sandbox: bool = False,
        now: Any = None,
    ) -> None:
        self._http = http
        self._client_id = client_id
        self._client_secret = client_secret
        self._api_base = SANDBOX_API_BASE if sandbox else API_BASE
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

    async def _token(self, form: dict[str, str], tenant_hint: str | None = None) -> TokenSet:
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
                expires_at=self._now() + timedelta(seconds=int(data.get("expires_in", 3600))),
                scopes=SCOPES,
                tenant_hint=tenant_hint,
            )
        except (KeyError, TypeError, ValueError):
            raise ErpPermanentError("QuickBooks token response was malformed") from None

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenSet:
        code, _, realm_id = code.partition("#")
        if not code or not realm_id.strip():
            raise ErpPermanentError("QuickBooks callback must carry the code and the realmId")
        return await self._token(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
            tenant_hint=realm_id.strip(),
        )

    async def refresh(self, refresh_token: str) -> TokenSet:
        return await self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})

    async def resolve_tenant(self, access_token: str) -> ErpTenant:
        # The realmId only exists in the OAuth redirect; the framework uses TokenSet.tenant_hint.
        raise ErpPermanentError("QuickBooks company is identified by the OAuth realmId")

    # --- Accounting API ------------------------------------------------------------------

    def _headers(self, ctx: ErpContext) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {ctx.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _url(self, ctx: ErpContext, path: str, request_id: str | None = None) -> str:
        sep = "&" if "?" in path else "?"
        company = quote(ctx.tenant_id, safe="")
        url = f"{self._api_base}/{company}{path}{sep}minorversion={MINOR_VERSION}"
        if request_id:
            url += f"&requestid={quote(request_id[:50], safe='')}"
        return url

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
                self._url(ctx, path, idempotency_key),
                self._headers(ctx),
                json.dumps(body).encode() if body is not None else None,
            )
        )
        return self._json(response)

    async def _query(self, ctx: ErpContext, statement: str, entity: str) -> list[dict[str, Any]]:
        data = await self._api(ctx, "GET", f"/query?query={quote(statement, safe='')}")
        rows = (data.get("QueryResponse") or {}).get(entity) or []
        return [r for r in rows if isinstance(r, dict)]

    async def _call(self, request: HttpRequest, *, token_endpoint: bool = False) -> HttpResponse:
        try:
            response = await self._http.send(request)
        except HttpTransportError as error:
            raise ErpTransientError(f"QuickBooks unreachable: {error}") from None
        status = response.status
        if 200 <= status < 300:
            return response
        if status == 429:
            retry_after = response.headers.get("retry-after")
            try:
                wait = float(retry_after) if retry_after else None
            except ValueError:
                wait = None
            raise ErpTransientError("QuickBooks rate limit reached", retry_after=wait)
        if status >= 500 or status == 408:
            raise ErpTransientError(f"QuickBooks server error {status}")
        if status in (401, 403) or (token_endpoint and status == 400):
            # invalid_grant on the token endpoint means the refresh token is dead.
            raise ErpAuthError(f"QuickBooks rejected the credentials ({status})")
        raise ErpPermanentError(
            f"QuickBooks rejected the request ({status}){self._detail(response)}"
        )

    @staticmethod
    def _detail(response: HttpResponse) -> str:
        try:
            data = json.loads(response.body)
            messages = [
                str(e["Message"]) + (f" ({e['Detail']})" if e.get("Detail") else "")
                for e in (data.get("Fault") or {}).get("Error") or []
                if "Message" in e
            ]
        except (ValueError, AttributeError, TypeError):
            return ""
        return ": " + "; ".join(messages)[:160] if messages else ""

    @staticmethod
    def _json(response: HttpResponse) -> Any:
        try:
            return json.loads(response.body or b"{}")
        except ValueError:
            raise ErpTransientError("QuickBooks returned a non-JSON body") from None

    async def _vendor_id(self, ctx: ErpContext, name: str) -> str:
        found = await self._query(
            ctx, f"select * from Vendor where DisplayName = '{_escape(name)}'", "Vendor"
        )
        if found:
            return str(found[0]["Id"])
        created = await self._api(
            ctx,
            "POST",
            "/vendor",
            body={"DisplayName": name},
            idempotency_key=f"vendor:{ctx.tenant_id}:{name}",
        )
        return str(created["Vendor"]["Id"])

    @staticmethod
    def _is_voided(bill: dict[str, Any]) -> bool:
        return "voided" in str(bill.get("PrivateNote", "")).lower() and not bill.get("TotalAmt")

    @staticmethod
    def _state(bill: dict[str, Any]) -> BillState:
        if QuickBooksProvider._is_voided(bill):
            return BillState.VOIDED
        if PENDING_MARKER in str(bill.get("PrivateNote", "")):
            return BillState.DRAFT
        if bill.get("TotalAmt") and not Decimal(str(bill.get("Balance", 1))):
            return BillState.PAID
        return BillState.APPROVED

    async def create_draft_bill(self, ctx: ErpContext, bill: ErpBill) -> ErpObject:
        if len(bill.reference) > DOC_NUMBER_MAX:
            raise ErpPermanentError(
                f"Invoice number is longer than QuickBooks allows ({DOC_NUMBER_MAX})"
            )
        vendor_id = await self._vendor_id(ctx, bill.vendor_name)
        existing = await self._query(
            ctx,
            f"select * from Bill where DocNumber = '{_escape(bill.reference)}' "
            f"and VendorRef = '{_escape(vendor_id)}'",
            "Bill",
        )
        live = [b for b in existing if not self._is_voided(b)]
        if live:
            return ErpObject(str(live[0]["Id"]), self._state(live[0]).value, created=False)
        payload = {
            "VendorRef": {"value": vendor_id},
            "DocNumber": bill.reference,
            "TxnDate": bill.issue_date.isoformat(),
            "DueDate": bill.due_date.isoformat(),
            "CurrencyRef": {"value": bill.currency},
            "PrivateNote": PENDING_MARKER,  # a human removes it in QuickBooks to approve
            "Line": [
                {
                    "DetailType": "AccountBasedExpenseLineDetail",
                    "Amount": _amount(bill.amount_minor, bill.currency_decimals),
                    "Description": bill.description,
                    "AccountBasedExpenseLineDetail": {
                        "AccountRef": {"value": bill.expense_account_code}
                    },
                }
            ],
        }
        created = await self._api(
            ctx, "POST", "/bill", body=payload, idempotency_key=bill.idempotency_key
        )
        row = created.get("Bill") or {}
        if "Id" not in row:
            raise ErpPermanentError("QuickBooks did not return the new bill")
        return ErpObject(str(row["Id"]), self._state(row).value)

    async def _bill(self, ctx: ErpContext, external_id: str) -> dict[str, Any]:
        data = await self._api(ctx, "GET", f"/bill/{quote(external_id, safe='')}")
        bill = data.get("Bill")
        if not isinstance(bill, dict):
            raise ErpPermanentError("The bill no longer exists in QuickBooks")
        return bill

    async def bill_status(self, ctx: ErpContext, external_id: str) -> BillStatus:
        state = self._state(await self._bill(ctx, external_id))
        return BillStatus(state, state.value)

    async def create_payment(
        self, ctx: ErpContext, payment: ErpPayment, bill_external_id: str
    ) -> ErpObject:
        bill = await self._bill(ctx, bill_external_id)
        vendor_id = str((bill.get("VendorRef") or {}).get("value", ""))
        if not vendor_id:
            raise ErpPermanentError("The QuickBooks bill has no vendor")
        applied = await self._query(
            ctx,
            f"select * from BillPayment where VendorRef = '{_escape(vendor_id)}'",
            "BillPayment",
        )
        for row in applied:
            if row.get("PrivateNote") == payment.tx_hash:
                return ErpObject(str(row["Id"]), "RECORDED", created=False)
        amount = _amount(payment.amount_minor, payment.currency_decimals)
        body = {
            "VendorRef": {"value": vendor_id},
            "PayType": "Check",
            "CheckPayment": {"BankAccountRef": {"value": payment.payment_account_code}},
            "TotalAmt": amount,
            "TxnDate": payment.paid_on.isoformat(),
            "CurrencyRef": {"value": payment.currency},
            "PrivateNote": payment.tx_hash,
            "Line": [
                {
                    "Amount": amount,
                    "LinkedTxn": [{"TxnId": bill_external_id, "TxnType": "Bill"}],
                }
            ],
        }
        created = await self._api(
            ctx, "POST", "/billpayment", body=body, idempotency_key=payment.idempotency_key
        )
        row = created.get("BillPayment") or {}
        if "Id" not in row:
            raise ErpPermanentError("QuickBooks did not return the new payment")
        return ErpObject(str(row["Id"]), "RECORDED")
