"""Versioned request evidence bundles.

The repository is deliberately an adapter: execution tables and chain receipt
lookup are owned by the execution integration. Until that integration exists,
the API fails closed when no repository is configured.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import ConfigDict, Field, field_validator, model_validator

from treasurypilot_api.identity.api import ApiModel

_HEX32 = re.compile(r"^0x[0-9a-fA-F]{64}$")
_FORBIDDEN_KEYS = frozenset(
    {
        "email",
        "phone",
        "telephone",
        "contact",
        "contact_name",
        "contact_email",
        "raw_signature",
        "signature",
        "signature_bytes",
        "sig",
    }
)


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
        if not re.fullmatch(r"-?(0|[1-9][0-9]*)", value):
            raise ValueError("amount must be an integer base-unit string")
        return value


class ApprovalEvidence(StrictModel):
    typed_data: dict[str, Any] | None = None
    signer_address: str | None = None
    signature_hash: str | None = None


class FlagEvidence(StrictModel):
    id: uuid.UUID
    code: str
    severity: str
    status: str
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    ack_note: str | None = None


class PlanEvidence(StrictModel):
    planner_source: str
    plan_hash: str | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)


class ValidationEvidence(StrictModel):
    id: uuid.UUID | None = None
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


class TransactionEvidence(StrictModel):
    tx_hash: str
    chain_id: int
    block_number: int | None = None
    fee_base_units: str | None = None

    @field_validator("tx_hash")
    @classmethod
    def valid_hash(cls, value: str) -> str:
        if not _HEX32.fullmatch(value):
            raise ValueError("transaction hash must be 32-byte hex")
        return value.lower()


class VerificationEvidence(StrictModel):
    tx_hash: str
    status: str
    checked_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)


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
    reconciliation: dict[str, Any] | None = None
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
        return self


class EvidenceNotFound(Exception):
    """Request is absent or outside the caller's organization."""


class EvidenceForbidden(Exception):
    """Caller lacks a role allowed to read financial evidence."""


class EvidenceBundleInvalid(Exception):
    """One or more transaction hashes did not resolve; the bundle is withheld."""


class EvidenceRepository(Protocol):
    async def export_request(self, *, organization_id: uuid.UUID, request_id: uuid.UUID) -> EvidenceBundle: ...


def _reject_sensitive_keys(value: Any, path: str = "bundle") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", str(key)).replace("-", "_").casefold()
            if normalized in _FORBIDDEN_KEYS:
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
    transaction_resolves: Any,
) -> EvidenceBundle:
    """Validate, privacy-check, resolve chain references, and seal one bundle."""
    from collections.abc import Awaitable, Callable

    resolver: Callable[[TransactionEvidence], Awaitable[bool]] = transaction_resolves
    payload = dict(source)
    payload["organization_id"] = organization_id
    payload.setdefault("schema_version", "evidence-bundle.v1")
    payload.setdefault("generated_at", datetime.now(UTC))
    payload.setdefault("request", {"id": request_id})
    payload["request"]["id"] = request_id
    if payload.get("transactions") == []:
        payload.pop("transactions")
    _reject_sensitive_keys(payload)
    bundle = EvidenceBundle.model_validate(payload)
    for tx in bundle.transactions or []:
        if not await resolver(tx):
            raise EvidenceBundleInvalid(f"transaction hash {tx.tx_hash} did not resolve")
    unsigned = bundle.model_dump(
        mode="json", by_alias=True, exclude={"sha256"}, exclude_none=True
    )
    digest = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return bundle.model_copy(update={"sha256": digest})
