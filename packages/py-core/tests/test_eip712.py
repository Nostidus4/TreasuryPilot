from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from eth_account.messages import encode_typed_data

from treasurypilot_core.eip712 import (
    ERC1271_MAGIC_VALUE,
    digest,
    encode_approver_sig,
    payment_approval_typed_data,
    plan_attestation_typed_data,
    verify_signature,
)

VECTORS = Path(__file__).resolve().parents[3] / "contracts" / "test" / "vectors"
APPROVAL_VECTORS = ("payment-approval", "payment-approval-early", "payment-approval-large")
PLAN_VECTORS = ("plan-attestation", "plan-attestation-empty")
SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def _load(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((VECTORS / f"{name}.json").read_text()))


def _build(vector: dict[str, Any]) -> dict[str, Any]:
    primary = next(iter(vector["types"]))
    builder = (
        payment_approval_typed_data if primary == "PaymentApproval" else plan_attestation_typed_data
    )
    return builder(
        vector["message"],
        chain_id=vector["domain"]["chainId"],
        verifying_contract=vector["domain"]["verifyingContract"],
    )


@pytest.mark.parametrize("name", APPROVAL_VECTORS + PLAN_VECTORS)
def test_golden_vectors_match_the_contract(name: str) -> None:
    vector = _load(name)
    typed = _build(vector)
    signable = encode_typed_data(full_message=typed)
    signature = bytes.fromhex(vector["signature"][2:])

    assert typed["domain"] == vector["domain"]
    assert {k: v for k, v in typed["types"].items() if k != "EIP712Domain"} == vector["types"]
    assert "0x" + signable.header.hex() == vector["domainSeparator"]
    assert "0x" + signable.body.hex() == vector["structHash"]
    assert "0x" + digest(typed).hex() == vector["digest"]
    assert verify_signature(typed, vector["signer"], signature)


@pytest.mark.parametrize("name", APPROVAL_VECTORS)
def test_approver_sig_envelope_matches_the_module_wire_format(name: str) -> None:
    vector = _load(name)
    envelope = encode_approver_sig(vector["signer"], bytes.fromhex(vector["signature"][2:]))

    assert "0x" + envelope.hex() == vector["approverSig"]


@pytest.mark.parametrize("name", APPROVAL_VECTORS + PLAN_VECTORS)
def test_any_one_field_mutation_changes_the_digest(name: str) -> None:
    vector = _load(name)
    original = digest(_build(vector))
    for field, value in vector["message"].items():
        mutated = json.loads(json.dumps(vector))
        if isinstance(value, list):
            mutated["message"][field] = [*value, "0x" + "ab" * 32]
        elif isinstance(value, str) and value.startswith("0x"):
            last = "0" if value[-1] != "0" else "1"
            mutated["message"][field] = value[:-1] + last
        else:
            mutated["message"][field] = int(value) + 1
        assert digest(_build(mutated)) != original, field


def test_wrong_signer_tampered_message_or_malformed_signature_fails() -> None:
    vector = _load("payment-approval")
    typed = _build(vector)
    signature = bytes.fromhex(vector["signature"][2:])
    tampered = _build({**vector, "message": {**vector["message"], "amount": "1"}})
    flipped_s = (SECP256K1_N - int.from_bytes(signature[32:64])).to_bytes(32)
    # Valid for the same signer, but OZ ECDSA rejects malleable and v=0/1 forms.
    high_s_twin = signature[:32] + flipped_s + bytes([55 - signature[64]])
    raw_v = signature[:64] + bytes([signature[64] - 27])

    assert not verify_signature(typed, "0x" + "11" * 20, signature)
    assert not verify_signature(tampered, vector["signer"], signature)
    assert not verify_signature(typed, vector["signer"], b"\x00" * 65)
    assert not verify_signature(typed, vector["signer"], b"\x00" * 64 + b"\x1b")
    assert not verify_signature(typed, vector["signer"], SECP256K1_N.to_bytes(32) * 2 + b"\x1b")
    assert not verify_signature(typed, vector["signer"], signature[:64])
    assert not verify_signature(typed, vector["signer"], high_s_twin)
    assert not verify_signature(typed, vector["signer"], raw_v)


def test_erc1271_hook_decides_for_contract_signers() -> None:
    wallet = "0x" + "44" * 20
    calls: list[tuple[str, bytes, bytes]] = []

    def accept(signer: str, hashed: bytes, signature: bytes) -> bytes:
        calls.append((signer, hashed, signature))
        return ERC1271_MAGIC_VALUE + bytes(28)

    typed, signature = _build(_load("payment-approval")), b"opaque-safe-signature"

    assert verify_signature(typed, wallet, signature, erc1271=accept)
    assert calls == [(wallet, digest(typed), signature)]
    # OZ requires a full 32-byte word equal to the padded selector.
    for returned in (b"\xff" * 32, ERC1271_MAGIC_VALUE, ERC1271_MAGIC_VALUE + b"\x01" * 28, b""):
        assert not verify_signature(typed, wallet, signature, erc1271=lambda *_, r=returned: r)


@pytest.mark.parametrize(
    "change",
    [lambda m: m.pop("expiry"), lambda m: m.update(nonce="1")],
)
def test_builder_rejects_messages_that_do_not_match_the_struct(change: Any) -> None:
    vector = _load("payment-approval")
    change(vector["message"])

    with pytest.raises(ValueError, match="PaymentApproval fields"):
        _build(vector)
