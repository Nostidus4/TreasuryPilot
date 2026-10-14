from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from treasurypilot_api.audit.evidence import (
    EvidenceBundleInvalid,
    build_evidence_bundle,
)

_SCHEMA = Path(__file__).parents[1] / "src/treasurypilot_api/audit/evidence-bundle.v1.schema.json"


def _source(request_id: uuid.UUID, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "request": {
            "id": request_id,
            "vendor_display_name": "Example Vendor",
            "amount": "250000",
            "currency": "USDC",
        },
        "validations": [
            {"stage": "PAYMENT", "decision": "BLOCK", "reason_codes": ["LIMIT"], "checks": []}
        ],
        "operations": [],
        "fixture_labels": ["TESTNET", "SYNTHETIC"],
        "app_version": "test",
    }
    payload.update(overrides)
    return payload


def test_blocked_request_bundle_has_validation_logs_but_no_transactions() -> None:
    request_id, organization_id = uuid.uuid4(), uuid.uuid4()

    async def scenario() -> dict[str, object]:
        bundle = await build_evidence_bundle(
            organization_id=organization_id,
            request_id=request_id,
            source=_source(request_id, transactions=[]),
            transaction_resolves=lambda _tx: _resolved(True),
        )
        return bundle.model_dump(mode="json", by_alias=True, exclude_none=True)

    result = asyncio.run(scenario())
    assert "transactions" not in result
    assert result["validations"][0]["decision"] == "BLOCK"
    assert result["sha256"]


def test_paid_request_hash_is_resolved_and_signature_is_hash_only() -> None:
    request_id, organization_id = uuid.uuid4(), uuid.uuid4()
    tx_hash = "0x" + "a" * 64

    async def scenario() -> dict[str, object]:
        bundle = await build_evidence_bundle(
            organization_id=organization_id,
            request_id=request_id,
            source=_source(
                request_id,
                approval={"signer_address": "0xabc", "signature_hash": "0x" + "b" * 64},
                transactions=[{"tx_hash": tx_hash, "chain_id": 11155111}],
                generated_at=datetime.now(UTC),
            ),
            transaction_resolves=lambda _tx: _resolved(True),
        )
        return bundle.model_dump(mode="json", by_alias=True, exclude_none=True)

    result = asyncio.run(scenario())
    assert result["transactions"][0]["txHash"] == tx_hash
    assert result["approval"]["signatureHash"] == "0x" + "b" * 64
    assert '"signature":' not in json.dumps(result).casefold()


def test_unresolved_transaction_withholds_bundle() -> None:
    request_id, organization_id = uuid.uuid4(), uuid.uuid4()

    async def scenario() -> None:
        await build_evidence_bundle(
            organization_id=organization_id,
            request_id=request_id,
            source=_source(
                request_id,
                transactions=[{"tx_hash": "0x" + "c" * 64, "chain_id": 1}],
            ),
            transaction_resolves=lambda _tx: _resolved(False),
        )

    with pytest.raises(EvidenceBundleInvalid):
        asyncio.run(scenario())


@pytest.mark.parametrize("sensitive", ["email", "phone", "contact_name", "signature"])
def test_sensitive_fields_are_rejected(sensitive: str) -> None:
    request_id, organization_id = uuid.uuid4(), uuid.uuid4()

    async def scenario() -> None:
        source = _source(request_id)
        source["reconciliation"] = {sensitive: "private"}
        await build_evidence_bundle(
            organization_id=organization_id,
            request_id=request_id,
            source=source,
            transaction_resolves=lambda _tx: _resolved(True),
        )

    with pytest.raises(ValueError, match="sensitive field"):
        asyncio.run(scenario())


def test_schema_is_valid_json_and_fixes_bundle_version() -> None:
    schema = json.loads(_SCHEMA.read_text())
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schemaVersion"]["const"] == "evidence-bundle.v1"
    assert "transactions" not in schema["required"]


async def _resolved(value: bool) -> bool:
    return value
