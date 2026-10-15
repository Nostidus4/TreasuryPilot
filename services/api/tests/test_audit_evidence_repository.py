from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from treasurypilot_api.audit.evidence import (
    EvidenceBundleInvalid,
    EvidenceNotFound,
    EvidenceUnavailable,
)
from treasurypilot_api.audit.evidence_repository import (
    ReceiptResult,
    SqlAlchemyEvidenceRepository,
)
from treasurypilot_api.execution.models import Operation, Transaction
from treasurypilot_api.invoices.models import (
    PaymentApproval,
    PaymentRequest,
    RequestFlag,
)
from treasurypilot_api.treasury.models import Chain


def _row(**values: Any) -> SimpleNamespace:
    return SimpleNamespace(**values)


class _Result:
    def __init__(self, value: Any = None, values: list[Any] | None = None) -> None:
        self._value = value
        self._values = values or []

    def one_or_none(self) -> Any:
        return self._value

    def first(self) -> Any:
        return self._values[0] if self._values else None

    def mappings(self) -> _Result:
        return self

    def __iter__(self):
        return iter(self._values)


class _Begin:
    async def __aenter__(self) -> _Begin:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakeSession:
    """Route actual SQLAlchemy selects to persisted-row-shaped test records."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.request_query_was_org_scoped = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _Begin:
        return _Begin()

    async def connection(self, **_kwargs: object) -> None:
        return None

    async def execute(self, statement: Any) -> _Result:
        entity = statement.column_descriptions[0].get("entity")
        if entity is None:
            table_name = statement.get_final_froms()[0].name
            if table_name == "attestations":
                attestation = self.data.get("attestation")
                return _Result(values=[attestation] if attestation else [])
            if table_name == "validations":
                return _Result(values=self.data.get("validations", []))
            raise AssertionError(f"unexpected Core table: {table_name}")
        if entity is PaymentRequest:
            statement_text = str(statement)
            self.request_query_was_org_scoped = "payment_requests.org_id" in statement_text
            if self.data.get("hide_request"):
                return _Result()
            return _Result(
                (
                    self.data["payment"],
                    self.data.get("vendor_name"),
                    self.data["asset_symbol"],
                    self.data["asset_is_test"],
                    self.data["chain"].is_testnet,
                )
            )
        raise AssertionError(f"unexpected execute entity: {entity}")

    async def scalars(self, statement: Any) -> _Result:
        entity = statement.column_descriptions[0]["entity"]
        if entity is PaymentApproval:
            values = self.data.get("approvals", [])
        elif entity is RequestFlag:
            values = self.data.get("flags", [])
        elif entity is Operation:
            values = self.data.get("operations", [])
        elif entity is Transaction:
            values = self.data.get("transactions", [])
        elif entity is Chain:
            values = self.data.get("chains", [])
        elif entity.__name__ == "AiCall":
            values = []
        else:
            raise AssertionError(f"unexpected scalar entity: {entity}")
        return _Result(values=values)


class _FakeSessions:
    def __init__(self, data: dict[str, Any]) -> None:
        self.session = _FakeSession(data)

    def __call__(self) -> _FakeSession:
        return self.session


class _MatchingReceiptVerifier:
    async def verify(
        self,
        *,
        tx_hash: str,
        chain_id: int,
        rpc_urls: list[str],
        expected_block_number: int | None,
        expected_block_hash: str | None,
    ) -> ReceiptResult:
        assert rpc_urls == ["https://rpc.example"]
        return ReceiptResult(
            resolved=True,
            chain_id=chain_id,
            transaction_hash=tx_hash,
            block_number=expected_block_number,
            block_hash=expected_block_hash,
            status="0x1",
        )


class _UnresolvedReceiptVerifier:
    async def verify(self, **_kwargs: Any) -> ReceiptResult:
        return ReceiptResult(resolved=False)


def _fixture(*, status: str, with_transaction: bool) -> tuple[dict[str, Any], uuid.UUID, uuid.UUID]:
    organization_id, request_id = uuid.uuid4(), uuid.uuid4()
    plan_id, operation_id = uuid.uuid4(), uuid.uuid4()
    step_id = bytes.fromhex("12" * 32)
    request_hash = bytes.fromhex("34" * 32)
    plan_hash = bytes.fromhex("56" * 32)
    now = datetime.now(UTC)
    payment = _row(
        id=request_id,
        org_id=organization_id,
        current_revision=1,
        amount=Decimal("250000"),
        asset_id=uuid.uuid4(),
        chain_id=11155111,
        status=status,
        fingerprint=bytes.fromhex("78" * 32),
        invoice_hash=bytes.fromhex("9a" * 32),
        onchain_request_id=request_hash if with_transaction else None,
    )
    chain = _row(
        chain_id=11155111,
        is_testnet=True,
        rpc_urls=["https://rpc.example"],
    )
    data: dict[str, Any] = {
        "payment": payment,
        "vendor_name": "Example Vendor",
        "asset_symbol": "USDC",
        "asset_is_test": True,
        "chain": chain,
        "chains": [chain],
        "approvals": [],
        "flags": [],
        "operations": [],
        "transactions": [],
        "validations": [],
    }
    if with_transaction:
        operation = _row(
            id=operation_id,
            request_id=request_id,
            plan_step_id=uuid.uuid4(),
            step_id=step_id,
            kind="PAY",
            status="Confirmed",
            attempts=1,
            created_at=now,
        )
        tx_hash = bytes.fromhex("ab" * 32)
        block_hash = bytes.fromhex("cd" * 32)
        transaction = _row(
            id=uuid.uuid4(),
            operation_id=operation_id,
            chain_id=11155111,
            tx_hash=tx_hash,
            nonce=1,
            status="Confirmed",
            block_number=123,
            block_hash=block_hash,
            confirmations=8,
            fee_wei=Decimal("19"),
            crosscheck="Match",
            submitted_at=now,
            last_seen_pending_at=now,
            confirmed_at=now,
        )
        attestation_typed = {
            "domain": {"name": "TreasuryPilot Policy"},
            "message": {
                "requestId": "0x" + request_hash.hex(),
                "planHash": "0x" + plan_hash.hex(),
                "stepIds": ["0x" + step_id.hex()],
            },
        }
        data.update(
            {
                "operations": [operation],
                "transactions": [transaction],
                "approvals": [
                    _row(
                        typed_data={"domain": {}, "message": {"amount": "250000"}},
                        approver_address=bytes.fromhex("ef" * 20),
                        signature=b"test-only-approval-signature",
                    )
                ],
                "attestation": {
                    "id": uuid.uuid4(),
                    "plan_id": plan_id,
                    "request_id": request_hash,
                    "plan_hash": plan_hash,
                    "step_ids": [step_id],
                    "typed_data": attestation_typed,
                    "signature": b"test-only-policy-signature",
                    "policy_signer": "0x" + "ef" * 20,
                    "created_at": now,
                },
                "validations": [
                    {
                        "id": uuid.uuid4(),
                        "plan_id": plan_id,
                        "stage": "PLAN",
                        "decision": "ALLOW",
                        "reason_codes": [],
                        "checks": [{"name": "within_limit", "passed": True}],
                        "created_at": now,
                    }
                ],
            }
        )
    else:
        data["flags"] = [
            _row(
                id=uuid.uuid4(),
                code="POLICY_BLOCK",
                severity="HIGH",
                status="Open",
                acknowledged_by=None,
                acknowledged_at=None,
                ack_note="private contact data must not leave the database",
                evidence={"email": "private@example.invalid"},
                created_at=now,
            )
        ]
    return data, organization_id, request_id


def test_paid_request_exports_only_persisted_rows_and_hashes_signatures() -> None:
    data, organization_id, request_id = _fixture(status="Paid", with_transaction=True)
    sessions = _FakeSessions(data)
    repository = SqlAlchemyEvidenceRepository(
        sessions, receipt_verifier=_MatchingReceiptVerifier(), app_version="test"
    )

    bundle = asyncio.run(
        repository.export_request(organization_id=organization_id, request_id=request_id)
    )
    result = bundle.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert sessions.session.request_query_was_org_scoped
    assert result["request"]["id"] == str(request_id)
    assert result["transactions"][0]["txHash"] == "0x" + "ab" * 32
    assert result["validations"][0]["decision"] == "ALLOW"
    assert (
        result["approval"]["signatureHash"]
        == hashlib.sha256(b"test-only-approval-signature").hexdigest()
    )
    assert (
        result["attestation"]["signatureHash"]
        == hashlib.sha256(b"test-only-policy-signature").hexdigest()
    )
    serialized = json.dumps(result)
    assert "test-only-approval-signature" not in serialized
    assert "test-only-policy-signature" not in serialized
    assert result["coverage"]["plan"].startswith("unavailable_until_issue_65")


def test_blocked_request_has_no_fabricated_transaction_or_unlinked_validation() -> None:
    data, organization_id, request_id = _fixture(status="NeedsReview", with_transaction=False)
    repository = SqlAlchemyEvidenceRepository(
        _FakeSessions(data), receipt_verifier=_MatchingReceiptVerifier(), app_version="test"
    )

    bundle = asyncio.run(
        repository.export_request(organization_id=organization_id, request_id=request_id)
    )
    result = bundle.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert "transactions" not in result
    assert result["validations"] == []
    assert result["coverage"]["validations"].startswith(
        "unavailable_without_request_to_plan_link_from_issue_65"
    )
    assert result["flags"][0]["code"] == "POLICY_BLOCK"
    assert "ackNote" not in result["flags"][0]
    assert "private@example.invalid" not in json.dumps(result)


def test_paid_request_without_persisted_transaction_fails_closed() -> None:
    data, organization_id, request_id = _fixture(status="Paid", with_transaction=False)
    repository = SqlAlchemyEvidenceRepository(
        _FakeSessions(data), receipt_verifier=_MatchingReceiptVerifier(), app_version="test"
    )

    with pytest.raises(EvidenceBundleInvalid, match="no persisted transaction hash"):
        asyncio.run(
            repository.export_request(organization_id=organization_id, request_id=request_id)
        )


def test_any_unresolvable_persisted_transaction_withholds_bundle() -> None:
    data, organization_id, request_id = _fixture(status="NeedsReview", with_transaction=True)
    repository = SqlAlchemyEvidenceRepository(
        _FakeSessions(data), receipt_verifier=_UnresolvedReceiptVerifier(), app_version="test"
    )

    with pytest.raises(EvidenceBundleInvalid, match="did not resolve"):
        asyncio.run(
            repository.export_request(organization_id=organization_id, request_id=request_id)
        )


def test_request_outside_organization_is_not_found() -> None:
    data, organization_id, request_id = _fixture(status="NeedsReview", with_transaction=False)
    data["hide_request"] = True
    sessions = _FakeSessions(data)
    repository = SqlAlchemyEvidenceRepository(
        sessions, receipt_verifier=_MatchingReceiptVerifier(), app_version="test"
    )

    with pytest.raises(EvidenceNotFound):
        asyncio.run(
            repository.export_request(organization_id=organization_id, request_id=request_id)
        )
    assert sessions.session.request_query_was_org_scoped


def test_missing_chain_receipt_marks_receipt_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    from treasurypilot_api.audit.evidence_repository import JsonRpcReceiptVerifier

    verifier = JsonRpcReceiptVerifier()
    responses = iter(["0xaa36a7", None])
    monkeypatch.setattr(verifier, "_rpc", lambda *_args: next(responses))
    result = verifier._verify_url(
        "https://rpc.example",
        "0x" + "ab" * 32,
        11155111,
        None,
        None,
    )
    assert result.resolved is False


def test_invalid_route_response_exposes_invalid_status_without_a_bundle() -> None:
    from treasurypilot_api.audit.api import get_request_evidence
    from treasurypilot_api.identity.auth import AuthFailure

    class InvalidRepository:
        async def export_request(self, **_kwargs: Any) -> Any:
            raise EvidenceBundleInvalid("unresolved test transaction")

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(evidence_repository=InvalidRepository()))
    )
    member = SimpleNamespace(organization_id=uuid.uuid4(), user_id=uuid.uuid4())
    with pytest.raises(AuthFailure) as raised:
        asyncio.run(get_request_evidence(request, member, uuid.uuid4()))

    assert raised.value.status == 409
    assert raised.value.code == "EVIDENCE_INVALID"
    assert raised.value.extensions == {"evidenceStatus": "INVALID"}


def _export(
    data: dict[str, Any], organization_id: uuid.UUID, request_id: uuid.UUID, verifier: Any
) -> Any:
    repository = SqlAlchemyEvidenceRepository(
        _FakeSessions(data), receipt_verifier=verifier, app_version="test", receipt_deadline=0.2
    )
    return asyncio.run(
        repository.export_request(organization_id=organization_id, request_id=request_id)
    )


def test_in_flight_transaction_is_exported_unverified_without_an_rpc_call() -> None:
    data, organization_id, request_id = _fixture(status="NeedsReview", with_transaction=True)
    data["transactions"][0].status = "Pending"
    bundle = _export(data, organization_id, request_id, _UnresolvedReceiptVerifier())
    details = bundle.verifications[0].details
    assert details["receiptChecked"] is False
    assert details["receiptResolved"] is False


def test_paid_request_requires_every_confirmed_transaction_to_check_out() -> None:
    data, organization_id, request_id = _fixture(status="Paid", with_transaction=True)
    bad = _row(**{**vars(data["transactions"][0]), "tx_hash": bytes.fromhex("ee" * 32)})
    data["transactions"].append(bad)

    class OneRevertedVerifier(_MatchingReceiptVerifier):
        async def verify(self, **kwargs: Any) -> ReceiptResult:
            result = await super().verify(**kwargs)
            if kwargs["tx_hash"] == "0x" + "ee" * 32:
                return ReceiptResult(resolved=True, status="0x0")
            return result

    with pytest.raises(EvidenceBundleInvalid, match="lacks a persisted confirmed"):
        _export(data, organization_id, request_id, OneRevertedVerifier())


def test_rpc_outage_is_unavailable_not_invalid() -> None:
    data, organization_id, request_id = _fixture(status="Paid", with_transaction=True)

    class DownVerifier:
        async def verify(self, **_kwargs: Any) -> ReceiptResult:
            return ReceiptResult(resolved=False, unreachable=True)

    with pytest.raises(EvidenceUnavailable):
        _export(data, organization_id, request_id, DownVerifier())


def test_slow_rpc_hits_the_overall_deadline() -> None:
    data, organization_id, request_id = _fixture(status="Paid", with_transaction=True)

    class SlowVerifier:
        async def verify(self, **_kwargs: Any) -> ReceiptResult:
            await asyncio.sleep(5)
            raise AssertionError("unreachable")

    with pytest.raises(EvidenceUnavailable):
        _export(data, organization_id, request_id, SlowVerifier())


def test_attestation_for_other_steps_is_rejected() -> None:
    data, organization_id, request_id = _fixture(status="Paid", with_transaction=True)
    data["attestation"]["step_ids"] = [bytes.fromhex("99" * 32)]
    with pytest.raises(EvidenceBundleInvalid, match="covers the executed steps"):
        _export(data, organization_id, request_id, _MatchingReceiptVerifier())


def test_all_rpcs_failing_marks_the_receipt_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    import http.client

    from treasurypilot_api.audit.evidence_repository import JsonRpcReceiptVerifier

    verifier = JsonRpcReceiptVerifier()

    def broken(*_args: Any) -> ReceiptResult:
        raise http.client.IncompleteRead(b"")

    monkeypatch.setattr(verifier, "_verify_url", broken)
    result = asyncio.run(
        verifier.verify(
            tx_hash="0x" + "ab" * 32,
            chain_id=1,
            rpc_urls=["https://one.example", "https://two.example"],
            expected_block_number=None,
            expected_block_hash=None,
        )
    )
    assert result.unreachable is True


def test_http_exception_falls_back_to_the_next_rpc(monkeypatch: pytest.MonkeyPatch) -> None:
    import http.client

    from treasurypilot_api.audit.evidence_repository import JsonRpcReceiptVerifier

    verifier = JsonRpcReceiptVerifier()

    def flaky(url: str, *_args: Any) -> ReceiptResult:
        if url == "https://one.example":
            raise http.client.BadStatusLine("bad")
        return ReceiptResult(resolved=True)

    monkeypatch.setattr(verifier, "_verify_url", flaky)
    result = asyncio.run(
        verifier.verify(
            tx_hash="0x" + "ab" * 32,
            chain_id=1,
            rpc_urls=["https://one.example", "https://two.example"],
            expected_block_number=None,
            expected_block_hash=None,
        )
    )
    assert result.resolved is True


def test_rpc_redirects_are_refused() -> None:
    import threading
    import urllib.error
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from treasurypilot_api.audit.evidence_repository import JsonRpcReceiptVerifier

    hits: list[str] = []

    class Target(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return None

    target = HTTPServer(("127.0.0.1", 0), Target)

    class Redirector(Target):
        def do_POST(self) -> None:
            self.send_response(307)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/internal")
            self.end_headers()

    redirector = HTTPServer(("127.0.0.1", 0), Redirector)
    servers = (target, redirector)
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(urllib.error.HTTPError):
            JsonRpcReceiptVerifier()._rpc(
                f"http://127.0.0.1:{redirector.server_port}", 1, "eth_chainId", []
            )
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
    assert hits == []


def test_unavailable_route_response_is_503() -> None:
    from treasurypilot_api.audit.api import get_request_evidence
    from treasurypilot_api.identity.auth import AuthFailure

    class DownRepository:
        async def export_request(self, **_kwargs: Any) -> Any:
            raise EvidenceUnavailable

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(evidence_repository=DownRepository()))
    )
    member = SimpleNamespace(organization_id=uuid.uuid4(), user_id=uuid.uuid4())
    with pytest.raises(AuthFailure) as raised:
        asyncio.run(get_request_evidence(request, member, uuid.uuid4()))
    assert raised.value.status == 503
