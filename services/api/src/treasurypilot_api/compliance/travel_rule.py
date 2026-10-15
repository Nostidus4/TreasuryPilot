"""Travel Rule threshold evaluation and provider-backed, fail-closed PAY gating."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, TypeVar

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.compliance.models import TravelRuleExchange
from treasurypilot_api.compliance.screening import FIXTURE_ENVIRONMENTS
from treasurypilot_api.identity.models import uuid7

if TYPE_CHECKING:
    from treasurypilot_core.policy.context import ExecutionPlan, ValidationContext
    from treasurypilot_core.privacy import FieldCipher

PROVIDER_TIMEOUT_SECONDS = 5
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_ADDRESS = re.compile(r"^(?:0[xX])?([0-9a-fA-F]{40})$")
logger = logging.getLogger(__name__)
_T = TypeVar("_T")


class TravelRuleStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    SELF_HOSTED = "SELF_HOSTED"
    NOT_REQUIRED = "NOT_REQUIRED"
    ERROR = "ERROR"


# Decisions that never change once recorded; stale provider replies must not overwrite them.
_TERMINAL = (
    TravelRuleStatus.COMPLETED,
    TravelRuleStatus.SELF_HOSTED,
    TravelRuleStatus.NOT_REQUIRED,
)


class CounterpartyKind(StrEnum):
    VASP = "VASP"
    SELF_HOSTED = "SELF_HOSTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class TravelRuleThreshold:
    jurisdiction: str
    currency: str
    amount_minor_units: int

    def __post_init__(self) -> None:
        if not _COUNTRY.fullmatch(self.jurisdiction):
            raise ValueError("jurisdiction must be an uppercase ISO 3166-1 alpha-2 code")
        if not _CURRENCY.fullmatch(self.currency):
            raise ValueError("currency must be an uppercase ISO 4217 code")
        if (
            isinstance(self.amount_minor_units, bool)
            or not isinstance(self.amount_minor_units, int)
            or self.amount_minor_units < 0
            or self.amount_minor_units >= 10**78
        ):
            raise ValueError("threshold must be a nonnegative integer minor-unit amount")


class TravelRulePolicyError(Exception):
    """Threshold coverage is absent or ambiguous; the payment cannot be released."""


class TravelRulePolicy:
    """Exact integer threshold rules; callers supply values approved for their jurisdiction."""

    def __init__(self, rules: tuple[TravelRuleThreshold, ...]) -> None:
        self._rules = {(rule.jurisdiction, rule.currency): rule for rule in rules}
        if len(self._rules) != len(rules):
            raise ValueError("duplicate Travel Rule jurisdiction/currency threshold")

    @classmethod
    def from_json(cls, value: str) -> TravelRulePolicy:
        parsed = json.loads(value)
        rules: list[TravelRuleThreshold] = []
        for jurisdiction, currencies in parsed.items():
            for currency, threshold in currencies.items():
                if isinstance(threshold, bool) or not isinstance(threshold, int):
                    raise ValueError("Travel Rule thresholds must be integer minor-unit amounts")
                rules.append(
                    TravelRuleThreshold(
                        jurisdiction=jurisdiction.upper(),
                        currency=currency.upper(),
                        amount_minor_units=threshold,
                    )
                )
        return cls(tuple(rules))

    def applicable_threshold(
        self,
        *,
        amount_minor_units: int,
        currency: str,
        origin_jurisdiction: str,
        beneficiary_jurisdiction: str,
    ) -> int:
        """Lower of the two configured jurisdiction thresholds for the transfer currency."""
        if (
            isinstance(amount_minor_units, bool)
            or not isinstance(amount_minor_units, int)
            or amount_minor_units <= 0
            or amount_minor_units >= 10**78
        ):
            raise ValueError("amount must be a positive integer minor-unit amount")
        normalized_currency = currency.upper()
        if not _CURRENCY.fullmatch(normalized_currency):
            raise TravelRulePolicyError("Travel Rule currency is missing or invalid")
        thresholds: list[int] = []
        for jurisdiction in (origin_jurisdiction, beneficiary_jurisdiction):
            normalized_jurisdiction = jurisdiction.upper()
            if not _COUNTRY.fullmatch(normalized_jurisdiction):
                raise TravelRulePolicyError("Travel Rule jurisdiction is missing or invalid")
            rule = self._rules.get((normalized_jurisdiction, normalized_currency))
            if rule is None:
                raise TravelRulePolicyError("no Travel Rule threshold is configured for this route")
            thresholds.append(rule.amount_minor_units)
        # A route qualifies if it exceeds the configured limit in either jurisdiction.
        return min(thresholds)

    def requires_exchange(
        self,
        *,
        amount_minor_units: int,
        currency: str,
        origin_jurisdiction: str,
        beneficiary_jurisdiction: str,
    ) -> bool:
        return amount_minor_units > self.applicable_threshold(
            amount_minor_units=amount_minor_units,
            currency=currency,
            origin_jurisdiction=origin_jurisdiction,
            beneficiary_jurisdiction=beneficiary_jurisdiction,
        )


@dataclass(frozen=True, slots=True)
class TravelRuleParty:
    legal_name: str
    country: str
    address: str | None = None
    account_identifier: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.legal_name, str)
            or not self.legal_name.strip()
            or not isinstance(self.country, str)
            or not _COUNTRY.fullmatch(self.country)
        ):
            raise ValueError("Travel Rule parties require a legal name and ISO country code")
        if self.address is not None and not self.address.strip():
            raise ValueError("party address cannot be blank")
        if self.account_identifier is not None and not self.account_identifier.strip():
            raise ValueError("party account identifier cannot be blank")

    def as_dict(self) -> dict[str, str | None]:
        return {
            "legalName": self.legal_name,
            "country": self.country,
            "address": self.address,
            "accountIdentifier": self.account_identifier,
        }


@dataclass(frozen=True, slots=True)
class TravelRuleTransfer:
    payment_request_id: uuid.UUID
    onchain_request_id: bytes
    chain_id: int
    beneficiary_address: bytes
    amount_minor_units: int
    currency: str
    origin_jurisdiction: str
    beneficiary_jurisdiction: str
    originator: TravelRuleParty | None
    beneficiary: TravelRuleParty | None

    def __post_init__(self) -> None:
        if not isinstance(self.onchain_request_id, bytes) or len(self.onchain_request_id) != 32:
            raise ValueError("on-chain request id must be bytes32")
        if not isinstance(self.beneficiary_address, bytes) or len(self.beneficiary_address) != 20:
            raise ValueError("beneficiary address must be 20 bytes")
        if (
            isinstance(self.chain_id, bool)
            or not isinstance(self.chain_id, int)
            or self.chain_id <= 0
        ):
            raise ValueError("chain_id must be positive")
        if (
            isinstance(self.amount_minor_units, bool)
            or not isinstance(self.amount_minor_units, int)
            or self.amount_minor_units <= 0
            or self.amount_minor_units >= 10**78
        ):
            raise ValueError("amount must be positive")
        if not isinstance(self.origin_jurisdiction, str) or not _COUNTRY.fullmatch(
            self.origin_jurisdiction.upper()
        ):
            raise ValueError("origin jurisdiction must be a two-letter country code")
        if not isinstance(self.beneficiary_jurisdiction, str) or not _COUNTRY.fullmatch(
            self.beneficiary_jurisdiction.upper()
        ):
            raise ValueError("beneficiary jurisdiction must be a two-letter country code")
        if not isinstance(self.currency, str) or not _CURRENCY.fullmatch(self.currency.upper()):
            raise ValueError("currency must be a three-letter code")
        if self.originator is not None and (
            not isinstance(self.originator, TravelRuleParty)
            or self.originator.country != self.origin_jurisdiction.upper()
        ):
            raise ValueError("originator country must match origin jurisdiction")
        if self.beneficiary is not None and (
            not isinstance(self.beneficiary, TravelRuleParty)
            or self.beneficiary.country != self.beneficiary_jurisdiction.upper()
        ):
            raise ValueError("beneficiary country must match beneficiary jurisdiction")

    def payload(self) -> dict[str, object]:
        return {
            "onchainRequestId": self.onchain_request_id.hex(),
            "chainId": self.chain_id,
            "beneficiaryAddress": self.beneficiary_address.hex(),
            "amountMinorUnits": str(self.amount_minor_units),
            "currency": self.currency.upper(),
            "originJurisdiction": self.origin_jurisdiction.upper(),
            "beneficiaryJurisdiction": self.beneficiary_jurisdiction.upper(),
            "originator": self.originator.as_dict() if self.originator is not None else None,
            "beneficiary": self.beneficiary.as_dict() if self.beneficiary is not None else None,
        }


@dataclass(frozen=True, slots=True)
class TravelRuleOutcome:
    status: TravelRuleStatus
    provider_ref: str | None = None
    # Only meaningful for SELF_HOSTED: the adapter validated the wallet attestation.
    attestation_verified: bool = False


@dataclass(frozen=True, slots=True)
class CounterpartyAssessment:
    kind: CounterpartyKind
    # A self-hosted classification only clears PAY when the adapter has validated its attestation.
    attestation_verified: bool = False


@dataclass(frozen=True, slots=True)
class TravelRuleRecord:
    id: uuid.UUID
    organization_id: uuid.UUID
    payment_request_id: uuid.UUID
    provider: str
    status: TravelRuleStatus
    amount_minor_units: int
    currency: str
    origin_jurisdiction: str
    beneficiary_jurisdiction: str
    beneficiary_address: bytes
    chain_id: int
    payload_encrypted: str
    provider_ref: str | None
    threshold_minor_units: int | None = None


class TravelRuleProviderError(Exception):
    """The provider could not classify a counterparty or complete an exchange."""


class TravelRuleBlocked(Exception):
    """A qualifying transfer is held until its exchange or attestation is complete."""

    code = "DATA_MISSING"


class TravelRuleProvider(Protocol):
    name: str

    async def classify_counterparty(
        self, *, chain_id: int, address: bytes, jurisdiction: str
    ) -> CounterpartyAssessment: ...

    async def exchange(
        self,
        *,
        idempotency_key: str,
        transfer: TravelRuleTransfer,
    ) -> TravelRuleOutcome: ...

    async def status(self, *, provider_ref: str) -> TravelRuleOutcome: ...


class TravelRuleRepository(Protocol):
    async def get(
        self, *, organization_id: uuid.UUID, payment_request_id: uuid.UUID
    ) -> TravelRuleRecord | None: ...

    async def create(self, record: TravelRuleRecord) -> TravelRuleRecord: ...

    async def update(
        self,
        *,
        record_id: uuid.UUID,
        status: TravelRuleStatus,
        provider_ref: str | None,
    ) -> TravelRuleRecord: ...


class SqlAlchemyTravelRuleRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(
        self, *, organization_id: uuid.UUID, payment_request_id: uuid.UUID
    ) -> TravelRuleRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(TravelRuleExchange).where(
                    TravelRuleExchange.org_id == organization_id,
                    TravelRuleExchange.request_id == payment_request_id,
                )
            )
            return _record(row) if row is not None else None

    async def create(self, record: TravelRuleRecord) -> TravelRuleRecord:
        row = TravelRuleExchange(
            id=record.id,
            org_id=record.organization_id,
            request_id=record.payment_request_id,
            provider=record.provider,
            status=record.status.value,
            amount=record.amount_minor_units,
            threshold=record.threshold_minor_units,
            currency=record.currency,
            origin_jurisdiction=record.origin_jurisdiction,
            beneficiary_jurisdiction=record.beneficiary_jurisdiction,
            beneficiary_address=record.beneficiary_address,
            chain_id=record.chain_id,
            payload_encrypted=record.payload_encrypted,
            provider_ref=record.provider_ref,
        )
        try:
            async with self._sessions() as session, session.begin():
                session.add(row)
                await session.flush()
                return _record(row)
        except IntegrityError:
            # Concurrent preflight for the same request converges on the unique durable case.
            existing = await self.get(
                organization_id=record.organization_id,
                payment_request_id=record.payment_request_id,
            )
            if existing is None:
                raise
            return existing

    async def update(
        self,
        *,
        record_id: uuid.UUID,
        status: TravelRuleStatus,
        provider_ref: str | None,
    ) -> TravelRuleRecord:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(TravelRuleExchange)
                .where(TravelRuleExchange.id == record_id)
                .with_for_update()
            )
            if row is None:
                raise TravelRuleBlocked("Travel Rule case disappeared while updating")
            # Concurrent retries may receive stale PENDING/ERROR replies after another
            # request has committed a final decision. Never let an old reply reopen a held case.
            if TravelRuleStatus(row.status) in _TERMINAL:
                return _record(row)
            row.status = status.value
            row.provider_ref = provider_ref or row.provider_ref
            await session.flush()
            return _record(row)


class UnconfiguredTravelRuleProvider:
    """No vendor is selected; every qualifying transfer remains blocked."""

    name = "unconfigured"

    async def classify_counterparty(
        self, *, chain_id: int, address: bytes, jurisdiction: str
    ) -> CounterpartyAssessment:
        raise TravelRuleProviderError("no Travel Rule provider is configured")

    async def exchange(
        self, *, idempotency_key: str, transfer: TravelRuleTransfer
    ) -> TravelRuleOutcome:
        raise TravelRuleProviderError("no Travel Rule provider is configured")

    async def status(self, *, provider_ref: str) -> TravelRuleOutcome:
        raise TravelRuleProviderError("no Travel Rule provider is configured")


class FixtureTravelRuleProvider:
    """TEST DATA adapter; unknown counterparties and exchanges remain pending by default."""

    name = "fixture-test"

    def __init__(
        self,
        counterparties: Mapping[tuple[int, bytes], CounterpartyAssessment] | None = None,
        outcomes: Mapping[str, TravelRuleOutcome] | None = None,
    ) -> None:
        self._counterparties = dict(counterparties or {})
        self._outcomes = dict(outcomes or {})

    async def classify_counterparty(
        self, *, chain_id: int, address: bytes, jurisdiction: str
    ) -> CounterpartyAssessment:
        return self._counterparties.get(
            (chain_id, address), CounterpartyAssessment(CounterpartyKind.UNKNOWN)
        )

    async def exchange(
        self, *, idempotency_key: str, transfer: TravelRuleTransfer
    ) -> TravelRuleOutcome:
        return self._outcomes.get(idempotency_key, TravelRuleOutcome(TravelRuleStatus.PENDING))

    async def status(self, *, provider_ref: str) -> TravelRuleOutcome:
        return TravelRuleOutcome(TravelRuleStatus.PENDING, provider_ref)


class TravelRuleService:
    def __init__(
        self,
        repository: TravelRuleRepository,
        provider: TravelRuleProvider,
        policy: TravelRulePolicy,
        cipher: FieldCipher | None,
        *,
        timeout_seconds: float = PROVIDER_TIMEOUT_SECONDS,
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._policy = policy
        self._cipher = cipher
        self._timeout_seconds = timeout_seconds

    async def require_exchange_complete(
        self, *, organization_id: uuid.UUID, transfer: TravelRuleTransfer
    ) -> TravelRuleRecord:
        """Return the final case: below-threshold, attested self-hosted, or completed exchange."""
        try:
            existing = await self._repository.get(
                organization_id=organization_id,
                payment_request_id=transfer.payment_request_id,
            )
        except Exception as error:
            logger.warning("travel_rule_repository_failed", extra={"error": type(error).__name__})
            raise TravelRuleBlocked("Travel Rule state is unavailable") from None

        if existing is None:
            try:
                threshold = self._policy.applicable_threshold(
                    amount_minor_units=transfer.amount_minor_units,
                    currency=transfer.currency,
                    origin_jurisdiction=transfer.origin_jurisdiction,
                    beneficiary_jurisdiction=transfer.beneficiary_jurisdiction,
                )
            except (TravelRulePolicyError, ValueError) as error:
                raise TravelRuleBlocked("Travel Rule threshold policy is unavailable") from error
            qualifies = transfer.amount_minor_units > threshold
            if qualifies and (transfer.originator is None or transfer.beneficiary is None):
                raise TravelRuleBlocked("qualifying transfers require both parties' data")
            # The decision is persisted with its threshold so retries honor it even if the
            # configured thresholds change later.
            existing = await self._new_record(
                organization_id,
                transfer,
                status=TravelRuleStatus.PENDING if qualifies else TravelRuleStatus.NOT_REQUIRED,
                threshold=threshold,
            )
        # A concurrent first preflight may have won the unique request key with
        # different party data; never send this caller's payload under that case.
        self._assert_same_payload(existing, transfer)
        if existing.status == TravelRuleStatus.NOT_REQUIRED:
            return existing
        if existing.provider != self._provider.name:
            raise TravelRuleBlocked("Travel Rule case belongs to a different provider")
        if existing.status in _TERMINAL:
            return existing

        if existing.status == TravelRuleStatus.PENDING and existing.provider_ref:
            outcome = await self._call_provider(
                "travel_rule_status_failed",
                lambda: self._provider.status(provider_ref=existing.provider_ref or ""),
            )
        else:
            outcome = await self._start_or_classify(
                existing=existing,
                organization_id=organization_id,
                transfer=transfer,
            )
        try:
            outcome_status = TravelRuleStatus(outcome.status)
        except ValueError:
            await self._save_status(existing.id, TravelRuleStatus.ERROR, outcome.provider_ref)
            raise TravelRuleBlocked("Travel Rule provider returned an unknown status") from None
        if outcome_status == TravelRuleStatus.SELF_HOSTED:
            if not outcome.attestation_verified:
                await self._save_status(existing.id, TravelRuleStatus.PENDING, outcome.provider_ref)
                raise TravelRuleBlocked("self-hosted wallet attestation is incomplete")
            return await self._save_status(
                existing.id, TravelRuleStatus.SELF_HOSTED, outcome.provider_ref
            )
        if outcome_status == TravelRuleStatus.ERROR:
            await self._save_status(existing.id, TravelRuleStatus.ERROR, outcome.provider_ref)
            raise TravelRuleBlocked("Travel Rule provider rejected the exchange")
        if outcome_status != TravelRuleStatus.COMPLETED:
            await self._save_status(existing.id, TravelRuleStatus.PENDING, outcome.provider_ref)
            raise TravelRuleBlocked("Travel Rule exchange is pending")
        return await self._save_status(
            existing.id, TravelRuleStatus.COMPLETED, outcome.provider_ref
        )

    async def _new_record(
        self,
        organization_id: uuid.UUID,
        transfer: TravelRuleTransfer,
        *,
        status: TravelRuleStatus,
        threshold: int,
    ) -> TravelRuleRecord:
        if self._cipher is None:
            raise TravelRuleBlocked("Travel Rule encryption is unavailable")
        record_id = uuid7()
        try:
            encrypted = self._cipher.encrypt(
                json.dumps(transfer.payload(), sort_keys=True, separators=(",", ":")).encode(),
                context=_cipher_context(organization_id, record_id),
            )
        except Exception as error:
            logger.warning("travel_rule_encryption_failed", extra={"error": type(error).__name__})
            raise TravelRuleBlocked("Travel Rule party data could not be encrypted") from None
        record = TravelRuleRecord(
            id=record_id,
            organization_id=organization_id,
            payment_request_id=transfer.payment_request_id,
            provider=self._provider.name,
            status=status,
            amount_minor_units=transfer.amount_minor_units,
            currency=transfer.currency.upper(),
            origin_jurisdiction=transfer.origin_jurisdiction.upper(),
            beneficiary_jurisdiction=transfer.beneficiary_jurisdiction.upper(),
            beneficiary_address=transfer.beneficiary_address,
            chain_id=transfer.chain_id,
            payload_encrypted=encrypted,
            provider_ref=None,
            threshold_minor_units=threshold,
        )
        try:
            return await self._repository.create(record)
        except Exception as error:
            logger.warning("travel_rule_record_failed", extra={"error": type(error).__name__})
            raise TravelRuleBlocked("Travel Rule state could not be saved") from None

    async def _start_or_classify(
        self,
        *,
        existing: TravelRuleRecord,
        organization_id: uuid.UUID,
        transfer: TravelRuleTransfer,
    ) -> TravelRuleOutcome:
        assessment = await self._call_provider(
            "travel_rule_classification_failed",
            lambda: self._provider.classify_counterparty(
                chain_id=transfer.chain_id,
                address=transfer.beneficiary_address,
                jurisdiction=transfer.beneficiary_jurisdiction.upper(),
            ),
        )
        if assessment.kind == CounterpartyKind.SELF_HOSTED:
            # Attestation and persistence are handled with provider status replies by the caller.
            return TravelRuleOutcome(
                TravelRuleStatus.SELF_HOSTED, attestation_verified=assessment.attestation_verified
            )
        if assessment.kind != CounterpartyKind.VASP:
            await self._save_status(existing.id, TravelRuleStatus.ERROR, None)
            raise TravelRuleBlocked("counterparty classification is unavailable")
        return await self._call_provider(
            "travel_rule_exchange_failed",
            lambda: self._provider.exchange(
                idempotency_key=f"{organization_id}:{transfer.payment_request_id}:{existing.id}",
                transfer=transfer,
            ),
        )

    async def _call_provider(self, event: str, operation: Callable[[], Awaitable[_T]]) -> _T:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                outcome = await operation()
        except Exception as error:
            logger.warning(
                event, extra={"provider": self._provider.name, "error": type(error).__name__}
            )
            raise TravelRuleBlocked("Travel Rule provider is unavailable") from None
        return outcome

    async def _save_status(
        self, record_id: uuid.UUID, status: TravelRuleStatus, provider_ref: str | None
    ) -> TravelRuleRecord:
        try:
            return await self._repository.update(
                record_id=record_id, status=status, provider_ref=provider_ref
            )
        except Exception as error:
            logger.warning("travel_rule_update_failed", extra={"error": type(error).__name__})
            raise TravelRuleBlocked("Travel Rule state could not be updated") from None

    def _assert_same_payload(self, record: TravelRuleRecord, transfer: TravelRuleTransfer) -> None:
        if self._cipher is None:
            raise TravelRuleBlocked("Travel Rule encryption is unavailable")
        try:
            plaintext = self._cipher.decrypt(
                record.payload_encrypted,
                context=_cipher_context(record.organization_id, record.id),
            )
            stored = json.loads(plaintext)
        except Exception:
            raise TravelRuleBlocked("Travel Rule payload cannot be verified") from None
        if stored != transfer.payload():
            raise TravelRuleBlocked("Travel Rule data changed after exchange started")


async def travel_rule_before_pay(
    plan: ExecutionPlan,
    context: ValidationContext,
    *,
    service: TravelRuleService,
    organization_id: uuid.UUID,
    transfer: TravelRuleTransfer | None,
) -> ValidationContext:
    """Perform Travel Rule preflight for PAY plans and encode missing/error as a hard block."""
    pay_steps = [step for step in plan.steps if step.action == "PAY"]
    if not pay_steps:
        return context
    if (
        transfer is None
        or transfer.onchain_request_id != plan.request_id
        or transfer.chain_id != plan.chain_id
    ):
        return context.model_copy(update={"travel_rule_clear": False})
    try:
        addresses = {normalize_address(step.to) for step in pay_steps}
    except ValueError:
        return context.model_copy(update={"travel_rule_clear": False})
    if addresses != {transfer.beneficiary_address}:
        return context.model_copy(update={"travel_rule_clear": False})
    try:
        await service.require_exchange_complete(
            organization_id=organization_id,
            transfer=transfer,
        )
    except TravelRuleBlocked:
        return context.model_copy(update={"travel_rule_clear": False})
    except Exception as error:
        logger.warning("travel_rule_preflight_failed", extra={"error": type(error).__name__})
        return context.model_copy(update={"travel_rule_clear": False})
    return context.model_copy(update={"travel_rule_clear": True})


def build_travel_rule_service(
    environment: str,
    sessions: async_sessionmaker[AsyncSession],
    *,
    thresholds_json: str,
    cipher: FieldCipher | None,
) -> TravelRuleService:
    provider: TravelRuleProvider
    if environment.casefold() in FIXTURE_ENVIRONMENTS:
        provider = FixtureTravelRuleProvider()
    else:
        logger.error("travel_rule_provider_unconfigured", extra={"environment": environment})
        provider = UnconfiguredTravelRuleProvider()
    return TravelRuleService(
        SqlAlchemyTravelRuleRepository(sessions),
        provider,
        TravelRulePolicy.from_json(thresholds_json),
        cipher,
    )


def normalize_address(address: str | bytes) -> bytes:
    if isinstance(address, bytes):
        if len(address) != 20:
            raise ValueError("beneficiary address must be 20 bytes")
        return address
    match = _ADDRESS.fullmatch(address)
    if match is None:
        raise ValueError("beneficiary address must be 20 bytes")
    return bytes.fromhex(match.group(1))


def _cipher_context(organization_id: uuid.UUID, record_id: uuid.UUID) -> bytes:
    return f"travel_rule_exchanges.payload_encrypted:{organization_id}:{record_id}".encode()


def _record(row: TravelRuleExchange) -> TravelRuleRecord:
    return TravelRuleRecord(
        id=row.id,
        organization_id=row.org_id,
        payment_request_id=row.request_id,
        provider=row.provider,
        status=TravelRuleStatus(row.status),
        amount_minor_units=int(row.amount),
        currency=row.currency,
        origin_jurisdiction=row.origin_jurisdiction,
        beneficiary_jurisdiction=row.beneficiary_jurisdiction,
        beneficiary_address=row.beneficiary_address,
        chain_id=row.chain_id,
        payload_encrypted=row.payload_encrypted,
        provider_ref=row.provider_ref,
        threshold_minor_units=int(row.threshold) if row.threshold is not None else None,
    )
