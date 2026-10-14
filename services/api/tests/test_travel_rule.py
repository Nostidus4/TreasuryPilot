from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import replace
from typing import cast
from urllib.request import Request as HttpRequest

import pytest
from pydantic import SecretStr, ValidationError

from treasurypilot_api.compliance.travel_rule import (
    CounterpartyAssessment,
    CounterpartyKind,
    HttpTravelRuleProvider,
    TravelRuleBlocked,
    TravelRuleOutcome,
    TravelRuleParty,
    TravelRulePolicy,
    TravelRulePolicyError,
    TravelRuleProvider,
    TravelRuleProviderError,
    TravelRuleRecord,
    TravelRuleRepository,
    TravelRuleService,
    TravelRuleStatus,
    TravelRuleThreshold,
    TravelRuleTransfer,
    build_travel_rule_service,
    travel_rule_before_pay,
)
from treasurypilot_api.config import Settings
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import Action, ExecutionPlan, PlanStep, ValidationContext
from treasurypilot_core.privacy import FieldCipher, FieldEncryptionKey

ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000010")
REQUEST_ID = uuid.UUID("00000000-0000-7000-8000-000000000020")
BENEFICIARY_ADDRESS = bytes.fromhex("ab" * 20)
ONCHAIN_REQUEST_ID = bytes.fromhex("cd" * 32)
POLICY = TravelRulePolicy(
    (
        TravelRuleThreshold("US", "USD", 100),
        TravelRuleThreshold("GB", "USD", 100),
    )
)
CIPHER = FieldCipher(FieldEncryptionKey.from_base64("A" * 43))


class MemoryRepository:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, TravelRuleRecord] = {}

    async def get(
        self, *, organization_id: uuid.UUID, payment_request_id: uuid.UUID
    ) -> TravelRuleRecord | None:
        return next(
            (
                row
                for row in self.rows.values()
                if row.organization_id == organization_id
                and row.payment_request_id == payment_request_id
            ),
            None,
        )

    async def create(self, record: TravelRuleRecord) -> TravelRuleRecord:
        self.rows[record.id] = record
        return record

    async def update(
        self,
        *,
        record_id: uuid.UUID,
        status: TravelRuleStatus,
        provider_ref: str | None,
    ) -> TravelRuleRecord:
        row = replace(self.rows[record_id], status=status, provider_ref=provider_ref)
        self.rows[record_id] = row
        return row


class FakeProvider:
    name = "test-provider"

    def __init__(
        self,
        *,
        outcomes: list[TravelRuleOutcome] | None = None,
        assessment: CounterpartyAssessment | None = None,
    ) -> None:
        self.outcomes = list(
            outcomes or [TravelRuleOutcome(TravelRuleStatus.PENDING, "exchange-1")]
        )
        self.assessment = assessment or CounterpartyAssessment(CounterpartyKind.VASP)
        self.classifications = 0
        self.exchanges = 0
        self.status_checks = 0

    async def classify_counterparty(
        self, *, chain_id: int, address: bytes, jurisdiction: str
    ) -> CounterpartyAssessment:
        self.classifications += 1
        return self.assessment

    async def exchange(
        self, *, idempotency_key: str, transfer: TravelRuleTransfer
    ) -> TravelRuleOutcome:
        self.exchanges += 1
        return self.outcomes.pop(0)

    async def status(self, *, provider_ref: str) -> TravelRuleOutcome:
        self.status_checks += 1
        return self.outcomes.pop(0)


class BrokenProvider(FakeProvider):
    async def classify_counterparty(
        self, *, chain_id: int, address: bytes, jurisdiction: str
    ) -> CounterpartyAssessment:
        raise TravelRuleProviderError("provider offline")


def transfer() -> TravelRuleTransfer:
    return TravelRuleTransfer(
        payment_request_id=REQUEST_ID,
        onchain_request_id=ONCHAIN_REQUEST_ID,
        chain_id=1,
        beneficiary_address=BENEFICIARY_ADDRESS,
        amount_minor_units=101,
        currency="USD",
        origin_jurisdiction="US",
        beneficiary_jurisdiction="GB",
        originator=TravelRuleParty("Treasury Inc", "US", "1 Main Street"),
        beneficiary=TravelRuleParty("Beneficiary Ltd", "GB", "2 High Street"),
    )


def service(
    provider: TravelRuleProvider | None = None,
    repository: TravelRuleRepository | None = None,
    *,
    cipher: FieldCipher | None = CIPHER,
) -> TravelRuleService:
    return TravelRuleService(
        repository or MemoryRepository(), provider or FakeProvider(), POLICY, cipher
    )


def test_thresholds_use_integer_minor_units_and_fail_closed_on_missing_route() -> None:
    assert not POLICY.requires_exchange(
        amount_minor_units=100,
        currency="USD",
        origin_jurisdiction="US",
        beneficiary_jurisdiction="GB",
    )
    assert POLICY.requires_exchange(
        amount_minor_units=101,
        currency="USD",
        origin_jurisdiction="US",
        beneficiary_jurisdiction="GB",
    )
    with pytest.raises(TravelRulePolicyError):
        POLICY.requires_exchange(
            amount_minor_units=101,
            currency="USD",
            origin_jurisdiction="US",
            beneficiary_jurisdiction="CA",
        )


def test_threshold_configuration_requires_country_currency_and_integer_amounts() -> None:
    settings = Settings(travel_rule_thresholds='{"US":{"USD":30000},"GB":{"USD":30000}}')
    assert settings.travel_rule_thresholds == '{"GB": {"USD": 30000}, "US": {"USD": 30000}}'
    with pytest.raises(ValidationError):
        Settings(travel_rule_thresholds='{"US":{"USD":30000.5}}')


def test_travel_rule_http_provider_configuration_requires_paired_https_credentials() -> None:
    with pytest.raises(ValidationError):
        Settings(travel_rule_provider_url="https://gateway.example")
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            travel_rule_provider_url="http://gateway.example",
            travel_rule_provider_api_key=SecretStr("provider-secret"),
        )
    configured = Settings(
        environment="production",
        travel_rule_provider_url="https://gateway.example/api/",
        travel_rule_provider_api_key=SecretStr("provider-secret"),
    )
    assert configured.travel_rule_provider_url == "https://gateway.example/api/"


def test_pending_exchange_holds_until_provider_confirms_completion() -> None:
    repository = MemoryRepository()
    provider = FakeProvider(
        outcomes=[
            TravelRuleOutcome(TravelRuleStatus.PENDING, "exchange-1"),
            TravelRuleOutcome(TravelRuleStatus.COMPLETED, "exchange-1"),
        ]
    )
    travel_service = service(provider, repository)

    with pytest.raises(TravelRuleBlocked):
        asyncio.run(
            travel_service.require_exchange_complete(organization_id=ORG_ID, transfer=transfer())
        )
    pending = next(iter(repository.rows.values()))
    assert pending.status == TravelRuleStatus.PENDING
    assert "Treasury Inc" not in pending.payload_encrypted
    assert "Beneficiary Ltd" not in pending.payload_encrypted

    completed = asyncio.run(
        travel_service.require_exchange_complete(organization_id=ORG_ID, transfer=transfer())
    )
    assert completed is not None and completed.status == TravelRuleStatus.COMPLETED
    assert provider.exchanges == 1
    assert provider.status_checks == 1


def test_provider_failure_and_missing_encryption_fail_closed() -> None:
    repository = MemoryRepository()
    with pytest.raises(TravelRuleBlocked):
        asyncio.run(
            service(BrokenProvider(), repository).require_exchange_complete(
                organization_id=ORG_ID, transfer=transfer()
            )
        )
    assert next(iter(repository.rows.values())).status == TravelRuleStatus.PENDING

    no_cipher_repository = MemoryRepository()
    with pytest.raises(TravelRuleBlocked):
        asyncio.run(
            service(FakeProvider(), no_cipher_repository, cipher=None).require_exchange_complete(
                organization_id=ORG_ID, transfer=transfer()
            )
        )
    assert no_cipher_repository.rows == {}


def test_configured_http_provider_holds_then_releases_only_after_completion() -> None:
    calls: list[tuple[str, str, str | None, dict[str, object] | None]] = []
    exchange_started = False

    def send(request: HttpRequest, timeout: float) -> bytes:
        nonlocal exchange_started
        body = json.loads(cast(bytes, request.data)) if request.data is not None else None
        calls.append(
            (
                request.get_method(),
                request.full_url.removeprefix("https://gateway.example"),
                request.get_header("Idempotency-key"),
                body,
            )
        )
        assert request.get_header("Authorization") == "Bearer test-secret"
        assert timeout == 5
        if request.full_url.endswith("/v1/counterparties/classify"):
            response = {"kind": "VASP"}
        elif request.full_url.endswith("/v1/exchanges"):
            exchange_started = True
            response = {"status": "PENDING", "providerRef": "case-123"}
        elif request.full_url.endswith("/v1/exchanges/case-123") and exchange_started:
            response = {"status": "COMPLETED", "providerRef": "case-123"}
        else:
            raise AssertionError(f"unexpected gateway request: {request.full_url}")
        return json.dumps(response).encode()

    repository = MemoryRepository()
    gateway = HttpTravelRuleProvider(
        base_url="https://gateway.example", api_key="test-secret", request_sender=send
    )
    travel_service = service(gateway, repository)
    with pytest.raises(TravelRuleBlocked):
        asyncio.run(
            travel_service.require_exchange_complete(organization_id=ORG_ID, transfer=transfer())
        )
    assert next(iter(repository.rows.values())).status == TravelRuleStatus.PENDING

    completed = asyncio.run(
        travel_service.require_exchange_complete(organization_id=ORG_ID, transfer=transfer())
    )
    assert completed is not None and completed.status == TravelRuleStatus.COMPLETED
    assert [call[:2] for call in calls] == [
        ("POST", "/v1/counterparties/classify"),
        ("POST", "/v1/exchanges"),
        ("GET", "/v1/exchanges/case-123"),
    ]
    assert calls[1][2]
    assert calls[1][3] == transfer().payload()


def test_production_service_uses_the_configured_http_provider() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    configured = build_travel_rule_service(
        "production",
        async_sessionmaker(),
        thresholds_json="{}",
        cipher=None,
        provider_url="https://gateway.example",
        provider_api_key="test-secret",
    )

    assert isinstance(configured._provider, HttpTravelRuleProvider)


def test_below_threshold_does_not_require_party_data_but_qualifying_transfer_does() -> None:
    repository = MemoryRepository()
    below_threshold = replace(transfer(), amount_minor_units=100, originator=None, beneficiary=None)
    result = asyncio.run(
        service(FakeProvider(), repository).require_exchange_complete(
            organization_id=ORG_ID, transfer=below_threshold
        )
    )
    assert result is None and repository.rows == {}

    missing_party = replace(transfer(), originator=None)
    with pytest.raises(TravelRuleBlocked):
        asyncio.run(
            service(FakeProvider(), repository).require_exchange_complete(
                organization_id=ORG_ID, transfer=missing_party
            )
        )
    assert repository.rows == {}


@pytest.mark.parametrize(
    ("attested", "blocked"),
    [(False, True), (True, False)],
)
def test_self_hosted_wallet_requires_verified_attestation(attested: bool, blocked: bool) -> None:
    provider = FakeProvider(
        assessment=CounterpartyAssessment(CounterpartyKind.SELF_HOSTED, attested)
    )
    if blocked:
        with pytest.raises(TravelRuleBlocked):
            asyncio.run(
                service(provider).require_exchange_complete(
                    organization_id=ORG_ID, transfer=transfer()
                )
            )
    else:
        record = asyncio.run(
            service(provider).require_exchange_complete(organization_id=ORG_ID, transfer=transfer())
        )
        assert record is not None and record.status == TravelRuleStatus.SELF_HOSTED


def test_pre_pay_context_stays_blocked_while_exchange_is_pending() -> None:
    provider = FakeProvider(
        outcomes=[
            TravelRuleOutcome(TravelRuleStatus.PENDING, "exchange-1"),
            TravelRuleOutcome(TravelRuleStatus.COMPLETED, "exchange-1"),
        ]
    )
    travel_service = service(provider)
    plan = ExecutionPlan(
        request_id=ONCHAIN_REQUEST_ID,
        treasury="0x" + "11" * 20,
        chain_id=1,
        steps=[
            PlanStep(
                seq=0,
                step_id=bytes.fromhex("ef" * 32),
                action=Action.PAY,
                from_wallet="0x" + "22" * 20,
                to="0x" + BENEFICIARY_ADDRESS.hex(),
                asset="0x" + "55" * 20,
                amount=BaseUnits(101),
            )
        ],
        planner_source="DETERMINISTIC",
        evidence_ids=[],
    )
    context = ValidationContext.model_construct(travel_rule_clear=False)

    pending = asyncio.run(
        travel_rule_before_pay(
            plan,
            context,
            service=travel_service,
            organization_id=ORG_ID,
            transfer=transfer(),
        )
    )
    assert pending.travel_rule_clear is False
    completed = asyncio.run(
        travel_rule_before_pay(
            plan,
            context,
            service=travel_service,
            organization_id=ORG_ID,
            transfer=transfer(),
        )
    )
    assert completed.travel_rule_clear is True
