from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
from eth_abi import decode, encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_hash.auto import keccak

from treasurypilot_api.mandate.api import CreateModuleSetupRequest
from treasurypilot_api.mandate.governance import (
    BorrowAuthorizationProposal,
    GovernanceCall,
    RepayAuthorizationProposal,
    build_allow_duplicate_call,
    build_borrow_authorization_call,
    build_cancel_request_call,
    build_grant_exception_call,
    build_repay_authorization_call,
    build_revoke_exception_call,
    build_safe_transaction,
    decode_multisend_calls,
    enable_module_data,
    exec_transaction_data,
    module_factory_create_data,
    pack_signatures,
    safe_tx_hash,
)
from treasurypilot_api.mandate.governance_service import (
    GovernanceFailure,
    GovernanceService,
    _address_bytes,
    _asset_policy_events,
)
from treasurypilot_api.mandate.models import GovernanceTx, GovernanceTxPurpose, GovernanceTxStatus
from treasurypilot_api.treasury.config import PlatformConfiguration

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

    proposal = BorrowAuthorizationProposal(
        plan_id=PLAN,
        amount=amount,
        expiry=expiry,
        min_health_factor=minimum_health_factor,
        max_rate_ray=maximum_rate_ray,
    )
    call = build_borrow_authorization_call(TARGET_A, proposal=proposal)

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

    # The exact proposal call is retained in both the governance record and the Safe
    # transaction data that owners sign.
    row = GovernanceTx(purpose=GovernanceTxPurpose.MANDATE, calls=[call.as_json()])
    assert row.calls == [
        {
            "to": "0x" + TARGET_A.hex(),
            "value": "0",
            "data": "0x" + call.data.hex(),
            "operation": 0,
        }
    ]
    typed_message = build_safe_transaction([call]).typed_data(
        chain_id=11155111, safe_address=SAFE, nonce=7
    )["message"]
    assert typed_message["to"] == "0x" + TARGET_A.hex()
    assert typed_message["data"] == "0x" + call.data.hex()

    with pytest.raises(FrozenInstanceError):
        proposal.amount = amount + 1  # type: ignore[misc]


def test_cancel_request_call_encodes_module_selector_and_request_id() -> None:
    call = build_cancel_request_call(TARGET_A, request_id=PLAN)

    assert (call.to, call.value, call.operation) == (TARGET_A, 0, 0)
    assert call.data[:4] == keccak(b"cancelRequest(bytes32)")[:4]
    assert decode(["bytes32"], call.data[4:]) == (PLAN,)
    with pytest.raises(ValueError, match="bytes32"):
        build_cancel_request_call(TARGET_A, request_id=b"short")


def test_exception_and_duplicate_calls_bind_the_exact_request_values() -> None:
    request_id = bytes.fromhex("12" * 32)
    fingerprint = bytes.fromhex("34" * 32)
    payee = bytes.fromhex("56" * 20)
    amount = 2**90 + 17
    expiry = 1_900_000_000

    grant = build_grant_exception_call(
        TARGET_A,
        request_id=request_id,
        amount=amount,
        payee=payee,
        expiry=expiry,
    )
    assert grant.to == TARGET_A
    assert grant.data[:4] == keccak(b"grantException(bytes32,uint128,address,uint64)")[:4]
    assert decode(["bytes32", "uint128", "address", "uint64"], grant.data[4:]) == (
        request_id,
        amount,
        "0x" + payee.hex(),
        expiry,
    )

    revoke = build_revoke_exception_call(TARGET_A, request_id=request_id)
    assert revoke.data[:4] == keccak(b"revokeException(bytes32)")[:4]
    assert decode(["bytes32"], revoke.data[4:]) == (request_id,)

    duplicate = build_allow_duplicate_call(TARGET_A, fingerprint=fingerprint, request_id=request_id)
    assert duplicate.data[:4] == keccak(b"allowDuplicate(bytes32,bytes32)")[:4]
    assert decode(["bytes32", "bytes32"], duplicate.data[4:]) == (fingerprint, request_id)

    with pytest.raises(ValueError, match="uint128"):
        build_grant_exception_call(
            TARGET_A,
            request_id=request_id,
            amount=1 << 128,
            payee=payee,
            expiry=expiry,
        )


def test_repay_authorization_keeps_proposal_values_exact() -> None:
    amount = 2**200 + 9
    expiry = 1_823_456_789

    call = build_repay_authorization_call(
        TARGET_B, proposal=RepayAuthorizationProposal(PLAN, amount, expiry)
    )

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
        ({"plan_id": bytearray(PLAN)}, "bytes32"),
        ({"plan_id": "11" * 16}, "bytes32"),
        ({"amount": 1.0}, "int"),
        ({"amount": True}, "int"),
        ({"expiry": 1.0}, "int"),
        ({"amount": 0}, "positive"),
        ({"amount": 1 << 256}, "uint256"),
        ({"expiry": 0}, "uint64"),
        ({"expiry": 1 << 64}, "uint64"),
        ({"min_health_factor": 1.5}, "int"),
        ({"max_rate_ray": True}, "int"),
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
        BorrowAuthorizationProposal(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"plan_id": b"short"}, "bytes32"),
        ({"plan_id": bytearray(PLAN)}, "bytes32"),
        ({"plan_id": "11" * 16}, "bytes32"),
        ({"amount": 1.0}, "int"),
        ({"amount": True}, "int"),
        ({"expiry": 1.0}, "int"),
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
        RepayAuthorizationProposal(**values)  # type: ignore[arg-type]


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


def test_asset_policy_readback_decodes_the_execution_receipt_values() -> None:
    module = bytes.fromhex("66" * 20)
    asset = bytes.fromhex("77" * 20)
    topic = "0x" + keccak(b"AssetPolicySet(address,bool,uint128,uint128,uint128,uint128)").hex()
    receipt = {
        "logs": [
            {
                "address": "0x" + module.hex(),
                "topics": [topic, "0x" + "00" * 12 + asset.hex()],
                "data": "0x"
                + encode(
                    ["bool", "uint128", "uint128", "uint128", "uint128"],
                    [True, 100, 500, 20, 80],
                ).hex(),
            }
        ]
    }

    assert _asset_policy_events(receipt, module) == {"0x" + asset.hex(): (True, 100, 500, 20, 80)}


def test_chain_address_normalization_accepts_abi_address_strings() -> None:
    address = bytes.fromhex("ab" * 20)

    assert _address_bytes("0x" + address.hex()) == address
    assert _address_bytes(address) == address


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


def _setup_payload(buffers: list[dict[str, str]], approvers: list[str] | None = None) -> dict:
    limit = {"perRequest": "1", "daily": "2"}
    return {
        "mandate": {
            "validFrom": "2030-01-01T00:00:00Z",
            "expiresAt": "2031-01-01T00:00:00Z",
            "payeeCoolingSeconds": 60,
            "executor": "0x" + "77" * 20,
            "pay": limit,
            "refill": limit,
            "supply": {"perRequest": "0", "daily": "0"},
            "approvalMaxAge": 60,
            "approvers": approvers or ["0x" + "99" * 20],
        },
        "buffers": buffers,
    }


def test_module_setup_request_rejects_duplicate_buffer_wallets_and_bad_approvers() -> None:
    wallet = {"wallet": "0x" + "AA" * 20, "minimum": "1", "target": "2"}
    other = {"wallet": "0x" + "bb" * 20, "minimum": "1", "target": "2"}

    CreateModuleSetupRequest.model_validate(_setup_payload([wallet, other]))
    with pytest.raises(ValueError, match="each wallet once"):
        CreateModuleSetupRequest.model_validate(
            _setup_payload([wallet, {**wallet, "wallet": wallet["wallet"].lower()}, other])
        )
    with pytest.raises(ValueError, match="String should match pattern"):
        CreateModuleSetupRequest.model_validate(_setup_payload([wallet, other], ["0x12"]))


def test_rpc_first_skips_failing_providers_and_unparseable_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = {"http://a": RuntimeError("down"), "http://b": None, "http://c": "0x01"}

    def fake_rpc(url: str, method: str, params: list) -> object:
        answer = answers[url]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr("treasurypilot_api.mandate.governance_service._rpc", fake_rpc)
    service = GovernanceService(None, None, PlatformConfiguration(chains=(), manifests=()))
    chain = type("Chain", (), {"rpc_urls": ("ws://x", "http://a", "http://b", "http://c")})()

    assert asyncio.run(service._rpc_first(chain, "eth_call", [])) == "0x01"
    assert asyncio.run(service._rpc_first(chain, "eth_call", [], lambda _: None)) is None


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


def test_refresh_marks_open_transaction_superseded_after_external_nonce_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        async def __aenter__(self) -> _SessionContext:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def begin(self) -> _SessionContext:
            return self

    row = SimpleNamespace(
        chain_id=31337,
        safe_address=SAFE,
        safe_nonce=4,
        status=GovernanceTxStatus.COLLECTING,
        purpose=GovernanceTxPurpose.PAUSE,
        exec_tx_hash=None,
        safe_tx_hash=b"\x11" * 32,
    )
    service = GovernanceService(None, None, PlatformConfiguration(chains=(), manifests=()))

    async def fake_row(
        _session: object, _organization_id: object, _tx_id: object
    ) -> SimpleNamespace:
        return row

    async def consumed_nonce(_chain_id: int, _safe: bytes) -> int:
        return 5

    monkeypatch.setattr(service, "_sessions", lambda: _SessionContext())
    monkeypatch.setattr(service, "_row", fake_row)
    monkeypatch.setattr(service, "_nonce", consumed_nonce)

    asyncio.run(service.refresh(organization_id=object(), governance_tx_id=object()))

    assert row.status == GovernanceTxStatus.SUPERSEDED


def test_summary_flags_delegatecall() -> None:
    call = GovernanceCall(TARGET_A, 0, b"\x12\x34\x56\x78", 1)
    row = GovernanceTx(purpose=GovernanceTxPurpose.PAUSE, calls=[call.as_json()])

    assert "DELEGATECALL call 1" in GovernanceService._summary(row)
