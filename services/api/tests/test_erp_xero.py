"""Xero adapter against recorded-shape responses (REC-L01). No network, no real account."""

from __future__ import annotations

import asyncio
import base64
import json
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
from treasurypilot_api.integrations.erp.testing import FakeHttp, reply, transport_error
from treasurypilot_api.integrations.erp.xero import API_BASE, TOKEN_URL, XeroProvider

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
CTX = ErpContext("tenant-1", "access-1")
BILL = ErpBill(
    reference="INV-100",
    idempotency_key="tp-bill-1",
    vendor_name='Acme "Ltd"',
    issue_date=date(2026, 10, 1),
    due_date=date(2026, 10, 31),
    currency="USD",
    amount_minor=123456,
    currency_decimals=2,
    description="Invoice INV-100",
    expense_account_code="6000",
)
PAYMENT = ErpPayment(
    bill_reference="INV-100",
    idempotency_key="tp-payment-1",
    paid_on=date(2026, 10, 15),
    currency="USD",
    amount_minor=123456,
    currency_decimals=2,
    tx_hash="0x" + "ab" * 32,
    payment_account_code="090",
)


def provider(http: FakeHttp) -> XeroProvider:
    return XeroProvider(http, client_id="cid", client_secret="secret", now=lambda: NOW)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_xero_satisfies_the_provider_protocol() -> None:
    assert isinstance(provider(FakeHttp()), ErpProvider)


def test_authorize_url_carries_state_scopes_and_redirect() -> None:
    url = provider(FakeHttp()).authorize_url("st", "https://app.test/cb")
    parts = urlparse(url)
    query = parse_qs(parts.query)
    assert parts.netloc == "login.xero.com"
    assert query["state"] == ["st"] and query["redirect_uri"] == ["https://app.test/cb"]
    assert "offline_access" in query["scope"][0] and "accounting.transactions" in query["scope"][0]


def test_code_exchange_and_refresh_use_basic_auth_and_parse_tokens() -> None:
    http = FakeHttp()
    http.on(
        "POST",
        TOKEN_URL,
        reply(200, {"access_token": "a", "refresh_token": "r", "expires_in": 1800, "scope": "s"}),
    )
    tokens = run(provider(http).exchange_code("code-1", "https://app.test/cb"))
    assert tokens.access_token == "a" and tokens.refresh_token == "r"
    assert (tokens.expires_at - NOW).total_seconds() == 1800
    request = http.requests[0]
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"cid:secret").decode()
    assert parse_qs(request.body.decode())["grant_type"] == ["authorization_code"]  # type: ignore[union-attr]
    run(provider(http).refresh("r"))
    assert parse_qs(http.requests[1].body.decode())["grant_type"] == ["refresh_token"]  # type: ignore[union-attr]


def test_revoked_refresh_token_is_an_auth_error() -> None:
    http = FakeHttp()
    http.on("POST", TOKEN_URL, reply(400, {"error": "invalid_grant"}))
    with pytest.raises(ErpAuthError):
        run(provider(http).refresh("dead"))


def test_tenant_resolution_picks_the_organisation() -> None:
    http = FakeHttp()
    http.on(
        "GET",
        "https://api.xero.com/connections",
        reply(200, [{"tenantId": "t-9", "tenantType": "ORGANISATION", "tenantName": "Demo Co"}]),
    )
    tenant = run(provider(http).resolve_tenant("a"))
    assert (tenant.tenant_id, tenant.name) == ("t-9", "Demo Co")


def _bill_http(existing: list[dict[str, Any]] | None = None) -> FakeHttp:
    http = FakeHttp()
    http.on("GET", f"{API_BASE}/Contacts", reply(200, {"Contacts": []}))
    http.on("PUT", f"{API_BASE}/Contacts", reply(200, {"Contacts": [{"ContactID": "c-1"}]}))
    http.on("GET", f"{API_BASE}/Invoices?", reply(200, {"Invoices": existing or []}))
    http.on(
        "PUT",
        f"{API_BASE}/Invoices",
        reply(200, {"Invoices": [{"InvoiceID": "inv-1", "Status": "DRAFT"}]}),
    )
    return http


def test_bill_is_created_as_an_accpay_draft_with_idempotency_key() -> None:
    http = _bill_http()
    created = run(provider(http).create_draft_bill(CTX, BILL))
    assert (created.external_id, created.status, created.created) == ("inv-1", "DRAFT", True)
    put = http.calls("PUT", f"{API_BASE}/Invoices")[0]
    sent = json.loads(put.body)["Invoices"][0]  # type: ignore[arg-type]
    assert sent["Type"] == "ACCPAY" and sent["Status"] == "DRAFT"
    assert sent["InvoiceNumber"] == "INV-100" and sent["CurrencyCode"] == "USD"
    assert sent["LineItems"][0]["UnitAmount"] == 1234.56
    assert sent["LineItems"][0]["AccountCode"] == "6000"
    assert put.headers["Idempotency-Key"] == "tp-bill-1"
    assert put.headers["xero-tenant-id"] == "tenant-1"
    # the contact name is escaped inside the where filter
    where = unquote(http.calls("GET", f"{API_BASE}/Contacts")[0].url)
    assert 'Name=="Acme \\"Ltd\\""' in where


def test_nothing_the_adapter_sends_ever_authorises_a_bill() -> None:
    http = _bill_http()
    run(provider(http).create_draft_bill(CTX, BILL))
    for request in http.requests:
        assert b"AUTHORISED" not in (request.body or b"")


def test_existing_bill_with_the_same_number_is_reused_not_duplicated() -> None:
    http = _bill_http([{"InvoiceID": "inv-0", "Status": "DRAFT"}])
    found = run(provider(http).create_draft_bill(CTX, BILL))
    assert (found.external_id, found.created) == ("inv-0", False)
    assert not http.calls("PUT", f"{API_BASE}/Invoices")


def test_voided_bill_with_the_same_number_does_not_block_a_new_draft() -> None:
    http = _bill_http([{"InvoiceID": "inv-0", "Status": "VOIDED"}])
    assert run(provider(http).create_draft_bill(CTX, BILL)).external_id == "inv-1"


@pytest.mark.parametrize(
    ("raw", "state"),
    [
        ("DRAFT", BillState.DRAFT),
        ("SUBMITTED", BillState.DRAFT),
        ("AUTHORISED", BillState.APPROVED),
        ("PAID", BillState.PAID),
        ("VOIDED", BillState.VOIDED),
        ("DELETED", BillState.VOIDED),
    ],
)
def test_bill_status_mapping(raw: str, state: BillState) -> None:
    http = FakeHttp()
    http.on("GET", f"{API_BASE}/Invoices/inv-1", reply(200, {"Invoices": [{"Status": raw}]}))
    assert run(provider(http).bill_status(CTX, "inv-1")).state is state


def test_payment_carries_the_tx_hash_as_reference() -> None:
    http = FakeHttp()
    http.on("GET", f"{API_BASE}/Invoices/inv-1", reply(200, {"Invoices": [{"Payments": []}]}))
    http.on("PUT", f"{API_BASE}/Payments", reply(200, {"Payments": [{"PaymentID": "pay-1"}]}))
    created = run(provider(http).create_payment(CTX, PAYMENT, "inv-1"))
    assert created.external_id == "pay-1"
    put = http.calls("PUT", f"{API_BASE}/Payments")[0]
    body = json.loads(put.body)  # type: ignore[arg-type]
    assert body == {
        "Invoice": {"InvoiceID": "inv-1"},
        "Account": {"Code": "090"},
        "Date": "2026-10-15",
        "Amount": 1234.56,
        "Reference": "0x" + "ab" * 32,
    }
    assert put.headers["Idempotency-Key"] == "tp-payment-1"


def test_payment_already_applied_with_the_same_reference_is_not_repeated() -> None:
    http = FakeHttp()
    applied = {"PaymentID": "pay-0", "Reference": PAYMENT.tx_hash, "Status": "AUTHORISED"}
    http.on(
        "GET", f"{API_BASE}/Invoices/inv-1", reply(200, {"Invoices": [{"Payments": [applied]}]})
    )
    found = run(provider(http).create_payment(CTX, PAYMENT, "inv-1"))
    assert (found.external_id, found.created) == ("pay-0", False)
    assert not http.calls("PUT", f"{API_BASE}/Payments")


def test_error_mapping() -> None:
    cases: list[tuple[Any, type[Exception]]] = [
        (reply(429, None, Retry_After="7"), ErpTransientError),
        (reply(503), ErpTransientError),
        (transport_error(), ErpTransientError),
        (reply(401), ErpAuthError),
        (reply(403), ErpAuthError),
        (
            reply(400, {"Elements": [{"ValidationErrors": [{"Message": "Account code invalid"}]}]}),
            ErpPermanentError,
        ),
    ]
    for response, expected in cases:
        http = FakeHttp()
        http.on("GET", f"{API_BASE}/Invoices/inv-1", response)
        with pytest.raises(expected) as caught:
            run(provider(http).bill_status(CTX, "inv-1"))
        if isinstance(caught.value, ErpTransientError) and isinstance(response, type(reply(200))):
            if response.status == 429:
                assert caught.value.retry_after == 7.0
        if expected is ErpPermanentError:
            assert "Account code invalid" in str(caught.value)


def test_secrets_never_appear_in_error_text() -> None:
    http = FakeHttp()
    http.on("GET", f"{API_BASE}/Invoices/inv-1", reply(401, {"Message": "token access-1 bad"}))
    with pytest.raises(ErpAuthError) as caught:
        run(provider(http).bill_status(CTX, "inv-1"))
    assert "access-1" not in str(caught.value)
