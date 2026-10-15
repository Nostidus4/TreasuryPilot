"""Versioned request evidence bundles.

The repository is deliberately an adapter: execution tables and chain receipt
lookup are owned by the execution integration. Until that integration exists,
the API fails closed when no repository is configured.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any, Literal, Protocol

from pydantic import ConfigDict, Field, field_validator, model_validator

from treasurypilot_api.identity.api import ApiModel

_HEX32 = re.compile(r"^0x[0-9a-fA-F]{64}$")
_SIGNATURE_HASH = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
_BASE_UNITS = re.compile(r"0|[1-9][0-9]*")
# Keys are compared with "_"/"-" stripped and casefolded; "signaturehash" is the one
# permitted signature field and its value is format-checked on the models.
_FORBIDDEN_KEY_PARTS = ("email", "phone", "contact", "signature")
_FORBIDDEN_EXACT_KEYS = frozenset({"sig"})
_ALLOWED_KEYS = frozenset({"signaturehash"})


class StrictModel(ApiModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class BundleRequest(StrictModel):
    id: uuid.UUID
    vendor_display_name: str | None = None
    amount: str
    currency: str
    fingerprint: str | None = None
    invoice_hash: str | None = None

    @field_validator("amount")
    @classmethod
    def integer_base_units(cls, value: str) -> str:
        if not _BASE_UNITS.fullmatch(value):
            raise ValueError("amount must be an integer base-unit string")
        return value


def _signature_hash(value: str | None) -> str | None:
    """Only a 32-byte digest may stand in for a signature; raw signatures are longer."""
    if value is None:
        return None
    if not _SIGNATURE_HASH.fullmatch(value):
        raise ValueError("signature_hash must be a 32-byte hex digest")
    return value.lower()


class ApprovalEvidence(StrictModel):
    typed_data: dict[str, Any] | None = None
    signer_address: str | None = None
    signature_hash: str | None = None

    @field_validator("signature_hash")
    @classmethod
    def hash_only(cls, value: str | None) -> str | None:
        return _signature_hash(value)


class FlagEvidence(StrictModel):
    id: uuid.UUID
    code: str
    severity: str
    status: str
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    ack_note: str | None = None


class PlanStepEvidence(StrictModel):
    seq: int
    step_id: str
    action: int
    chain_id: int
    from_address: str
    to_address: str
    asset_address: str
    amount: str
    venue: Literal["TEST_ROUTER"] | None = None  # swap-for-gas steps are labelled TEST ROUTER


class PlanEvidence(StrictModel):
    plan_id: uuid.UUID | None = None
    status: str | None = None
    planner_source: str
    plan_hash: str | None = None
    steps: list[PlanStepEvidence] = Field(default_factory=list)


class ValidationEvidence(StrictModel):
    id: uuid.UUID | None = None
    plan_id: uuid.UUID | None = None
    stage: str
    decision: str
    reason_codes: list[str] = Field(default_factory=list)
    checks: list[dict[str, Any]] = Field(default_factory=list)


class AICallEvidence(StrictModel):
    id: uuid.UUID
    purpose: str
    model: str | None = None
    prompt_version: str | None = None
    output_summary: str | None = None


class AttestationEvidence(StrictModel):
    typed_data: dict[str, Any] | None = None
    signer_address: str | None = None
    signature_hash: str | None = None

    @field_validator("signature_hash")
    @classmethod
    def hash_only(cls, value: str | None) -> str | None:
        return _signature_hash(value)


def _tx_hash(value: str) -> str:
    if not _HEX32.fullmatch(value):
        raise ValueError("transaction hash must be 32-byte hex")
    return value.lower()


class TransactionEvidence(StrictModel):
    tx_hash: str
    chain_id: int = Field(ge=1)
    block_number: int | None = Field(default=None, ge=0)
    fee_base_units: str | None = None

    @field_validator("tx_hash")
    @classmethod
    def valid_hash(cls, value: str) -> str:
        return _tx_hash(value)

    @field_validator("fee_base_units")
    @classmethod
    def integer_fee(cls, value: str | None) -> str | None:
        if value is not None and not _BASE_UNITS.fullmatch(value):
            raise ValueError("fee_base_units must be a non-negative integer string")
        return value


class VerificationEvidence(StrictModel):
    tx_hash: str
    status: str
    checked_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tx_hash")
    @classmethod
    def valid_hash(cls, value: str) -> str:
        return _tx_hash(value)


class ReconciliationLineEvidence(StrictModel):
    classification: str
    tx_hash: str
    asset_address: str | None = None
    amount: str
    block_number: int | None = None
    day: date | None = None

    @field_validator("tx_hash")
    @classmethod
    def valid_hash(cls, value: str) -> str:
        return _tx_hash(value)


class ReconciliationEvidence(StrictModel):
    status: str
    version: int
    matched_by: str | None = None
    matched_at: datetime | None = None
    finalized_at: datetime | None = None
    lines: list[ReconciliationLineEvidence] = Field(default_factory=list)


class EvidenceBundle(StrictModel):
    schema_version: Literal["evidence-bundle.v1"] = "evidence-bundle.v1"
    status: Literal["VALID"] = "VALID"
    organization_id: uuid.UUID
    request: BundleRequest
    approval: ApprovalEvidence | None = None
    flags: list[FlagEvidence] = Field(default_factory=list)
    plan: PlanEvidence | None = None
    validations: list[ValidationEvidence] = Field(default_factory=list)
    ai_calls: list[AICallEvidence] = Field(default_factory=list)
    attestation: AttestationEvidence | None = None
    operations: list[dict[str, Any]] = Field(default_factory=list)
    transactions: list[TransactionEvidence] | None = None
    verifications: list[VerificationEvidence] = Field(default_factory=list)
    reconciliation: ReconciliationEvidence | None = None
    eas_uid: str | None = None
    coverage: dict[str, Any] = Field(default_factory=dict)
    fixture_labels: list[str] = Field(default_factory=list)
    generated_at: datetime
    app_version: str
    sha256: str | None = None

    @model_validator(mode="after")
    def valid_tx_section(self) -> EvidenceBundle:
        if self.transactions == []:
            raise ValueError("transactions must be omitted when there are no transactions")
        resolved = {tx.tx_hash for tx in self.transactions or []}
        for verification in self.verifications:
            if verification.tx_hash not in resolved:
                raise ValueError(f"verification {verification.tx_hash} has no matching transaction")
        return self


class EvidenceNotFound(Exception):
    """Request is absent or outside the caller's organization."""


class EvidenceForbidden(Exception):
    """Caller lacks a role allowed to read financial evidence."""


class EvidenceUnavailable(Exception):
    """Chain verification could not be completed (e.g. every RPC failed); retry later."""


class EvidenceBundleInvalid(Exception):
    """The bundle failed an integrity check (e.g. unresolved tx hash); it is withheld."""


class EvidenceRepository(Protocol):
    """Implementations must produce bundles via ``build_evidence_bundle`` (privacy, tx, seal)."""

    async def export_request(
        self, *, organization_id: uuid.UUID, request_id: uuid.UUID
    ) -> EvidenceBundle: ...


def _reject_sensitive_keys(value: Any, path: str = "bundle") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = re.sub(r"[_-]", "", str(key)).casefold()
            if normalized not in _ALLOWED_KEYS and (
                normalized in _FORBIDDEN_EXACT_KEYS
                or any(part in normalized for part in _FORBIDDEN_KEY_PARTS)
            ):
                raise ValueError(f"sensitive field is not allowed at {path}.{key}")
            _reject_sensitive_keys(child, f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, child in enumerate(value):
            _reject_sensitive_keys(child, f"{path}[{index}]")


async def build_evidence_bundle(
    *,
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    source: Mapping[str, Any],
    transaction_resolves: Callable[[TransactionEvidence], Awaitable[bool]],
) -> EvidenceBundle:
    """Validate, privacy-check, resolve chain references, and seal one bundle."""
    payload = dict(source)
    payload["organization_id"] = organization_id
    payload.setdefault("schema_version", "evidence-bundle.v1")
    payload.setdefault("generated_at", datetime.now(UTC))
    request = dict(payload.get("request") or {})
    if request.setdefault("id", request_id) != request_id:
        raise EvidenceBundleInvalid("bundle request id does not match the requested id")
    payload["request"] = request
    if payload.get("transactions") == []:
        payload.pop("transactions")
    _reject_sensitive_keys(payload)
    bundle = EvidenceBundle.model_validate(payload)
    transactions = bundle.transactions or []
    results = await asyncio.gather(
        *(transaction_resolves(tx) for tx in transactions), return_exceptions=True
    )
    for tx, resolved in zip(transactions, results, strict=True):
        if resolved is not True:
            cause = resolved if isinstance(resolved, BaseException) else None
            raise EvidenceBundleInvalid(f"transaction hash {tx.tx_hash} did not resolve") from cause
    unsigned = bundle.model_dump(mode="json", by_alias=True, exclude={"sha256"}, exclude_none=True)
    digest = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return bundle.model_copy(update={"sha256": digest})
