from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import SessionAccess, UserRecord
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.main import create_app
from treasurypilot_api.mandate import pause
from treasurypilot_api.mandate.models import BackendPause, OnchainPauseStatus
from treasurypilot_api.treasury.models import TreasuryStatus

ORG_ID = uuid.UUID("00000000-0000-4000-8000-000000000111")
TREASURY_ID = uuid.UUID("00000000-0000-4000-8000-000000000222")
USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000444")
MODULE = bytes.fromhex("11" * 20)
URL = f"/v1/orgs/{ORG_ID}/treasuries/{TREASURY_ID}"


class FakeSession:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def begin(self) -> FakeSession:
        return self

    async def scalar(self, *_: object, **__: object) -> None:
        return None  # no guardian setup

    async def get(self, *_: object) -> BackendPause | None:
        return self.state.get("row")

    def add(self, row: BackendPause) -> None:
        self.state["row"] = row


class FakeGovernance:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create(self, **fields: Any) -> dict[str, Any]:
        self.calls.append(fields)
        return {"governanceTx": {"id": str(uuid.uuid4())}}


def _client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    role: str,
    row: BackendPause | None = None,
    step_up_age: timedelta = timedelta(0),
    **settings: Any,
) -> tuple[TestClient, dict[str, Any], FakeGovernance]:
    state: dict[str, Any] = {"row": row}
    treasury = SimpleNamespace(
        name="Acme Treasury", module_address=MODULE, status=TreasuryStatus.READY
    )

    async def load(*_: object) -> object:
        return treasury

    async def no_pending(*_: object) -> list[pause.PendingTransaction]:
        return [
            pause.PendingTransaction(
                operation_id="op-1", request_id="req-1", kind="PAY", status="NotSubmitted"
            )
        ]

    async def upsert(*_: object) -> OnchainPauseStatus:
        if state["row"] is None:
            state["row"] = _paused_row(OnchainPauseStatus.REQUESTED)
        return cast(OnchainPauseStatus, state["row"].onchain_status)

    async def safe(*_: object) -> str:
        return "0x" + "22" * 20

    async def no_audit(*_: object, **__: object) -> None:
        return None

    async def org_name(*_: object) -> str:
        return "Acme Treasury"

    monkeypatch.setattr(pause, "_load", load)
    monkeypatch.setattr(pause, "_org_name", org_name)
    monkeypatch.setattr(pause, "_pending_operations", no_pending)
    monkeypatch.setattr(pause, "_upsert_pause", upsert)
    monkeypatch.setattr(pause, "_guardian_safe", safe)
    monkeypatch.setattr(pause, "log_audit_event", no_audit)
    app = create_app(settings=Settings(environment="local", **settings))
    app.state.request_sessions = lambda: FakeSession(state)
    governance = FakeGovernance()
    app.state.governance_service = governance

    async def member(organization_id: uuid.UUID) -> MemberAccess:
        access = SessionAccess(
            user=UserRecord(USER_ID, "u@example.test", None, "active"),
            session_id=uuid.uuid4(),
            step_up_at=datetime.now(UTC) - step_up_age,
        )
        return MemberAccess(access=access, organization_id=organization_id, roles=frozenset({role}))

    app.dependency_overrides[require_member] = member
    return TestClient(app), state, governance


def _paused_row(status: OnchainPauseStatus) -> BackendPause:
    return BackendPause(
        treasury_id=TREASURY_ID, org_id=ORG_ID, paused=True, reason="x", onchain_status=status
    )


def test_pause_without_sentinel_sets_flag_and_returns_guardian_tx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, state, _ = _client(monkeypatch, role="Guardian")
    response = client.post(f"{URL}/pause", json={"reason": " fire "})
    assert response.status_code == 202
    body = response.json()
    assert body["backendPaused"] is True
    assert body["onchainStatus"] == "Requested"  # requested, not yet effective
    assert body["onchain"] == "GUARDIAN_SAFE_TX_REQUIRED"
    assert body["guardianTx"]["call"]["to"] == "0x" + MODULE.hex()
    assert body["guardianTx"]["call"]["data"] == "0x8456cb59"
    assert body["pendingTransactions"][0]["operationId"] == "op-1"
    assert body["guardianTx"]["safeAddress"] == "0x" + "22" * 20
    assert state["row"].paused


def test_pause_with_sentinel_reports_submission(monkeypatch: pytest.MonkeyPatch) -> None:
    client, state, _ = _client(
        monkeypatch, role="Owner", signer_url="http://signer", signer_shared_secret="s"
    )

    async def sentinel(*_: object) -> dict[str, Any]:
        return {"txHash": "0x" + "ab" * 32, "alreadyPaused": False}

    monkeypatch.setattr(pause, "_call_sentinel", sentinel)
    body = client.post(f"{URL}/pause", json={"reason": "r"}).json()
    assert body["onchain"] == "SENTINEL_SUBMITTED" and body["sentinelTxHash"] == "0x" + "ab" * 32
    assert body["guardianTx"] is None and state["row"].paused


def test_sentinel_failure_keeps_flag_and_falls_back_to_safe_tx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, state, _ = _client(monkeypatch, role="Owner")

    async def broken(*_: object) -> dict[str, Any]:
        return {"error": True}

    monkeypatch.setattr(pause, "_call_sentinel", broken)
    body = client.post(f"{URL}/pause", json={"reason": "r"}).json()
    assert body["onchain"] == "SENTINEL_FAILED" and "guardianTx" in body and state["row"].paused


def test_status_distinguishes_requested_from_effective(monkeypatch: pytest.MonkeyPatch) -> None:
    client, *_ = _client(monkeypatch, role="Auditor", row=_paused_row(OnchainPauseStatus.REQUESTED))
    body = client.get(f"{URL}/pause").json()
    assert (body["backendPaused"], body["onchainStatus"], body["effective"]) == (
        True,
        "Requested",
        False,
    )
    client, *_ = _client(monkeypatch, role="Auditor", row=_paused_row(OnchainPauseStatus.EFFECTIVE))
    assert client.get(f"{URL}/pause").json()["effective"] is True


def test_guardian_cannot_resume_or_revoke(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, governance = _client(
        monkeypatch, role="Guardian", row=_paused_row(OnchainPauseStatus.EFFECTIVE)
    )
    assert client.post(f"{URL}/resume-tx").status_code == 403
    assert client.post(f"{URL}/revoke-tx", json={"confirmName": "Acme Treasury"}).status_code == 403
    assert governance.calls == []


def test_owner_resume_builds_resume_call_only_when_pause_is_effective(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, governance = _client(
        monkeypatch, role="Owner", row=_paused_row(OnchainPauseStatus.REQUESTED)
    )
    assert client.post(f"{URL}/resume-tx").json()["code"] == "PAUSE_NOT_EFFECTIVE"
    client, _, governance = _client(
        monkeypatch, role="Owner", row=_paused_row(OnchainPauseStatus.EFFECTIVE)
    )
    assert client.post(f"{URL}/resume-tx").status_code == 201
    call = governance.calls[0]["calls"][0]
    assert call.data.hex() == "046f7da2" and call.to == MODULE


def test_revoke_requires_the_exact_confirmation_name(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, governance = _client(monkeypatch, role="Owner")
    wrong = client.post(f"{URL}/revoke-tx", json={"confirmName": "acme treasury"})
    assert wrong.status_code == 422 and governance.calls == []
    ok = client.post(f"{URL}/revoke-tx", json={"confirmName": "Acme Treasury"})
    assert ok.status_code == 201
    assert governance.calls[0]["calls"][0].data.hex() == "b6549f75"


def test_stale_step_up_is_refused_on_resume_and_revoke(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, governance = _client(
        monkeypatch,
        role="Owner",
        row=_paused_row(OnchainPauseStatus.EFFECTIVE),
        step_up_age=timedelta(hours=1),
    )
    for response in (
        client.post(f"{URL}/resume-tx"),
        client.post(f"{URL}/revoke-tx", json={"confirmName": "Acme Treasury"}),
        client.post(f"{URL}/pause/cancel"),
    ):
        assert response.status_code == 403 and response.json()["code"] == "STEP_UP_REQUIRED"
    assert governance.calls == []


def test_missing_guardian_safe_is_a_clear_409(monkeypatch: pytest.MonkeyPatch) -> None:
    client, state, _ = _client(monkeypatch, role="Owner")

    async def no_safe(*_: object) -> None:
        return None

    monkeypatch.setattr(pause, "_guardian_safe", no_safe)
    response = client.post(f"{URL}/pause", json={"reason": "r"})
    assert response.status_code == 409 and response.json()["code"] == "GUARDIAN_SAFE_MISSING"


def test_status_returns_guardian_tx_while_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    client, *_ = _client(monkeypatch, role="Auditor", row=_paused_row(OnchainPauseStatus.REQUESTED))
    assert client.get(f"{URL}/pause").json()["guardianTx"]["call"]["data"] == "0x8456cb59"
    client, *_ = _client(monkeypatch, role="Auditor", row=_paused_row(OnchainPauseStatus.EFFECTIVE))
    assert client.get(f"{URL}/pause").json()["guardianTx"] is None


def test_signer_url_must_be_http() -> None:
    with pytest.raises(ValueError, match="http"):
        Settings(environment="local", signer_url="file:///etc/passwd")
    assert Settings(environment="local", signer_url="").signer_url is None
