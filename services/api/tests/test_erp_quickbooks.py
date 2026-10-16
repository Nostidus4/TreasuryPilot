"""QuickBooks adapter against recorded-shape responses (REC-L02). No network, no real account."""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from treasurypilot_api.integrations.erp.provider import (
    BillState,
    ErpAuthError,
    ErpBill,
    ErpContext,
    ErpPayment,
    ErpPermanentError,
    ErpProvider,
    ErpTransientError,
)
from treasurypilot_api.integrations.erp.quickbooks import (
    API_BASE,
    PENDING_MARKER,
    TOKEN_URL,
    QuickBooksProvider,
)
from treasurypilot_api.integrations.erp.testing import FakeHttp, reply, transport_error

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
CTX = ErpContext("realm-1", "access-1")
BASE = f"{API_BASE}/realm-1"
BILL = ErpBill(
    reference="INV-100",
    idempotency_key="tp-bill-1",
    vendor_name="Acme O'Neil Ltd",
    issue_date=date(2026, 10, 1),
    due_date=date(2026, 10, 31),
    currency="USD",
    amount_minor=123456,
    currency_decimals=2,
    description="Invoice INV-100",
    expense_account_code="64",
)
PAYMENT = ErpPayment(
    bill_reference="INV-100",
    idempotency_key="tp-payment-1",
    paid_on=date(2026, 10, 15),
    currency="USD",
    amount_minor=123456,
    currency_decimals=2,
    tx_hash="0x" + "ab" * 32,
    payment_account_code="35",
)


def provider(http: FakeHttp) -> QuickBooksProvider:
    return QuickBooksProvider(http, client_id="cid", client_secret="secret", now=lambda: NOW)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_quickbooks_satisfies_the_provider_protocol() -> None:
    assert isinstance(provider(FakeHttp()), ErpProvider)


def test_authorize_url_carries_state_scope_and_redirect() -> None:
    url = provider(FakeHttp()).authorize_url("st", "https://app.test/cb")
    parts = urlparse(url)
    query = parse_qs(parts.query)
    assert parts.netloc == "appcenter.intuit.com"
    assert query["state"] == ["st"] and query["redirect_uri"] == ["https://app.test/cb"]
    assert query["scope"] == ["com.intuit.quickbooks.accounting"]


def test_code_exchange_and_refresh_use_basic_auth_and_parse_tokens() -> None:
    http = FakeHttp()
    token = {"access_token": "a", "refresh_token": "r", "expires_in": 3600}
    http.on("POST", TOKEN_URL, reply(200, token))
    tokens = run(provider(http).exchange_code("code-1#9130", "https://app.test/cb"))
    assert tokens.access_token == "a" and tokens.refresh_token == "r"
    assert tokens.tenant_hint == "9130"
    assert (tokens.expires_at - NOW).total_seconds() == 3600
    request = http.requests[0]
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"cid:secret").decode()
    form = parse_qs(request.body.decode())  # type: ignore[union-attr]
    assert form["grant_type"] == ["authorization_code"] and form["code"] == ["code-1"]
    assert run(provider(http).refresh("r")).tenant_hint is None
    assert parse_qs(http.requests[1].body.decode())["grant_type"] == ["refresh_token"]  # type: ignore[union-attr]


def test_callback_without_realm_id_is_refused_before_any_request() -> None:
    http = FakeHttp()
    with pytest.raises(ErpPermanentError):
        run(provider(http).exchange_code("code-only", "https://app.test/cb"))
    assert not http.requests


def test_revoked_refresh_token_is_an_auth_error() -> None:
    http = FakeHttp()
    http.on("POST", TOKEN_URL, reply(400, {"error": "invalid_grant"}))
    with pytest.raises(ErpAuthError):
        run(provider(http).refresh("dead"))


def _bill_http(existing: list[dict[str, Any]] | None = None) -> FakeHttp:
    http = FakeHttp()
    http.on("GET", f"{BASE}/query?query=select%20%2A%20from%20Vendor", reply(200, {}))
    http.on("POST", f"{BASE}/vendor", reply(200, {"Vendor": {"Id": "v-1"}}))
    http.on(
        "GET",
        f"{BASE}/query?query=select%20%2A%20from%20Bill",
        reply(200, {"QueryResponse": {"Bill": existing or []}}),
    )
    created = {"Bill": {"Id": "b-1", "PrivateNote": PENDING_MARKER}}
    http.on("POST", f"{BASE}/bill", reply(200, created))
    return http


def test_bill_is_created_pending_approval_with_request_id() -> None:
    http = _bill_http()
    created = run(provider(http).create_draft_bill(CTX, BILL))
    assert (created.external_id, created.status, created.created) == ("b-1", "DRAFT", True)
    post = http.calls("POST", f"{BASE}/bill")[0]
    sent = json.loads(post.body)  # type: ignore[arg-type]
    assert sent["DocNumber"] == "INV-100" and sent["CurrencyRef"] == {"value": "USD"}
    assert sent["PrivateNote"] == PENDING_MARKER
    assert sent["Line"][0]["Amount"] == 1234.56
    assert sent["Line"][0]["AccountBasedExpenseLineDetail"]["AccountRef"] == {"value": "64"}
    assert "requestid=tp-bill-1" in post.url
    assert post.headers["Authorization"] == "Bearer access-1"
    # the vendor name is escaped inside the query
    assert "DisplayName = 'Acme O\\'Neil Ltd'" in unquote(http.requests[0].url)


def test_overlong_invoice_number_is_refused_not_truncated() -> None:
    http = _bill_http()
    with pytest.raises(ErpPermanentError):
        run(provider(http).create_draft_bill(CTX, replace(BILL, reference="X" * 22)))
    assert not http.requests


def test_existing_bill_with_the_same_number_is_reused_not_duplicated() -> None:
    http = _bill_http([{"Id": "b-0", "PrivateNote": PENDING_MARKER, "TotalAmt": 1234.56}])
    found = run(provider(http).create_draft_bill(CTX, BILL))
    assert (found.external_id, found.created) == ("b-0", False)
    assert not http.calls("POST", f"{BASE}/bill")


def test_voided_bill_with_the_same_number_does_not_block_a_new_draft() -> None:
    http = _bill_http([{"Id": "b-0", "PrivateNote": "Voided", "TotalAmt": 0}])
    assert run(provider(http).create_draft_bill(CTX, BILL)).external_id == "b-1"


@pytest.mark.parametrize(
    ("bill", "state"),
    [
        ({"PrivateNote": PENDING_MARKER, "TotalAmt": 10, "Balance": 10}, BillState.DRAFT),
        ({"PrivateNote": "approved by cfo", "TotalAmt": 10, "Balance": 10}, BillState.APPROVED),
        ({"TotalAmt": 10, "Balance": 0}, BillState.PAID),
        ({"PrivateNote": "Voided", "TotalAmt": 0, "Balance": 0}, BillState.VOIDED),
    ],
)
def test_bill_status_mapping(bill: dict[str, Any], state: BillState) -> None:
    http = FakeHttp()
    http.on("GET", f"{BASE}/bill/b-1", reply(200, {"Bill": bill}))
    assert run(provider(http).bill_status(CTX, "b-1")).state is state


def test_nothing_the_adapter_sends_ever_removes_the_pending_marker() -> None:
    http = _bill_http()
    run(provider(http).create_draft_bill(CTX, BILL))
    posts = [r for r in http.requests if r.method == "POST" and r.url.startswith(f"{BASE}/bill")]
    assert all(PENDING_MARKER.encode() in (r.body or b"") for r in posts)


def _payment_http(applied: list[dict[str, Any]] | None = None) -> FakeHttp:
    http = FakeHttp()
    http.on("GET", f"{BASE}/bill/b-1", reply(200, {"Bill": {"VendorRef": {"value": "v-1"}}}))
    http.on(
        "GET",
        f"{BASE}/query?query=select%20%2A%20from%20BillPayment",
        reply(200, {"QueryResponse": {"BillPayment": applied or []}}),
    )
    http.on("POST", f"{BASE}/billpayment", reply(200, {"BillPayment": {"Id": "pay-1"}}))
    return http


def test_payment_carries_the_tx_hash_and_links_the_bill() -> None:
    http = _payment_http()
    created = run(provider(http).create_payment(CTX, PAYMENT, "b-1"))
    assert created.external_id == "pay-1"
    post = http.calls("POST", f"{BASE}/billpayment")[0]
    body = json.loads(post.body)  # type: ignore[arg-type]
    assert body["PrivateNote"] == "0x" + "ab" * 32
    assert body["TotalAmt"] == 1234.56 and body["TxnDate"] == "2026-10-15"
    assert body["CheckPayment"] == {"BankAccountRef": {"value": "35"}}
    assert body["Line"][0]["LinkedTxn"] == [{"TxnId": "b-1", "TxnType": "Bill"}]
    assert "requestid=tp-payment-1" in post.url


def test_payment_already_applied_with_the_same_reference_is_not_repeated() -> None:
    http = _payment_http([{"Id": "pay-0", "PrivateNote": PAYMENT.tx_hash}])
    found = run(provider(http).create_payment(CTX, PAYMENT, "b-1"))
    assert (found.external_id, found.created) == ("pay-0", False)
    assert not http.calls("POST", f"{BASE}/billpayment")


def test_error_mapping() -> None:
    fault = {"Fault": {"Error": [{"Message": "Account invalid", "Detail": "id 64"}]}}
    cases: list[tuple[Any, type[Exception]]] = [
        (reply(429, None, Retry_After="7"), ErpTransientError),
        (reply(503), ErpTransientError),
        (transport_error(), ErpTransientError),
        (reply(401), ErpAuthError),
        (reply(403), ErpAuthError),
        (reply(400, fault), ErpPermanentError),
    ]
    for response, expected in cases:
        http = FakeHttp()
        http.on("GET", f"{BASE}/bill/b-1", response)
        with pytest.raises(expected) as caught:
            run(provider(http).bill_status(CTX, "b-1"))
        if getattr(response, "status", None) == 429:
            assert caught.value.retry_after == 7.0  # type: ignore[attr-defined]
        if expected is ErpPermanentError:
            assert "Account invalid" in str(caught.value)


def test_secrets_never_appear_in_error_text() -> None:
    http = FakeHttp()
    http.on("GET", f"{BASE}/bill/b-1", reply(401, {"Message": "token access-1 bad"}))
    with pytest.raises(ErpAuthError) as caught:
        run(provider(http).bill_status(CTX, "b-1"))
    assert "access-1" not in str(caught.value)
