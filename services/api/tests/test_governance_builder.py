from __future__ import annotations

import asyncio

import pytest
from eth_abi import decode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_hash.auto import keccak

from treasurypilot_api.mandate.governance import (
    GovernanceCall,
    build_safe_transaction,
    decode_multisend_calls,
    enable_module_data,
    exec_transaction_data,
    module_factory_create_data,
    pack_signatures,
    safe_tx_hash,
)
from treasurypilot_api.mandate.governance_service import GovernanceFailure, GovernanceService
from treasurypilot_api.treasury.config import PlatformConfiguration

SAFE = bytes.fromhex("11" * 20)
MULTISEND = bytes.fromhex("22" * 20)
TARGET_A = bytes.fromhex("33" * 20)
TARGET_B = bytes.fromhex("44" * 20)


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


def test_module_factory_create_calldata_encodes_initializer_and_salt() -> None:
    asset = bytes.fromhex("55" * 20)
    operational = [bytes.fromhex("66" * 20)]
    executor = bytes.fromhex("77" * 20)
    guardian = bytes.fromhex("88" * 20)
    approver = bytes.fromhex("99" * 20)
    pool = bytes.fromhex("aa" * 20)
    salt = bytes.fromhex("bb" * 32)
    mandate = (1, 2, 3, executor, guardian, (4, 5), (6, 7), 8, (0, 0))
    buffers = [(SAFE, 10, 10), (operational[0], 20, 30)]

    data = module_factory_create_data(
        asset=asset,
        operational=operational,
        mandate=mandate,
        approvers=[approver],
        buffers=buffers,
        aave_pool=pool,
        salt=salt,
    )

    assert len(data) > 4
    assert (
        data[:4]
        == keccak(
            b"createDeterministic(address,address[],(uint64,uint64,uint32,address,address,(uint128,uint128),(uint128,uint128),uint32,(uint128,uint128)),address[],(address,uint256,uint256)[],address,bytes32)"
        )[:4]
    )
    decoded = decode(
        [
            "address",
            "address[]",
            "(uint64,uint64,uint32,address,address,(uint128,uint128),(uint128,uint128),uint32,(uint128,uint128))",
            "address[]",
            "(address,uint256,uint256)[]",
            "address",
            "bytes32",
        ],
        data[4:],
    )

    def as_bytes(address: str) -> bytes:
        return bytes.fromhex(address[2:])

    assert as_bytes(decoded[0]) == asset
    assert [as_bytes(address) for address in decoded[1]] == operational
    assert decoded[2] == (
        1,
        2,
        3,
        "0x" + executor.hex(),
        "0x" + guardian.hex(),
        (4, 5),
        (6, 7),
        8,
        (0, 0),
    )
    assert [as_bytes(address) for address in decoded[3]] == [approver]
    assert [
        (as_bytes(wallet), minimum, target) for wallet, minimum, target in decoded[4]
    ] == buffers
    assert as_bytes(decoded[5]) == pool
    assert decoded[6] == salt
    assert enable_module_data(SAFE)[:4] == keccak(b"enableModule(address)")[:4]


def test_module_setup_fails_closed_when_factory_manifest_is_missing() -> None:
    service = GovernanceService(None, None, PlatformConfiguration(chains=(), manifests=()))

    with pytest.raises(GovernanceFailure, match="verified TREASURY_MODULE_FACTORY") as error:
        asyncio.run(service._verified_deployment(11155111, "TREASURY_MODULE_FACTORY", "1.0.0"))

    assert error.value.status == 503
    assert error.value.code == "MODULE_DEPLOYMENT_UNAVAILABLE"


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
