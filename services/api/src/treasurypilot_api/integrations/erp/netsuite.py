"""NetSuite adapter over OAuth 2.0 (authorization code) and the SuiteTalk REST web services.

Bills are ``vendorBill`` records created with ``approvalStatus`` Pending Approval (id ``1``);
this adapter has no call that approves a bill (id ``2``), so a human approves in NetSuite
(the account must have "Require approvals on vendor bills" enabled, see the module spec).
Payments are applied by transforming the approved bill into a ``vendorPayment``. Idempotency:
a SuiteQL lookup by transaction number (bills) or memo carrying the tx hash (payments)
before any create. The NetSuite account id is both the tenant id and part of every host name.
"""

from __future__ import annotations

import base64
import json
import re
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

SCOPES = "rest_webservices"
APPROVAL_PENDING = "1"
_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def host(account_id: str) -> str:
    """NetSuite host label: lower case, underscores become hyphens (``1234567_SB1``)."""

    return account_id.lower().replace("_", "-")


def authorize_endpoint(account_id: str) -> str:
    return f"https://{host(account_id)}.app.netsuite.com/app/login/oauth2/authorize.nl"


def token_endpoint(account_id: str) -> str:
    return f"{api_base(account_id)}/auth/oauth2/v1/token"


def api_base(account_id: str) -> str:
    return f"https://{host(account_id)}.suitetalk.api.netsuite.com/services/rest"


def _amount(minor: int, decimals: int) -> float:
    return float(Decimal(minor).scaleb(-decimals))


def _quote_sql(value: str) -> str:
    return value.replace("'", "''")


def _ref_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("id", ""))
    return "" if value is None else str(value)


def _approval_name(value: Any) -> str:
    return {"1": "PENDING_APPROVAL", "2": "APPROVED", "3": "REJECTED"}.get(str(value), "")


class NetSuiteProvider:
    key = "netsuite"
    display_name = "NetSuite"

    def __init__(
        self,
        http: HttpClient,
        *,
        account_id: str,
        client_id: str,
        client_secret: str,
        now: Any = None,
    ) -> None:
        if not _ACCOUNT_RE.match(account_id):
            raise ValueError("invalid NetSuite account id")
        self._http = http
        self._account_id = account_id
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
        return f"{authorize_endpoint(self._account_id)}?{query}"

    def _basic(self) -> str:
        raw = f"{self._client_id}:{self._client_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    async def _token(self, form: dict[str, str]) -> TokenSet:
        response = await self._call(
            HttpRequest(
                "POST",
                token_endpoint(self._account_id),
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
            refresh = str(data.get("refresh_token") or form.get("refresh_token") or "")
            if not refresh:
                raise ValueError
            return TokenSet(
                access_token=str(data["access_token"]),
                # NetSuite may keep the refresh token on refresh; reuse the one we sent.
                refresh_token=refresh,
                expires_at=self._now() + timedelta(seconds=int(data.get("expires_in", 3600))),
                scopes=str(data.get("scope", SCOPES)),
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ErpPermanentError("NetSuite token response was malformed") from None

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenSet:
        return await self._token(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        )

    async def refresh(self, refresh_token: str) -> TokenSet:
        return await self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})

    async def resolve_tenant(self, access_token: str) -> ErpTenant:
        """The account is fixed by configuration; this proves the token works against it."""

        ctx = ErpContext(self._account_id, access_token)
        await self._query(ctx, "SELECT id FROM currency FETCH FIRST 1 ROWS ONLY")
        return ErpTenant(self._account_id, f"NetSuite {self._account_id}")

    # --- REST web services ---------------------------------------------------------------

    @staticmethod
    def _headers(ctx: ErpContext, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {ctx.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            # NetSuite documents no idempotency header; sent for traceability only. The
            # lookup before every create is what makes a retry safe.
            headers["X-Request-Id"] = idempotency_key[:128]
        return headers

    async def _api(
        self,
        ctx: ErpContext,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> HttpResponse:
        headers = {**self._headers(ctx, idempotency_key), **(extra or {})}
        return await self._call(
            HttpRequest(
                method,
                f"{api_base(ctx.tenant_id)}{path}",
                headers,
                json.dumps(body).encode() if body is not None else None,
            )
        )

    async def _query(self, ctx: ErpContext, sql: str) -> list[dict[str, Any]]:
        response = await self._api(
            ctx, "POST", "/query/v1/suiteql", body={"q": sql}, extra={"Prefer": "transient"}
        )
        items = self._json(response).get("items")
        return [i for i in items or [] if isinstance(i, dict)]

    async def _call(self, request: HttpRequest, *, token_endpoint: bool = False) -> HttpResponse:
        try:
            response = await self._http.send(request)
        except HttpTransportError as error:
            raise ErpTransientError(f"NetSuite unreachable: {error}") from None
        status = response.status
        if 200 <= status < 300:
            return response
        if status == 429:
            retry_after = response.headers.get("retry-after")
            try:
                wait = float(retry_after) if retry_after else None
            except ValueError:
                wait = None
            raise ErpTransientError("NetSuite rate limit reached", retry_after=wait)
        if status >= 500 or status == 408:
            raise ErpTransientError(f"NetSuite server error {status}")
        if status in (401, 403) or (token_endpoint and status == 400):
            raise ErpAuthError(f"NetSuite rejected the credentials ({status})")
        raise ErpPermanentError(f"NetSuite rejected the request ({status}){self._detail(response)}")

    @staticmethod
    def _detail(response: HttpResponse) -> str:
        try:
            data = json.loads(response.body)
            messages = [str(e["detail"]) for e in data.get("o:errorDetails") or [] if "detail" in e]
            if not messages and data.get("detail"):
                messages = [str(data["detail"])]
        except (ValueError, AttributeError, TypeError):
            return ""
        return ": " + "; ".join(messages)[:160] if messages else ""

    @staticmethod
    def _json(response: HttpResponse) -> Any:
        if not response.body:
            return {}
        try:
            return json.loads(response.body)
        except ValueError:
            raise ErpTransientError("NetSuite returned a non-JSON body") from None

    @staticmethod
    def _created_id(response: HttpResponse, what: str) -> str:
        """Record creates answer 204 with the new record's URL in ``Location``."""

        location = response.headers.get("location", "")
        record_id = location.rstrip("/").rsplit("/", 1)[-1]
        if not record_id:
            raise ErpPermanentError(f"NetSuite did not return the new {what}")
        return record_id

    async def _vendor_id(self, ctx: ErpContext, name: str) -> str:
        rows = await self._query(
            ctx,
            f"SELECT id FROM vendor WHERE companyName = '{_quote_sql(name)}' "
            "AND isInactive = 'F' FETCH FIRST 1 ROWS ONLY",
        )
        if rows:
            return str(rows[0]["id"])
        created = await self._api(
            ctx,
            "POST",
            "/record/v1/vendor",
            body={"companyName": name, "isPerson": False},
            idempotency_key=f"vendor:{ctx.tenant_id}:{name}",
        )
        return self._created_id(created, "vendor")

    async def create_draft_bill(self, ctx: ErpContext, bill: ErpBill) -> ErpObject:
        vendor_id = await self._vendor_id(ctx, bill.vendor_name)
        existing = await self._query(
            ctx,
            "SELECT id, approvalStatus FROM transaction WHERE type = 'VendBill' "
            f"AND tranId = '{_quote_sql(bill.reference)}' AND entity = {int(vendor_id)} "
            "AND voided = 'F' FETCH FIRST 1 ROWS ONLY",
        )
        if existing:
            return ErpObject(
                str(existing[0]["id"]), _approval_name(existing[0].get("approvalstatus")), False
            )
        payload = {
            "entity": {"id": vendor_id},
            "tranId": bill.reference,
            "tranDate": bill.issue_date.isoformat(),
            "dueDate": bill.due_date.isoformat(),
            "currency": {"refName": bill.currency},
            "memo": bill.description,
            "approvalStatus": {"id": APPROVAL_PENDING},  # never "2": a human approves
            "expense": {
                "items": [
                    {
                        "account": {"id": bill.expense_account_code},
                        "amount": _amount(bill.amount_minor, bill.currency_decimals),
                        "memo": bill.description,
                    }
                ]
            },
        }
        created = await self._api(
            ctx, "POST", "/record/v1/vendorBill", body=payload, idempotency_key=bill.idempotency_key
        )
        return ErpObject(self._created_id(created, "bill"), "PENDING_APPROVAL")

    async def _bill(self, ctx: ErpContext, external_id: str) -> dict[str, Any]:
        try:
            response = await self._api(
                ctx, "GET", f"/record/v1/vendorBill/{quote(external_id, safe='')}"
            )
        except ErpPermanentError as error:
            if "(404)" in str(error):
                raise ErpPermanentError("The bill no longer exists in NetSuite") from None
            raise
        data = self._json(response)
        if not isinstance(data, dict):
            raise ErpTransientError("NetSuite returned a malformed bill")
        return data

    async def bill_status(self, ctx: ErpContext, external_id: str) -> BillStatus:
        bill = await self._bill(ctx, external_id)
        status = _ref_id(bill.get("status"))
        approval = _ref_id(bill.get("approvalStatus"))
        raw = f"{status}/{approval}"
        if status.endswith(":V"):
            return BillStatus(BillState.VOIDED, raw)
        if status.endswith(":B"):
            return BillStatus(BillState.PAID, raw)
        if approval == "2":
            return BillStatus(BillState.APPROVED, raw)
        return BillStatus(BillState.DRAFT, raw)

    async def create_payment(
        self, ctx: ErpContext, payment: ErpPayment, bill_external_id: str
    ) -> ErpObject:
        found = await self._query(
            ctx,
            "SELECT id FROM transaction WHERE type = 'VendPymt' "
            f"AND memo = '{_quote_sql(payment.tx_hash)}' AND voided = 'F' "
            "FETCH FIRST 1 ROWS ONLY",
        )
        if found:
            return ErpObject(str(found[0]["id"]), None, created=False)
        body = {
            "account": {"id": payment.payment_account_code},
            "tranDate": payment.paid_on.isoformat(),
            "memo": payment.tx_hash,
            "apply": {
                "items": [
                    {
                        "doc": {"id": bill_external_id},
                        "apply": True,
                        "amount": _amount(payment.amount_minor, payment.currency_decimals),
                    }
                ]
            },
        }
        created = await self._api(
            ctx,
            "POST",
            f"/record/v1/vendorBill/{quote(bill_external_id, safe='')}/!transform/vendorPayment",
            body=body,
            idempotency_key=payment.idempotency_key,
        )
        return ErpObject(self._created_id(created, "payment"))
