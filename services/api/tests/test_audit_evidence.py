from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from treasurypilot_api.audit.evidence import (
    ApprovalEvidence,
    AttestationEvidence,
    EvidenceBundle,
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


@pytest.mark.parametrize(
    "sensitive",
    [
        "email",
        "phone",
        "contact_name",
        "signature",
        "emailAddress",
        "phoneNumber",
        "contactPhone",
        "EMAIL",
        "PHONE",
        "SIG",
    ],
)
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


@pytest.mark.parametrize("model", [ApprovalEvidence, AttestationEvidence])
@pytest.mark.parametrize("value", ["0x" + "ab" * 65, "raw", "0x" + "g" * 64, ""])
def test_raw_signatures_are_rejected_as_signature_hash(model: type, value: str) -> None:
    with pytest.raises(ValueError, match="32-byte hex digest"):
        model(signature_hash=value)


def test_signature_hash_is_normalized_to_lowercase() -> None:
    assert ApprovalEvidence(signature_hash="0x" + "AB" * 32).signature_hash == "0x" + "ab" * 32


def _build(request_id: uuid.UUID, source: dict[str, object], ok: bool = True) -> EvidenceBundle:
    return asyncio.run(
        build_evidence_bundle(
            organization_id=uuid.uuid4(),
            request_id=request_id,
            source=source,
            transaction_resolves=lambda _tx: _resolved(ok),
        )
    )


def test_request_id_mismatch_is_rejected_and_source_is_not_mutated() -> None:
    request_id = uuid.uuid4()
    source = _source(request_id)
    snapshot = json.dumps(source, default=str)
    _build(request_id, source)
    assert json.dumps(source, default=str) == snapshot
    with pytest.raises(EvidenceBundleInvalid, match="request id"):
        _build(uuid.uuid4(), source)


def test_resolver_failure_withholds_bundle() -> None:
    request_id = uuid.uuid4()

    async def boom(_tx: object) -> bool:
        raise RuntimeError("rpc down")

    with pytest.raises(EvidenceBundleInvalid):
        asyncio.run(
            build_evidence_bundle(
                organization_id=uuid.uuid4(),
                request_id=request_id,
                source=_source(
                    request_id, transactions=[{"tx_hash": "0x" + "c" * 64, "chain_id": 1}]
                ),
                transaction_resolves=boom,
            )
        )


@pytest.mark.parametrize(
    "tx",
    [
        {"tx_hash": "0x" + "c" * 64, "chain_id": 0},
        {"tx_hash": "0x" + "c" * 64, "chain_id": 1, "block_number": -1},
        {"tx_hash": "0x" + "c" * 64, "chain_id": 1, "fee_base_units": "-1"},
        {"tx_hash": "0x" + "c" * 64, "chain_id": 1, "fee_base_units": "abc"},
    ],
)
def test_transaction_fields_match_schema(tx: dict[str, object]) -> None:
    request_id = uuid.uuid4()
    with pytest.raises(ValueError):
        _build(request_id, _source(request_id, transactions=[tx]))


def test_negative_amount_is_rejected() -> None:
    request_id = uuid.uuid4()
    source = _source(request_id)
    source["request"] = {"id": request_id, "amount": "-5", "currency": "USDC"}
    with pytest.raises(ValueError):
        _build(request_id, source)


def test_verifications_are_normalized_and_tied_to_transactions() -> None:
    request_id = uuid.uuid4()
    tx_hash = "0x" + "c" * 64
    verification = {
        "tx_hash": tx_hash.upper().replace("0X", "0x"),
        "status": "OK",
        "checked_at": datetime.now(UTC),
    }
    bundle = _build(
        request_id,
        _source(
            request_id,
            transactions=[{"tx_hash": tx_hash, "chain_id": 1}],
            verifications=[verification],
        ),
    )
    assert bundle.verifications[0].tx_hash == tx_hash
    with pytest.raises(ValueError, match="no matching transaction"):
        _build(request_id, _source(request_id, verifications=[verification]))


def test_schema_properties_match_model_fields() -> None:
    schema = json.loads(_SCHEMA.read_text())

    def aliases(model: type) -> set[str]:
        return {f.alias or n for n, f in model.model_fields.items()}  # type: ignore[attr-defined]

    assert set(schema["properties"]) == aliases(EvidenceBundle)
    defs = schema["$defs"]
    for name, field in (
        ("approval", "approval"),
        ("request", "request"),
        ("plan", "plan"),
        ("transaction", "transactions"),
        ("verification", "verifications"),
        ("flag", "flags"),
        ("validation", "validations"),
        ("aiCall", "ai_calls"),
    ):
        annotation = EvidenceBundle.model_fields[field].annotation
        model = next(a for a in _models(annotation))
        assert set(defs[name]["properties"]) == aliases(model), name


def _models(annotation: object) -> list[type]:
    from typing import get_args

    found = [a for a in get_args(annotation) if hasattr(a, "model_fields")]
    for a in get_args(annotation):
        found += _models(a)
    return found or ([annotation] if hasattr(annotation, "model_fields") else [])


async def _resolved(value: bool) -> bool:
    return value


def test_swap_step_carries_the_test_router_label_and_others_omit_it() -> None:
    request_id = uuid.uuid4()
    step = {
        "seq": 0, "step_id": "0x" + "1" * 64, "action": 3, "chain_id": 31337,
        "from_address": "0x" + "1" * 40, "to_address": "0x" + "2" * 40,
        "asset_address": "0x" + "3" * 40, "amount": "1500",
    }  # fmt: skip
    plan = {"planner_source": "DETERMINISTIC", "steps": [{**step, "venue": "TEST_ROUTER"}, step]}

    async def scenario() -> dict[str, Any]:
        bundle = await build_evidence_bundle(
            organization_id=uuid.uuid4(),
            request_id=request_id,
            source=_source(request_id, plan=plan),
            transaction_resolves=lambda _tx: _resolved(True),
        )
        return bundle.model_dump(mode="json", by_alias=True, exclude_none=True)

    steps = asyncio.run(scenario())["plan"]["steps"]
    assert steps[0]["venue"] == "TEST_ROUTER" and "venue" not in steps[1]
