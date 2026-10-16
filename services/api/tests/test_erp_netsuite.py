"""NetSuite adapter against recorded-shape responses (REC-L03). No network, no real account."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from treasurypilot_api.integrations.erp.netsuite import NetSuiteProvider, api_base, token_endpoint
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

ACCOUNT = "1234567_SB1"
BASE = api_base(ACCOUNT)
TOKEN_URL = token_endpoint(ACCOUNT)
QUERY = f"{BASE}/query/v1/suiteql"
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
CTX = ErpContext(ACCOUNT, "access-1")
BILL = ErpBill(
    reference="INV-100",
    idempotency_key="tp-bill-1",
    vendor_name="Acme O'Brien Ltd",
    issue_date=date(2026, 10, 1),
    due_date=date(2026, 10, 31),
    currency="USD",
    amount_minor=123456,
    currency_decimals=2,
    description="Invoice INV-100",
    expense_account_code="210",
)
PAYMENT = ErpPayment(
    bill_reference="INV-100",
    idempotency_key="tp-payment-1",
    paid_on=date(2026, 10, 15),
    currency="USD",
    amount_minor=123456,
    currency_decimals=2,
    tx_hash="0x" + "ab" * 32,
    payment_account_code="25",
)


def provider(http: FakeHttp) -> NetSuiteProvider:
    return NetSuiteProvider(
        http, account_id=ACCOUNT, client_id="cid", client_secret="secret", now=lambda: NOW
    )


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def located(record: str, id_: str) -> Any:
    return reply(204, None, Location=f"{BASE}/record/v1/{record}/{id_}")


def sql_of(request: Any) -> str:
    return str(json.loads(request.body)["q"])


def test_netsuite_satisfies_the_provider_protocol() -> None:
    assert isinstance(provider(FakeHttp()), ErpProvider)


def test_account_id_is_validated_and_shapes_the_host() -> None:
    with pytest.raises(ValueError):
        NetSuiteProvider(FakeHttp(), account_id="x/../evil", client_id="c", client_secret="s")
    assert BASE.startswith("https://1234567-sb1.suitetalk.api.netsuite.com/")


def test_authorize_url_carries_state_scope_and_redirect() -> None:
    url = provider(FakeHttp()).authorize_url("st", "https://app.test/cb")
    parts = urlparse(url)
    query = parse_qs(parts.query)
    assert parts.netloc == "1234567-sb1.app.netsuite.com"
    assert query["state"] == ["st"] and query["redirect_uri"] == ["https://app.test/cb"]
    assert query["scope"] == ["rest_webservices"] and query["response_type"] == ["code"]


def test_code_exchange_and_refresh_use_basic_auth_and_parse_tokens() -> None:
    http = FakeHttp()
    http.on(
        "POST",
        TOKEN_URL,
        reply(200, {"access_token": "a", "refresh_token": "r", "expires_in": 3600}),
    )
    tokens = run(provider(http).exchange_code("code-1", "https://app.test/cb"))
    assert tokens.access_token == "a" and tokens.refresh_token == "r"
    assert (tokens.expires_at - NOW).total_seconds() == 3600
    request = http.requests[0]
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"cid:secret").decode()
    assert parse_qs(request.body.decode())["grant_type"] == ["authorization_code"]  # type: ignore[union-attr]
    run(provider(http).refresh("r"))
    assert parse_qs(http.requests[1].body.decode())["grant_type"] == ["refresh_token"]  # type: ignore[union-attr]


def test_refresh_keeps_the_old_refresh_token_when_none_is_returned() -> None:
    http = FakeHttp()
    http.on("POST", TOKEN_URL, reply(200, {"access_token": "a2", "expires_in": 3600}))
    assert run(provider(http).refresh("r-old")).refresh_token == "r-old"


def test_code_exchange_without_a_refresh_token_is_permanent() -> None:
    http = FakeHttp()
    http.on("POST", TOKEN_URL, reply(200, {"access_token": "a"}))
    with pytest.raises(ErpPermanentError):
        run(provider(http).exchange_code("c", "https://app.test/cb"))


def test_revoked_refresh_token_is_an_auth_error() -> None:
    http = FakeHttp()
    http.on("POST", TOKEN_URL, reply(400, {"error": "invalid_grant"}))
    with pytest.raises(ErpAuthError):
        run(provider(http).refresh("dead"))


def test_tenant_is_the_configured_account_after_a_probe() -> None:
    http = FakeHttp()
    http.on("POST", QUERY, reply(200, {"items": [{"id": "1"}]}))
    tenant = run(provider(http).resolve_tenant("a"))
    assert tenant.tenant_id == ACCOUNT
    assert http.requests[0].headers["Authorization"] == "Bearer a"


def _bill_http(existing: list[dict[str, Any]] | None = None, vendors: bool = True) -> FakeHttp:
    http = FakeHttp()

    def query(request: Any) -> Any:
        sql = sql_of(request)
        if "FROM vendor" in sql:
            return reply(200, {"items": [{"id": "77"}] if vendors else []})
        return reply(200, {"items": existing or []})

    http.on("POST", QUERY, query)
    # the longer prefix first: routes match by url prefix, in order
    http.on("POST", f"{BASE}/record/v1/vendorBill", located("vendorBill", "5001"))
    http.on("POST", f"{BASE}/record/v1/vendor", located("vendor", "78"))
    return http


def test_bill_is_created_pending_approval_with_integer_derived_amount() -> None:
    http = _bill_http()
    created = run(provider(http).create_draft_bill(CTX, BILL))
    assert (created.external_id, created.created) == ("5001", True)
    post = http.calls("POST", f"{BASE}/record/v1/vendorBill")[0]
    sent = json.loads(post.body)  # type: ignore[arg-type]
    assert sent["approvalStatus"] == {"id": "1"}
    assert sent["tranId"] == "INV-100" and sent["currency"] == {"refName": "USD"}
    assert sent["entity"] == {"id": "77"}
    assert sent["expense"]["items"][0]["amount"] == 1234.56
    assert sent["expense"]["items"][0]["account"] == {"id": "210"}
    assert post.headers["X-Request-Id"] == "tp-bill-1"
    assert post.headers["Authorization"] == "Bearer access-1"
    # single quotes in the vendor name are escaped inside SuiteQL
    assert "'Acme O''Brien Ltd'" in sql_of(http.calls("POST", QUERY)[0])


def test_unknown_vendor_is_created_first() -> None:
    http = _bill_http(vendors=False)
    run(provider(http).create_draft_bill(CTX, BILL))
    assert http.calls("POST", f"{BASE}/record/v1/vendor")
    assert json.loads(http.calls("POST", f"{BASE}/record/v1/vendorBill")[0].body)["entity"] == {  # type: ignore[arg-type]
        "id": "78"
    }


def test_nothing_the_adapter_sends_ever_approves_a_bill() -> None:
    http = _bill_http()
    run(provider(http).create_draft_bill(CTX, BILL))
    for request in http.requests:
        assert b'"approvalStatus": {"id": "2"}' not in (request.body or b"")


def test_existing_bill_with_the_same_number_is_reused_not_duplicated() -> None:
    http = _bill_http([{"id": "4000", "approvalstatus": "1"}])
    found = run(provider(http).create_draft_bill(CTX, BILL))
    assert (found.external_id, found.created) == ("4000", False)
    assert not http.calls("POST", f"{BASE}/record/v1/vendorBill")


@pytest.mark.parametrize(
    ("status", "approval", "state"),
    [
        ("VendBill:A", "1", BillState.DRAFT),
        ("VendBill:A", "3", BillState.DRAFT),
        ("VendBill:A", "2", BillState.APPROVED),
        ("VendBill:B", "2", BillState.PAID),
        ("VendBill:V", "2", BillState.VOIDED),
    ],
)
def test_bill_status_mapping(status: str, approval: str, state: BillState) -> None:
    http = FakeHttp()
    http.on(
        "GET",
        f"{BASE}/record/v1/vendorBill/5001",
        reply(200, {"status": {"id": status}, "approvalStatus": {"id": approval}}),
    )
    assert run(provider(http).bill_status(CTX, "5001")).state is state


def test_missing_bill_is_a_permanent_error() -> None:
    http = FakeHttp()
    http.on("GET", f"{BASE}/record/v1/vendorBill/5001", reply(404, {"detail": "not found"}))
    with pytest.raises(ErpPermanentError, match="no longer exists"):
        run(provider(http).bill_status(CTX, "5001"))


def test_payment_transforms_the_bill_and_carries_the_tx_hash() -> None:
    http = FakeHttp()
    http.on("POST", QUERY, reply(200, {"items": []}))
    http.on(
        "POST",
        f"{BASE}/record/v1/vendorBill/5001/!transform/vendorPayment",
        located("vendorPayment", "9001"),
    )
    created = run(provider(http).create_payment(CTX, PAYMENT, "5001"))
    assert (created.external_id, created.created) == ("9001", True)
    post = http.calls("POST", f"{BASE}/record/v1/vendorBill/5001/!transform")[0]
    assert json.loads(post.body) == {  # type: ignore[arg-type]
        "account": {"id": "25"},
        "tranDate": "2026-10-15",
        "memo": "0x" + "ab" * 32,
        "apply": {"items": [{"doc": {"id": "5001"}, "apply": True, "amount": 1234.56}]},
    }
    assert post.headers["X-Request-Id"] == "tp-payment-1"


def test_payment_already_applied_with_the_same_reference_is_not_repeated() -> None:
    http = FakeHttp()
    http.on("POST", QUERY, reply(200, {"items": [{"id": "9000"}]}))
    found = run(provider(http).create_payment(CTX, PAYMENT, "5001"))
    assert (found.external_id, found.created) == ("9000", False)
    assert not http.calls("POST", f"{BASE}/record/v1/vendorBill/5001/!transform")


def test_error_mapping() -> None:
    cases: list[tuple[Any, type[Exception]]] = [
        (reply(429, None, Retry_After="7"), ErpTransientError),
        (reply(503), ErpTransientError),
        (transport_error(), ErpTransientError),
        (reply(401), ErpAuthError),
        (reply(403), ErpAuthError),
        (
            reply(400, {"o:errorDetails": [{"detail": "Invalid account reference"}]}),
            ErpPermanentError,
        ),
    ]
    for response, expected in cases:
        http = FakeHttp()
        http.on("GET", f"{BASE}/record/v1/vendorBill/5001", response)
        with pytest.raises(expected) as caught:
            run(provider(http).bill_status(CTX, "5001"))
        if isinstance(caught.value, ErpTransientError) and getattr(response, "status", 0) == 429:
            assert caught.value.retry_after == 7.0
        if expected is ErpPermanentError:
            assert "Invalid account reference" in str(caught.value)


def test_secrets_never_appear_in_error_text() -> None:
    http = FakeHttp()
    http.on("GET", f"{BASE}/record/v1/vendorBill/5001", reply(401, {"detail": "token access-1"}))
    with pytest.raises(ErpAuthError) as caught:
        run(provider(http).bill_status(CTX, "5001"))
    assert "access-1" not in str(caught.value)
