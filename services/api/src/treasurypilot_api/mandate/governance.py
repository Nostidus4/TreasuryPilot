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
_ENABLE_MODULE_SELECTOR = keccak(b"enableModule(address)")[:4]
_FACTORY_CREATE_SELECTOR = keccak(
    b"createDeterministic(address,address[],(uint64,uint64,uint32,address,address,(uint128,uint128),(uint128,uint128),uint32,(uint128,uint128)),address[],(address,uint256,uint256)[],address,bytes32)"
)[:4]
_FACTORY_PREDICT_SELECTOR = keccak(b"predictDeterministicAddress(address,bytes32)")[:4]
_AUTHORIZE_BORROW_SELECTOR = keccak(b"authorizeBorrow(bytes32,uint256,uint64,uint256,uint256)")[:4]
_AUTHORIZE_REPAY_SELECTOR = keccak(b"authorizeRepay(bytes32,uint256,uint64)")[:4]
_CANCEL_REQUEST_SELECTOR = keccak(b"cancelRequest(bytes32)")[:4]
_ADD_PAYEE_SELECTOR = keccak(b"addPayee(address)")[:4]
_DEACTIVATE_PAYEE_SELECTOR = keccak(b"deactivatePayee(address)")[:4]
_GRANT_EXCEPTION_SELECTOR = keccak(b"grantException(bytes32,uint128,address,uint64)")[:4]
_REVOKE_EXCEPTION_SELECTOR = keccak(b"revokeException(bytes32)")[:4]
_PAUSE_SELECTOR = keccak(b"pause()")[:4]
_RESUME_SELECTOR = keccak(b"resume()")[:4]
_REVOKE_SELECTOR = keccak(b"revoke()")[:4]
_ALLOW_DUPLICATE_SELECTOR = keccak(b"allowDuplicate(bytes32,bytes32)")[:4]


def _require_positive_uint(name: str, value: int, bits: int = 256) -> None:
    # `type(...) is int` also rejects bool, which would otherwise encode as 0/1.
    if type(value) is not int:
        raise ValueError(f"{name} must be an int")
    if not 0 < value < 1 << bits:
        raise ValueError(f"{name} must be positive and fit uint{bits}")


def _require_authorization(kind: str, plan_id: bytes, amount: int, expiry: int) -> None:
    # Exact bytes only: a mutable bytearray could change after validation.
    if type(plan_id) is not bytes or len(plan_id) != 32:
        raise ValueError("plan_id must be bytes32")
    _require_positive_uint(f"{kind} amount", amount)
    _require_positive_uint("expiry", expiry, 64)


@dataclass(frozen=True, slots=True)
class BorrowAuthorizationProposal:
    """Exact integer terms captured for one owner-authorized borrow proposal."""

    plan_id: bytes
    amount: int
    expiry: int
    min_health_factor: int
    max_rate_ray: int

    def __post_init__(self) -> None:
        # Validation also guarantees immutable field types (bytes, int).
        _require_authorization("borrow", self.plan_id, self.amount, self.expiry)
        _require_positive_uint("minimum health factor", self.min_health_factor)
        _require_positive_uint("maximum rate", self.max_rate_ray)


def build_borrow_authorization_call(
    module_address: bytes,
    *,
    proposal: BorrowAuthorizationProposal,
) -> GovernanceCall:
    """Encode the exact owner authorization for one borrow proposal.

    The amount, expiry, minimum health factor and maximum rate travel together in one
    immutable proposal object, so a caller cannot supply a different set of values to
    the encoder. All values are protocol integers; no display-unit conversion occurs.
    """
    data = _AUTHORIZE_BORROW_SELECTOR + encode(
        ["bytes32", "uint256", "uint64", "uint256", "uint256"],
        [
            proposal.plan_id,
            proposal.amount,
            proposal.expiry,
            proposal.min_health_factor,
            proposal.max_rate_ray,
        ],
    )
    return GovernanceCall(module_address, 0, data)


@dataclass(frozen=True, slots=True)
class RepayAuthorizationProposal:
    """Exact integer terms captured for one owner-authorized repay proposal."""

    plan_id: bytes
    amount: int
    expiry: int

    def __post_init__(self) -> None:
        _require_authorization("repay", self.plan_id, self.amount, self.expiry)


def build_repay_authorization_call(
    module_address: bytes,
    *,
    proposal: RepayAuthorizationProposal,
) -> GovernanceCall:
    """Encode the exact owner authorization for one repay proposal."""
    data = _AUTHORIZE_REPAY_SELECTOR + encode(
        ["bytes32", "uint256", "uint64"], [proposal.plan_id, proposal.amount, proposal.expiry]
    )
    return GovernanceCall(module_address, 0, data)


def build_cancel_request_call(module_address: bytes, *, request_id: bytes) -> GovernanceCall:
    """Encode `module.cancelRequest(requestId)` for an approver wallet or a Safe T transaction."""
    if len(request_id) != 32:
        raise ValueError("request_id must be bytes32")
    return GovernanceCall(
        module_address, 0, _CANCEL_REQUEST_SELECTOR + encode(["bytes32"], [request_id])
    )


def _no_arg_call(module_address: bytes, selector: bytes) -> GovernanceCall:
    if len(module_address) != 20 or module_address == bytes(20):
        raise ValueError("module must be a nonzero EVM address")
    return GovernanceCall(module_address, 0, selector)


def build_pause_call(module_address: bytes) -> GovernanceCall:
    """`module.pause()`: callable by Safe T or the guardian Safe."""
    return _no_arg_call(module_address, _PAUSE_SELECTOR)


def build_resume_call(module_address: bytes) -> GovernanceCall:
    """`module.resume()`: Safe T only, so a guardian can never lift a pause."""
    return _no_arg_call(module_address, _RESUME_SELECTOR)


def build_revoke_call(module_address: bytes) -> GovernanceCall:
    """`module.revoke()`: Safe T only and irreversible."""
    return _no_arg_call(module_address, _REVOKE_SELECTOR)


def build_add_payee_call(module_address: bytes, *, payee: bytes) -> GovernanceCall:
    """Encode the Safe-only registration call for one screened payee address."""
    if len(module_address) != 20 or len(payee) != 20 or payee == bytes(20):
        raise ValueError("module and payee must be nonzero EVM addresses")
    return GovernanceCall(module_address, 0, _ADD_PAYEE_SELECTOR + encode(["address"], [payee]))


def build_deactivate_payee_call(module_address: bytes, *, payee: bytes) -> GovernanceCall:
    """Encode the Safe-only deactivation call for one known payee address."""
    if len(module_address) != 20 or len(payee) != 20 or payee == bytes(20):
        raise ValueError("module and payee must be nonzero EVM addresses")
    return GovernanceCall(
        module_address, 0, _DEACTIVATE_PAYEE_SELECTOR + encode(["address"], [payee])
    )


def build_grant_exception_call(
    module_address: bytes,
    *,
    request_id: bytes,
    amount: int,
    payee: bytes,
    expiry: int,
) -> GovernanceCall:
    """Build the exact one-request, one-payee exception reviewed by an Owner."""
    if len(module_address) != 20 or module_address == bytes(20):
        raise ValueError("module address must be a nonzero EVM address")
    if len(request_id) != 32 or request_id == bytes(32):
        raise ValueError("request_id must be a nonzero bytes32")
    if len(payee) != 20 or payee == bytes(20):
        raise ValueError("payee must be a nonzero EVM address")
    _require_positive_uint("exception amount", amount, 128)
    _require_positive_uint("exception expiry", expiry, 64)
    return GovernanceCall(
        module_address,
        0,
        _GRANT_EXCEPTION_SELECTOR
        + encode(["bytes32", "uint128", "address", "uint64"], [request_id, amount, payee, expiry]),
    )


def build_revoke_exception_call(module_address: bytes, *, request_id: bytes) -> GovernanceCall:
    """Build `revokeException` for the request's existing one-time grant."""
    if len(module_address) != 20 or module_address == bytes(20):
        raise ValueError("module address must be a nonzero EVM address")
    if len(request_id) != 32 or request_id == bytes(32):
        raise ValueError("request_id must be a nonzero bytes32")
    return GovernanceCall(
        module_address, 0, _REVOKE_EXCEPTION_SELECTOR + encode(["bytes32"], [request_id])
    )


def build_allow_duplicate_call(
    module_address: bytes, *, fingerprint: bytes, request_id: bytes
) -> GovernanceCall:
    """Build a duplicate override bound to one invoice fingerprint and request."""
    if len(module_address) != 20 or module_address == bytes(20):
        raise ValueError("module address must be a nonzero EVM address")
    if len(fingerprint) != 32 or fingerprint == bytes(32):
        raise ValueError("fingerprint must be a nonzero bytes32")
    if len(request_id) != 32 or request_id == bytes(32):
        raise ValueError("request_id must be a nonzero bytes32")
    return GovernanceCall(
        module_address,
        0,
        _ALLOW_DUPLICATE_SELECTOR + encode(["bytes32", "bytes32"], [fingerprint, request_id]),
    )


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


def module_factory_create_data(
    *,
    asset: bytes,
    operational: Sequence[bytes],
    mandate: tuple[Any, ...],
    approvers: Sequence[bytes],
    buffers: Sequence[tuple[bytes, int, int]],
    aave_pool: bytes,
    salt: bytes,
) -> bytes:
    """Encode the factory's deterministic initializer call using its Solidity ABI."""
    if len(salt) != 32 or len(asset) != 20 or len(aave_pool) != 20:
        raise ValueError("module factory address or salt is invalid")
    if any(len(address) != 20 for address in (*operational, *approvers)):
        raise ValueError("module factory address is invalid")
    if any(len(wallet) != 20 for wallet, _, _ in buffers):
        raise ValueError("buffer wallet address is invalid")
    return _FACTORY_CREATE_SELECTOR + encode(
        [
            "address",
            "address[]",
            "(uint64,uint64,uint32,address,address,(uint128,uint128),(uint128,uint128),uint32,(uint128,uint128))",
            "address[]",
            "(address,uint256,uint256)[]",
            "address",
            "bytes32",
        ],
        [asset, operational, mandate, approvers, buffers, aave_pool, salt],
    )


def module_factory_predict_data(*, safe_t: bytes, salt: bytes) -> bytes:
    if len(safe_t) != 20 or len(salt) != 32:
        raise ValueError("Safe address or salt is invalid")
    return _FACTORY_PREDICT_SELECTOR + encode(["address", "bytes32"], [safe_t, salt])


def enable_module_data(module: bytes) -> bytes:
    if len(module) != 20:
        raise ValueError("module address is invalid")
    return _ENABLE_MODULE_SELECTOR + encode(["address"], [module])
