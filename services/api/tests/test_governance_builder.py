from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest
from eth_abi import decode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_hash.auto import keccak

from treasurypilot_api.mandate.governance import (
    GovernanceCall,
    build_borrow_authorization_call,
    build_repay_authorization_call,
    build_safe_transaction,
    decode_multisend_calls,
    exec_transaction_data,
    pack_signatures,
    safe_tx_hash,
)
from treasurypilot_api.mandate.governance_service import GovernanceService
from treasurypilot_api.mandate.models import GovernanceTx, GovernanceTxPurpose, GovernanceTxStatus

SAFE = bytes.fromhex("11" * 20)
MULTISEND = bytes.fromhex("22" * 20)
TARGET_A = bytes.fromhex("33" * 20)
TARGET_B = bytes.fromhex("44" * 20)
PLAN = bytes.fromhex("55" * 32)


def test_borrow_authorization_keeps_proposal_values_exact() -> None:
    amount = 9_500_000_000
    expiry = 1_823_456_789
    minimum_health_factor = 1_350_000_000_000_000_000
    maximum_rate_ray = 512_000_000_000_000_000_000_000_000

    call = build_borrow_authorization_call(
        TARGET_A,
        plan_id=PLAN,
        amount=amount,
        expiry=expiry,
        min_health_factor=minimum_health_factor,
        max_rate_ray=maximum_rate_ray,
    )

    assert call.to == TARGET_A
    assert call.value == 0
    assert call.data[:4] == keccak(b"authorizeBorrow(bytes32,uint256,uint64,uint256,uint256)")[:4]
    assert decode(["bytes32", "uint256", "uint64", "uint256", "uint256"], call.data[4:]) == (
        PLAN,
        amount,
        expiry,
        minimum_health_factor,
        maximum_rate_ray,
    )


def test_repay_authorization_keeps_proposal_values_exact() -> None:
    amount = 2**200 + 9
    expiry = 1_823_456_789

    call = build_repay_authorization_call(TARGET_B, plan_id=PLAN, amount=amount, expiry=expiry)

    assert call.data[:4] == keccak(b"authorizeRepay(bytes32,uint256,uint64)")[:4]
    assert decode(["bytes32", "uint256", "uint64"], call.data[4:]) == (
        PLAN,
        amount,
        expiry,
    )


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"plan_id": b"short"}, "bytes32"),
        ({"amount": 0}, "positive"),
        ({"amount": 1 << 256}, "uint256"),
        ({"expiry": 0}, "uint64"),
        ({"expiry": 1 << 64}, "uint64"),
        ({"min_health_factor": 0}, "positive"),
        ({"min_health_factor": 1 << 256}, "uint256"),
        ({"max_rate_ray": 0}, "positive"),
        ({"max_rate_ray": 1 << 256}, "uint256"),
    ],
)
def test_borrow_authorization_rejects_invalid_values(
    kwargs: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "plan_id": PLAN,
        "amount": 1,
        "expiry": 1,
        "min_health_factor": 1,
        "max_rate_ray": 1,
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        build_borrow_authorization_call(TARGET_A, **values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"plan_id": b"short"}, "bytes32"),
        ({"amount": 0}, "positive"),
        ({"amount": 1 << 256}, "uint256"),
        ({"expiry": 0}, "uint64"),
        ({"expiry": 1 << 64}, "uint64"),
    ],
)
def test_repay_authorization_rejects_invalid_values(
    kwargs: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {"plan_id": PLAN, "amount": 1, "expiry": 1}
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        build_repay_authorization_call(TARGET_B, **values)  # type: ignore[arg-type]


def test_direct_call_keeps_safe_call_fields() -> None:
    call = GovernanceCall(TARGET_A, 7, bytes.fromhex("aabb"))

    tx = build_safe_transaction([call])

    assert (tx.to, tx.value, tx.data, tx.operation) == (TARGET_A, 7, b"\xaa\xbb", 0)
    assert tx.calls == (call,)


def test_multisend_call_round_trips_each_decoded_call() -> None:
    calls = (
        GovernanceCall(TARGET_A, 0, bytes.fromhex("12345678")),
        GovernanceCall(TARGET_B, 19, bytes.fromhex("deadbeef")),
    )

    tx = build_safe_transaction(calls, multisend_call_only=MULTISEND)

    assert tx.to == MULTISEND
    assert tx.operation == 1  # Safe delegatecalls MultiSendCallOnly.
    assert tx.value == 0
    assert decode_multisend_calls(tx.data) == calls


def test_multisend_requires_configured_call_only_and_nonempty_calls() -> None:
    with pytest.raises(ValueError, match="at least one"):
        build_safe_transaction([])
    with pytest.raises(ValueError, match="MultiSendCallOnly"):
        build_safe_transaction(
            [GovernanceCall(TARGET_A, 0, b"1"), GovernanceCall(TARGET_B, 0, b"2")]
        )


def test_safe_tx_typed_data_hashes_and_packs_owner_signatures_in_address_order() -> None:
    account_a = Account.from_key(bytes.fromhex("01" * 32))
    account_b = Account.from_key(bytes.fromhex("02" * 32))
    tx = build_safe_transaction([GovernanceCall(TARGET_A, 0, b"\x12\x34\x56\x78")])
    typed_data = tx.typed_data(chain_id=31337, safe_address=SAFE, nonce=4)
    signed_a = account_a.sign_message(encode_typed_data(full_message=typed_data)).signature
    signed_b = account_b.sign_message(encode_typed_data(full_message=typed_data)).signature

    packed = pack_signatures(
        typed_data,
        [
            (bytes.fromhex(account_b.address[2:]), bytes(signed_b)),
            (bytes.fromhex(account_a.address[2:]), bytes(signed_a)),
        ],
        [bytes.fromhex(account_a.address[2:]), bytes.fromhex(account_b.address[2:])],
        2,
    )

    assert safe_tx_hash(typed_data) == bytes(
        account_a.sign_message(encode_typed_data(full_message=typed_data)).message_hash
    )
    assert packed == b"".join(
        [
            bytes(signed_a)
            if account_a.address.lower() < account_b.address.lower()
            else bytes(signed_b),
            bytes(signed_b)
            if account_a.address.lower() < account_b.address.lower()
            else bytes(signed_a),
        ]
    )
    exec_data = exec_transaction_data(tx, nonce=4, packed_signatures=packed)
    assert len(exec_data[:4]) == 4
    fields = decode(
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
        exec_data[4:],
    )
    assert fields == (
        "0x" + TARGET_A.hex(),
        0,
        b"\x12\x34\x56\x78",
        0,
        0,
        0,
        0,
        "0x" + "00" * 20,
        "0x" + "00" * 20,
        packed,
    )


def test_signature_from_non_owner_is_rejected() -> None:
    owner = Account.from_key(bytes.fromhex("01" * 32))
    outsider = Account.from_key(bytes.fromhex("03" * 32))
    typed_data = build_safe_transaction([GovernanceCall(TARGET_A, 0, b"")]).typed_data(
        chain_id=31337, safe_address=SAFE, nonce=0
    )
    signature = bytes(outsider.sign_message(encode_typed_data(full_message=typed_data)).signature)

    with pytest.raises(ValueError, match="NOT_SAFE_OWNER"):
        pack_signatures(
            typed_data,
            [(bytes.fromhex(outsider.address[2:]), signature)],
            [bytes.fromhex(owner.address[2:])],
            1,
        )


class _FakeVerifier:
    def __init__(self, receipt: Mapping[str, object] | None) -> None:
        self._receipt = receipt

    async def call(self, chain_id: int, method: str, params: list[object]) -> object:
        return self._receipt


def _receipt_status(receipt: Mapping[str, object] | None) -> GovernanceTxStatus | None:
    service = GovernanceService(None, _FakeVerifier(receipt), None)
    return asyncio.run(service._receipt_status(1, b"\x01" * 32, SAFE, b"\x02" * 32))


def _execution_log(event: str) -> dict[str, object]:
    topic = "0x" + keccak(event.encode()).hex()
    return {"address": "0x" + SAFE.hex(), "topics": [topic, "0x" + "02" * 32]}


def test_receipt_status_distinguishes_outer_revert_from_safe_outcome() -> None:
    assert _receipt_status(None) is None
    # Outer tx reverted: the Safe nonce is unconsumed, so the row can be reopened.
    assert _receipt_status({"status": "0x0", "logs": []}) == GovernanceTxStatus.READY
    assert _receipt_status({"status": "0x1", "logs": []}) is None
    ok = {"status": "0x1", "logs": [_execution_log("ExecutionSuccess(bytes32,uint256)")]}
    assert _receipt_status(ok) == GovernanceTxStatus.EXECUTED
    failed = {"status": "0x1", "logs": [_execution_log("ExecutionFailure(bytes32,uint256)")]}
    assert _receipt_status(failed) == GovernanceTxStatus.FAILED


def test_summary_flags_delegatecall() -> None:
    call = GovernanceCall(TARGET_A, 0, b"\x12\x34\x56\x78", 1)
    row = GovernanceTx(purpose=GovernanceTxPurpose.PAUSE, calls=[call.as_json()])

    assert "DELEGATECALL call 1" in GovernanceService._summary(row)
