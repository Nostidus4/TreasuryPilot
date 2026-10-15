from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from eth_abi import decode
from fastapi.testclient import TestClient

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import AuthFailure, SessionAccess, UserRecord
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.invoices.models import RequestStatus
from treasurypilot_api.main import create_app
from treasurypilot_api.mandate import exceptions
from treasurypilot_api.mandate.models import ExceptionStatus, GovernanceTxStatus, PayeeStatus

ORG_ID = uuid.UUID("00000000-0000-4000-8000-000000000111")
TREASURY_ID = uuid.UUID("00000000-0000-4000-8000-000000000222")
REQUEST_ID = uuid.UUID("00000000-0000-4000-8000-000000000333")
OWNER_ID = uuid.UUID("00000000-0000-4000-8000-000000000444")
ASSET_ID = uuid.UUID("00000000-0000-4000-8000-000000000555")
REQUEST_ONCHAIN_ID = bytes.fromhex("66" * 32)
MODULE_ADDRESS = bytes.fromhex("11" * 20)
ASSET_ADDRESS = bytes.fromhex("22" * 20)
PAYEE_ADDRESS = bytes.fromhex("33" * 20)
GOVERNANCE_TX_ID = uuid.UUID("00000000-0000-4000-8000-000000000777")


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def begin(self) -> FakeSession:
        return self

    async def execute(self, *_: object, **__: object) -> None:
        return None

    async def scalar(self, *_: object, **__: object) -> None:
        return None

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        for row in self.added:
            if getattr(row, "version", None) is None:
                row.version = 1
        return None


class FakeSessions:
    def __init__(self) -> None:
        self.created: list[FakeSession] = []

    def __call__(self) -> FakeSession:
        session = FakeSession()
        self.created.append(session)
        return session


class FakeGovernanceService:
    def __init__(self, *, daily_used: int) -> None:
        self.daily_used = daily_used
        self.read_calls: list[tuple[int, bytes, bytes]] = []
        self.create_calls: list[dict[str, Any]] = []

    async def read_used_today(
        self, chain_id: int, module_address: bytes, asset_address: bytes
    ) -> int:
        self.read_calls.append((chain_id, module_address, asset_address))
        return self.daily_used

    async def create(self, **fields: Any) -> dict[str, Any]:
        self.create_calls.append(fields)
        return {"governanceTx": {"id": str(GOVERNANCE_TX_ID), "status": "Collecting"}}


def _context(
    *,
    amount: int = 150,
    per_request_cap: int = 100,
    daily_cap: int = 1_000,
    mandate_expiry: datetime | None = None,
) -> tuple[object, object, object, object, object]:
    now = datetime.now(UTC)
    payment = SimpleNamespace(
        id=REQUEST_ID,
        org_id=ORG_ID,
        treasury_id=TREASURY_ID,
        asset_id=ASSET_ID,
        chain_id=8453,
        amount=amount,
        onchain_request_id=REQUEST_ONCHAIN_ID,
        status=RequestStatus.APPROVED.value,
        current_revision=1,
    )
    treasury = SimpleNamespace(asset_id=ASSET_ID, module_address=MODULE_ADDRESS)
    payee = SimpleNamespace(
        address=PAYEE_ADDRESS,
        status=PayeeStatus.ACTIVE,
        active_from=now - timedelta(days=1),
    )
    asset = SimpleNamespace(id=ASSET_ID, address=ASSET_ADDRESS)
    mandate = SimpleNamespace(
        onchain_version=7,
        config={"limits": {"PAY": {"perRequest": str(per_request_cap), "daily": str(daily_cap)}}},
        expires_at=mandate_expiry or now + timedelta(days=60),
    )
    return payment, treasury, payee, asset, mandate


def _client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    context: tuple[object, object, object, object, object],
    daily_used: int,
) -> tuple[TestClient, FakeGovernanceService, FakeSessions]:
    async def request_context(
        _sessions: object,
        *,
        organization_id: uuid.UUID,
        request_id: uuid.UUID,
    ) -> tuple[object, object, object, object, object]:
        assert organization_id == ORG_ID
        assert request_id == REQUEST_ID
        return context

    async def no_approval_lookup(*_: object, **__: object) -> list[object]:
        pytest.fail("approval lookup should be supplied per test")

    async def no_audit_event(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(exceptions, "_request_context", request_context)
    monkeypatch.setattr(exceptions, "log_audit_event", no_audit_event)
    monkeypatch.setattr(
        exceptions,
        "_valid_approvals",
        no_approval_lookup,
    )

    sessions = FakeSessions()
    governance = FakeGovernanceService(daily_used=daily_used)
    app = create_app(settings=Settings(environment="local"))
    app.state.request_sessions = sessions
    app.state.governance_service = governance

    async def member_override(organization_id: uuid.UUID) -> MemberAccess:
        access = SessionAccess(
            user=UserRecord(OWNER_ID, "owner@example.test", None, "active"),
            session_id=uuid.UUID("00000000-0000-4000-8000-000000000888"),
            step_up_at=datetime.now(UTC),
        )
        return MemberAccess(
            access=access, organization_id=organization_id, roles=frozenset({"Owner"})
        )

    app.dependency_overrides[require_member] = member_override
    return TestClient(app), governance, sessions


def test_exception_grant_refuses_amount_at_or_below_cap_before_governance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(amount=100, per_request_cap=100)
    client, governance, _sessions = _client(monkeypatch, context=context, daily_used=0)
    with client:
        response = client.post(
            f"/v1/orgs/{ORG_ID}/requests/{REQUEST_ID}/exception/grant-tx",
            json={"expiryHours": 72},
        )

    assert response.status_code == 409
    assert response.json()["code"] == "NOT_OVER_CAP"
    assert governance.read_calls == []
    assert governance.create_calls == []


def test_exception_grant_refuses_daily_limit_before_governance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(amount=150, per_request_cap=100, daily_cap=200)
    client, governance, _sessions = _client(monkeypatch, context=context, daily_used=100)
    with client:
        response = client.post(
            f"/v1/orgs/{ORG_ID}/requests/{REQUEST_ID}/exception/grant-tx",
            json={"expiryHours": 72},
        )

    assert response.status_code == 409
    assert response.json()["code"] == "DAILY_LIMIT_WOULD_EXCEED"
    assert governance.read_calls == [(8453, MODULE_ADDRESS, ASSET_ADDRESS)]
    assert governance.create_calls == []


@pytest.mark.parametrize(
    ("approval_days", "mandate_days"),
    [(10, 20), (20, 10)],
    ids=["approval-expiry-caps-grant", "mandate-expiry-caps-grant"],
)
def test_exception_grant_uses_exact_request_terms_and_caps_expiry(
    monkeypatch: pytest.MonkeyPatch,
    approval_days: int,
    mandate_days: int,
) -> None:
    now = datetime.now(UTC)
    approval_expiry = now + timedelta(days=approval_days)
    mandate_expiry = now + timedelta(days=mandate_days)
    context = _context(mandate_expiry=mandate_expiry)
    client, governance, sessions = _client(monkeypatch, context=context, daily_used=200)
    approval = SimpleNamespace(
        typed_data={"message": {"expiry": int(approval_expiry.timestamp())}},
        expires_at=approval_expiry,
    )

    async def valid_approval_lookup(*_: object, **__: object) -> list[object]:
        return [approval]

    monkeypatch.setattr(exceptions, "_valid_approvals", valid_approval_lookup)

    with client:
        response = client.post(
            f"/v1/orgs/{ORG_ID}/requests/{REQUEST_ID}/exception/grant-tx",
            json={"expiryHours": 720},
        )

    assert response.status_code == 201
    assert len(governance.create_calls) == 1
    create_call = governance.create_calls[0]
    assert create_call["purpose"].value == "EXCEPTION_GRANT"
    assert create_call["entity_type"] == "exception"
    assert len(create_call["calls"]) == 1
    call = create_call["calls"][0]
    request_id, amount, payee_address, expiry = decode(
        ["bytes32", "uint128", "address", "uint64"], call.data[4:]
    )
    assert call.to == MODULE_ADDRESS
    assert request_id == REQUEST_ONCHAIN_ID
    assert amount == 150
    assert payee_address.lower() == "0x" + PAYEE_ADDRESS.hex()
    assert expiry == int(min(approval_expiry, mandate_expiry).timestamp())
    assert len(sessions.created) == 2
    stored_exception = sessions.created[-1].added[0]
    assert stored_exception.amount == 150
    assert stored_exception.payee == PAYEE_ADDRESS
    assert stored_exception.expiry == min(approval_expiry, mandate_expiry).replace(microsecond=0)


def test_pay_limits_refuse_missing_or_disabled_asset_policy() -> None:
    other = uuid.UUID("00000000-0000-4000-8000-000000000999")
    for policies in ([], [{"assetId": str(other), "enabled": False}]):
        with pytest.raises(AuthFailure) as caught:
            exceptions._pay_limits(
                {"assetPolicies": policies}, asset_id=other, primary_asset_id=ASSET_ID
            )
        assert caught.value.code == "ASSET_NOT_ENABLED"


def test_approval_expiry_falls_back_when_signed_expiry_is_unparseable() -> None:
    fallback = datetime.now(UTC) + timedelta(days=1)
    approval = SimpleNamespace(typed_data={"message": {"expiry": "soon"}}, expires_at=fallback)
    assert exceptions._approval_expiry([approval]) == fallback  # type: ignore[list-item]


def test_reject_granted_exception_reports_active(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _governance, _sessions = _client(monkeypatch, context=_context(), daily_used=0)
    granted = SimpleNamespace(status=ExceptionStatus.GRANTED)

    async def scalar(*_: object, **__: object) -> object:
        return granted

    monkeypatch.setattr(FakeSession, "scalar", scalar)
    with client:
        response = client.post(
            f"/v1/orgs/{ORG_ID}/requests/{REQUEST_ID}/exception/reject", json={"reason": "no"}
        )
    assert response.status_code == 409
    assert response.json()["code"] == "EXCEPTION_ACTIVE"


def test_reject_proposed_exception_with_failed_grant_tx_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _governance, _sessions = _client(monkeypatch, context=_context(), daily_used=0)
    proposed = SimpleNamespace(
        id=uuid.uuid4(),
        status=ExceptionStatus.PROPOSED,
        governance_tx_id=GOVERNANCE_TX_ID,
        version=1,
        reason=None,
        request_id=REQUEST_ID,
        mandate_onchain_version=7,
        amount=150,
        payee=PAYEE_ADDRESS,
        expiry=datetime.now(UTC),
        updated_by=None,
    )
    results = iter([proposed, GovernanceTxStatus.FAILED])

    async def scalar(*_: object, **__: object) -> object:
        return next(results)

    monkeypatch.setattr(FakeSession, "scalar", scalar)
    with client:
        response = client.post(
            f"/v1/orgs/{ORG_ID}/requests/{REQUEST_ID}/exception/reject", json={"reason": "no"}
        )
    assert response.status_code == 200
    assert response.json()["exception"]["status"] == "Rejected"
