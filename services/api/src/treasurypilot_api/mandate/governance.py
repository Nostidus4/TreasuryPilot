"""Safe v1.4.1 transaction construction and owner signature handling (MDT-009)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from eth_abi import decode, encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_hash.auto import keccak
from eth_keys.exceptions import BadSignature

SAFE_TX_FIELDS = [
    {"name": "to", "type": "address"},
    {"name": "value", "type": "uint256"},
    {"name": "data", "type": "bytes"},
    {"name": "operation", "type": "uint8"},
    {"name": "safeTxGas", "type": "uint256"},
    {"name": "baseGas", "type": "uint256"},
    {"name": "gasPrice", "type": "uint256"},
    {"name": "gasToken", "type": "address"},
    {"name": "refundReceiver", "type": "address"},
    {"name": "nonce", "type": "uint256"},
]
_DOMAIN_FIELDS = [
    {"name": "chainId", "type": "uint256"},
    {"name": "verifyingContract", "type": "address"},
]
_ZERO_ADDRESS = "0x" + "00" * 20
_SECP256K1_HALF_N = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0
_MULTISEND_SELECTOR = keccak(b"multiSend(bytes)")[:4]
_EXEC_SELECTOR = keccak(
    b"execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)"
)[:4]
_AUTHORIZE_BORROW_SELECTOR = keccak(b"authorizeBorrow(bytes32,uint256,uint64,uint256,uint256)")[:4]
_AUTHORIZE_REPAY_SELECTOR = keccak(b"authorizeRepay(bytes32,uint256,uint64)")[:4]


def build_borrow_authorization_call(
    module_address: bytes,
    *,
    plan_id: bytes,
    amount: int,
    expiry: int,
    min_health_factor: int,
    max_rate_ray: int,
) -> GovernanceCall:
    """Encode the exact owner authorization for one validated borrow proposal.

    All numeric values are integer base units / protocol scalars. Callers must pass
    proposal-derived values directly; this builder deliberately performs no rounding
    or conversion from display units.
    """
    if len(plan_id) != 32:
        raise ValueError("plan_id must be bytes32")
    if amount <= 0:
        raise ValueError("borrow amount must be positive")
    if not 0 < expiry < 1 << 64:
        raise ValueError("expiry must fit uint64 and be positive")
    if min_health_factor <= 0 or max_rate_ray <= 0:
        raise ValueError("minimum health factor and maximum rate must be positive")
    data = _AUTHORIZE_BORROW_SELECTOR + encode(
        ["bytes32", "uint256", "uint64", "uint256", "uint256"],
        [plan_id, amount, expiry, min_health_factor, max_rate_ray],
    )
    return GovernanceCall(module_address, 0, data)


def build_repay_authorization_call(
    module_address: bytes,
    *,
    plan_id: bytes,
    amount: int,
    expiry: int,
) -> GovernanceCall:
    """Encode the exact owner authorization for one repay proposal."""
    if len(plan_id) != 32:
        raise ValueError("plan_id must be bytes32")
    if amount <= 0:
        raise ValueError("repay amount must be positive")
    if not 0 < expiry < 1 << 64:
        raise ValueError("expiry must fit uint64 and be positive")
    data = _AUTHORIZE_REPAY_SELECTOR + encode(
        ["bytes32", "uint256", "uint64"], [plan_id, amount, expiry]
    )
    return GovernanceCall(module_address, 0, data)


@dataclass(frozen=True, slots=True)
class GovernanceCall:
    to: bytes
    value: int
    data: bytes
    operation: int = 0

    def __post_init__(self) -> None:
        if len(self.to) != 20:
            raise ValueError("call target must be 20 bytes")
        if not 0 <= self.value < 1 << 256 or self.operation not in (0, 1):
            raise ValueError("call value or operation is invalid")

    def as_json(self) -> dict[str, Any]:
        return {
            "to": "0x" + self.to.hex(),
            "value": str(self.value),
            "data": "0x" + self.data.hex(),
            "operation": self.operation,
        }


@dataclass(frozen=True, slots=True)
class SafeTransaction:
    to: bytes
    value: int
    data: bytes
    operation: int
    calls: tuple[GovernanceCall, ...]

    def typed_data(self, *, chain_id: int, safe_address: bytes, nonce: int) -> dict[str, Any]:
        return {
            "types": {"EIP712Domain": _DOMAIN_FIELDS, "SafeTx": SAFE_TX_FIELDS},
            "primaryType": "SafeTx",
            "domain": {"chainId": chain_id, "verifyingContract": _address(safe_address)},
            "message": {
                "to": _address(self.to),
                "value": self.value,
                "data": "0x" + self.data.hex(),
                "operation": self.operation,
                "safeTxGas": 0,
                "baseGas": 0,
                "gasPrice": 0,
                "gasToken": _ZERO_ADDRESS,
                "refundReceiver": _ZERO_ADDRESS,
                "nonce": nonce,
            },
        }


def _address(value: bytes) -> str:
    if len(value) != 20:
        raise ValueError("address must be 20 bytes")
    return "0x" + value.hex()


def build_safe_transaction(
    calls: Sequence[GovernanceCall], *, multisend_call_only: bytes | None = None
) -> SafeTransaction:
    """Use a direct call for one item, or Safe MultiSendCallOnly v1.4.1 for a bundle."""
    if not calls:
        raise ValueError("at least one call is required")
    if len(calls) == 1:
        call = calls[0]
        return SafeTransaction(call.to, call.value, call.data, call.operation, tuple(calls))
    if multisend_call_only is None or len(multisend_call_only) != 20:
        raise ValueError("MultiSendCallOnly v1.4.1 is required for a bundle")
    if any(call.operation != 0 for call in calls):
        raise ValueError("MultiSendCallOnly accepts only CALL operations")
    packed = b"".join(
        bytes([call.operation])
        + call.to
        + call.value.to_bytes(32, "big")
        + len(call.data).to_bytes(32, "big")
        + call.data
        for call in calls
    )
    return SafeTransaction(
        multisend_call_only,
        0,
        _MULTISEND_SELECTOR + encode(["bytes"], [packed]),
        1,
        tuple(calls),
    )


def safe_tx_hash(typed_data: Mapping[str, Any]) -> bytes:
    """Return the EIP-712 digest consumed by Safe v1.4.1."""
    signable = encode_typed_data(full_message=dict(typed_data))
    return keccak(b"\x19" + signable.version + signable.header + signable.body)


def recover_owner(typed_data: Mapping[str, Any], signature: bytes) -> bytes:
    """Recover a standard 65-byte EIP-712 owner signature; reject non-canonical v/r/s."""
    if (
        len(signature) != 65
        or signature[64] not in (27, 28)
        or int.from_bytes(signature[32:64], "big") > _SECP256K1_HALF_N
    ):
        raise ValueError("SIGNATURE_INVALID")
    try:
        address = Account.recover_message(
            encode_typed_data(full_message=dict(typed_data)), signature=signature
        )
    except (ValueError, BadSignature):
        raise ValueError("SIGNATURE_INVALID") from None
    return bytes.fromhex(address[2:])


def pack_signatures(
    typed_data: Mapping[str, Any],
    signatures: Sequence[tuple[bytes, bytes]],
    owners: Sequence[bytes],
    threshold: int,
) -> bytes:
    """Pack threshold-valid signatures in Safe's required ascending owner order."""
    if not 1 <= threshold <= len(owners):
        raise ValueError("invalid Safe threshold")
    owner_set = set(owners)
    recovered: dict[bytes, bytes] = {}
    for signature_owner, signature in signatures:
        signer = recover_owner(typed_data, signature)
        if signer not in owner_set or signer != signature_owner:
            raise ValueError("NOT_SAFE_OWNER")
        if signer in recovered:
            raise ValueError("ALREADY_SIGNED")
        recovered[signer] = signature
    if len(recovered) < threshold:
        raise ValueError("NOT_READY")
    return b"".join(recovered[address] for address in sorted(recovered)[:threshold])


def exec_transaction_data(tx: SafeTransaction, *, nonce: int, packed_signatures: bytes) -> bytes:
    """ABI encode the call the last owner submits to the Safe proxy."""
    if nonce < 0:
        raise ValueError("nonce must be non-negative")
    return _EXEC_SELECTOR + encode(
        [
            "address",
            "uint256",
            "bytes",
            "uint8",
            "uint256",
            "uint256",
            "uint256",
            "address",
            "address",
            "bytes",
        ],
        [
            _address(tx.to),
            tx.value,
            tx.data,
            tx.operation,
            0,
            0,
            0,
            _ZERO_ADDRESS,
            _ZERO_ADDRESS,
            packed_signatures,
        ],
    )


def decode_multisend_calls(data: bytes) -> tuple[GovernanceCall, ...]:
    """Decode MultiSendCallOnly payloads for persisted call review and round-trip checking."""
    if len(data) < 4 or data[:4] != _MULTISEND_SELECTOR:
        raise ValueError("not a MultiSendCallOnly call")
    (packed,) = decode(["bytes"], data[4:])
    calls: list[GovernanceCall] = []
    offset = 0
    while offset < len(packed):
        if offset + 85 > len(packed):
            raise ValueError("truncated MultiSendCallOnly entry")
        operation = packed[offset]
        to = packed[offset + 1 : offset + 21]
        value = int.from_bytes(packed[offset + 21 : offset + 53], "big")
        size = int.from_bytes(packed[offset + 53 : offset + 85], "big")
        offset += 85
        if offset + size > len(packed):
            raise ValueError("truncated MultiSendCallOnly calldata")
        calls.append(GovernanceCall(to, value, packed[offset : offset + size], operation))
        offset += size
    if not calls:
        raise ValueError("empty MultiSendCallOnly payload")
    return tuple(calls)
