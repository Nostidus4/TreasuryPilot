"""EIP-712 typed-data builders and signature checks matching the treasury module (ADR-003, ADR-019).

Exceptions and duplicate overrides are Safe governance transactions, not typed structs (M04-D3).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from eth_abi import encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_hash.auto import keccak
from eth_keys.exceptions import BadSignature

ERC1271_MAGIC_VALUE = bytes.fromhex("1626ba7e")
_ERC1271_MAGIC_WORD = ERC1271_MAGIC_VALUE + bytes(28)
_SECP256K1_HALF_N = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0

_DOMAIN_TYPE = [
    {"name": "name", "type": "string"},
    {"name": "version", "type": "string"},
    {"name": "chainId", "type": "uint256"},
    {"name": "verifyingContract", "type": "address"},
]
PAYMENT_APPROVAL_TYPE = [
    {"name": "requestId", "type": "bytes32"},
    {"name": "invoiceHash", "type": "bytes32"},
    {"name": "fingerprint", "type": "bytes32"},
    {"name": "treasury", "type": "address"},
    {"name": "payingWallet", "type": "address"},
    {"name": "asset", "type": "address"},
    {"name": "payee", "type": "address"},
    {"name": "amount", "type": "uint256"},
    {"name": "earlyAmount", "type": "uint256"},
    {"name": "earlyPayBy", "type": "uint64"},
    {"name": "deadline", "type": "uint64"},
    {"name": "termsHash", "type": "bytes32"},
    {"name": "expiry", "type": "uint64"},
]
PLAN_ATTESTATION_TYPE = [
    {"name": "planHash", "type": "bytes32"},
    {"name": "requestId", "type": "bytes32"},
    {"name": "stepIds", "type": "bytes32[]"},
    {"name": "policyVersion", "type": "bytes32"},
    {"name": "executor", "type": "address"},
    {"name": "validUntil", "type": "uint64"},
    {"name": "nonce", "type": "uint256"},
    {"name": "evidenceDigest", "type": "bytes32"},
]

# (signer, digest, signature) -> raw return data of signer.isValidSignature; the caller owns the RPC call.
Erc1271Call = Callable[[str, bytes, bytes], bytes]


def _typed_data(
    primary: str,
    fields: list[dict[str, str]],
    domain_name: str,
    message: Mapping[str, Any],
    chain_id: int,
    verifying_contract: str,
) -> dict[str, Any]:
    names = [field["name"] for field in fields]
    if set(message) != set(names):
        raise ValueError(f"{primary} fields must be exactly {names}, got {sorted(message)}")
    return {
        "types": {"EIP712Domain": _DOMAIN_TYPE, primary: fields},
        "primaryType": primary,
        "domain": {
            "name": domain_name,
            "version": "1",
            "chainId": chain_id,
            "verifyingContract": verifying_contract,
        },
        "message": {name: message[name] for name in names},
    }


def payment_approval_typed_data(
    message: Mapping[str, Any], *, chain_id: int, verifying_contract: str
) -> dict[str, Any]:
    """The 13-field PaymentApproval; ``verifying_contract`` is the module clone, never the factory."""
    return _typed_data(
        "PaymentApproval",
        PAYMENT_APPROVAL_TYPE,
        "TreasuryPilot",
        message,
        chain_id,
        verifying_contract,
    )


def plan_attestation_typed_data(
    message: Mapping[str, Any], *, chain_id: int, verifying_contract: str
) -> dict[str, Any]:
    """The policy-signed PlanAttestation (M08 §6.3) under the ``TreasuryPilot Policy`` domain."""
    return _typed_data(
        "PlanAttestation",
        PLAN_ATTESTATION_TYPE,
        "TreasuryPilot Policy",
        message,
        chain_id,
        verifying_contract,
    )


def digest(typed_data: Mapping[str, Any]) -> bytes:
    """The 32-byte hash the module signs and checks: keccak(0x1901 || domainSeparator || structHash)."""
    signable = encode_typed_data(full_message=dict(typed_data))
    return keccak(b"\x19" + signable.version + signable.header + signable.body)


def verify_signature(
    typed_data: Mapping[str, Any],
    signer: str,
    signature: bytes,
    *,
    erc1271: Erc1271Call | None = None,
) -> bool:
    """Mirror OpenZeppelin 5.2 ``SignatureChecker.isValidSignatureNow``.

    Pass ``erc1271`` exactly when ``signer`` has code; EOAs get the contract's strict ECDSA rules.
    """
    if erc1271 is not None:
        return erc1271(signer, digest(typed_data), signature)[:32] == _ERC1271_MAGIC_WORD
    if (
        len(signature) != 65
        or signature[64] not in (27, 28)
        or int.from_bytes(signature[32:64]) > _SECP256K1_HALF_N
    ):
        return False
    try:
        recovered = Account.recover_message(
            encode_typed_data(full_message=dict(typed_data)), signature=signature
        )
    except (ValueError, BadSignature):
        return False
    return str(recovered).lower() == signer.lower()


def encode_approver_sig(signer: str, signature: bytes) -> bytes:
    """The module's ``approverSig`` wire format: ``abi.encode(address signer, bytes signature)``."""
    return encode(["address", "bytes"], [signer, signature])
