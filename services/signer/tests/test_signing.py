from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

import pytest
from eth_abi import encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_account.signers.local import LocalAccount
from eth_hash.auto import keccak
from fastapi.testclient import TestClient

from treasurypilot_core.eip712 import (
    PAY,
    REFILL,
    SUPPLY,
    SWAP_IN,
    WITHDRAW,
    plan_attestation_typed_data,
    plan_hash,
    step_id,
)
from treasurypilot_signer.config import Settings
from treasurypilot_signer.keys import ExecutorKeyNotConfigured
from treasurypilot_signer.main import create_app
from treasurypilot_signer.models import Fees, SignRequest
from treasurypilot_signer.rpc import JsonRpc, RpcFailure
from treasurypilot_signer.service import SignerFault, SigningService
from treasurypilot_signer.store import NonceAlreadyBound, ReservedNonce, StepAlreadyUsed

POLICY = Account.from_key(bytes(31) + b"\x08")
EXECUTOR = Account.from_key(bytes(31) + b"\x09")
MODULE = "0x" + "11" * 20
EXECUTOR_CONTRACT = "0x" + "22" * 20
WALLET = "0x" + "33" * 20
ASSET = "0x" + "44" * 20
SAFE_T = "0x" + "66" * 20
PAYEE = "0x" + "77" * 20
LIQUIDITY_ID = "0x" + "55" * 32
REQUEST_ID = "0x" + "00" * 32
ATTESTATION_ABI = "(bytes32,bytes32,bytes32[],uint256[],bytes32,address,uint64,uint256,bytes32)"
MANDATE_OUTPUTS = [
    "uint64",
    "uint64",
    "uint64",
    "uint32",
    "address",
    "address",
    "(uint128,uint128)",
    "(uint128,uint128)",
    "uint32",
    "(uint128,uint128)",
]


# Fixed per process: calldata embeds validUntil, so rebuilding a request across a
# second boundary would otherwise change the payload and trip PAYLOAD_MISMATCH.
VALID_UNTIL = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())


def _make_request(
    *,
    amount: int = 123,
    chain_id: int = 31337,
    nonce: int = 77,
    executor: LocalAccount = EXECUTOR,
    action: int = SUPPLY,
) -> SignRequest:
    step = {
        "seq": 0,
        "stepId": "0x" + step_id(LIQUIDITY_ID, action, WALLET).hex(),
        "action": action,
        "from": WALLET,
        "to": MODULE,
        "asset": ASSET,
        "amount": amount,
    }
    plan: dict[str, Any] = {
        "requestId": REQUEST_ID,
        "treasury": MODULE,
        "chainId": chain_id,
        "steps": [step],
        "feeCapWei": 10**18,
    }
    message = {
        "planHash": "0x" + plan_hash(REQUEST_ID, MODULE, chain_id, [step]).hex(),
        "requestId": REQUEST_ID,
        "stepIds": [step["stepId"]],
        "stepAmounts": [amount],
        "policyVersion": "0x" + "66" * 32,
        "executor": executor.address,
        "validUntil": VALID_UNTIL,
        "nonce": nonce,
        "evidenceDigest": "0x" + "77" * 32,
    }
    typed_data = plan_attestation_typed_data(message, chain_id=chain_id, verifying_contract=MODULE)
    signature = POLICY.sign_message(encode_typed_data(full_message=typed_data)).signature
    attestation = (
        bytes.fromhex(message["planHash"][2:]),
        bytes.fromhex(REQUEST_ID[2:]),
        [bytes.fromhex(step["stepId"][2:])],
        [amount],
        bytes.fromhex(message["policyVersion"][2:]),
        executor.address,
        message["validUntil"],
        nonce,
        bytes.fromhex(message["evidenceDigest"][2:]),
    )
    types = ["bytes32", "bytes32", "uint256", ATTESTATION_ABI, "bytes"]
    args = [
        bytes.fromhex(REQUEST_ID[2:]),
        bytes.fromhex(step["stepId"][2:]),
        amount,
        attestation,
        signature,
    ]
    function_name = "supply" if action == SUPPLY else "withdraw"
    calldata = keccak(
        function_name.encode()
        + b"(bytes32,bytes32,uint256,"
        + ATTESTATION_ABI.encode()
        + b",bytes)"
    )[:4]
    calldata += encode(types, args)
    return SignRequest(
        treasuryId="01890000-0000-7000-8000-000000000001",
        plan=plan,
        attestation=typed_data,
        signature="0x" + signature.hex(),
        stepSeq=0,
        payload={"to": EXECUTOR_CONTRACT, "data": "0x" + calldata.hex()},
        fees={
            "maxFeePerGas": 2_000_000_000,
            "maxPriorityFeePerGas": 1_000_000_000,
            "feeCapWei": 10**18,
        },
    )


def _make_swap_request(
    *,
    calldata_min_out: int = 190,
    plan_min_out: int | None = 190,
    venue: str = "TEST_ROUTER",
    amount_in: int = 100,
    nonce: int = 99,
    executor: LocalAccount = EXECUTOR,
) -> SignRequest:
    """A SWAP step: the executor's swapForGas carries no attestation, so the plan binds it."""
    chain_id, request_id = 31337, "0x" + "01" * 32
    step = {
        "seq": 0,
        "stepId": "0x" + step_id(request_id, SWAP_IN, SAFE_T).hex(),
        "action": SWAP_IN,
        "from": SAFE_T,
        "to": WALLET,  # the router
        "asset": ASSET,
        "amount": amount_in,
    }
    plan: dict[str, Any] = {
        "requestId": request_id,
        "treasury": MODULE,
        "chainId": chain_id,
        "steps": [step],
        "feeCapWei": 10**18,
    }
    if plan_min_out is not None:
        plan["swaps"] = {step["stepId"]: {"minOut": plan_min_out, "venue": venue}}
    message = {
        "planHash": "0x" + plan_hash(request_id, MODULE, chain_id, [step]).hex(),
        "requestId": request_id,
        "stepIds": [step["stepId"]],
        "stepAmounts": [amount_in],
        "policyVersion": "0x" + "66" * 32,
        "executor": executor.address,
        "validUntil": VALID_UNTIL,
        "nonce": nonce,
        "evidenceDigest": "0x" + "77" * 32,
    }
    typed_data = plan_attestation_typed_data(message, chain_id=chain_id, verifying_contract=MODULE)
    signature = POLICY.sign_message(encode_typed_data(full_message=typed_data)).signature
    calldata = keccak(b"swapForGas(bytes32,uint256,uint256)")[:4] + encode(
        ["bytes32", "uint256", "uint256"],
        [bytes.fromhex(step["stepId"][2:]), amount_in, calldata_min_out],
    )
    return SignRequest(
        treasuryId="01890000-0000-7000-8000-000000000001",
        plan=plan,
        attestation=typed_data,
        signature="0x" + signature.hex(),
        stepSeq=0,
        payload={"to": EXECUTOR_CONTRACT, "data": "0x" + calldata.hex()},
        fees={
            "maxFeePerGas": 2_000_000_000,
            "maxPriorityFeePerGas": 1_000_000_000,
            "feeCapWei": 10**18,
        },
    )


def _make_payment_request(
    *, refill: bool, nonce: int = 88, calldata_from: str | None = None
) -> SignRequest:
    action = REFILL if refill else PAY
    payment_request_id = "0x" + "aa" * 32
    step_from = SAFE_T if refill else WALLET
    step_to = WALLET if refill else PAYEE
    amount = 77 if refill else 123
    step = {
        "seq": 0,
        "stepId": "0x"
        + step_id(payment_request_id, action, step_to if refill else step_from).hex(),
        "action": action,
        "from": step_from,
        "to": step_to,
        "asset": ASSET,
        "amount": amount,
    }
    plan: dict[str, Any] = {
        "requestId": payment_request_id,
        "treasury": MODULE,
        "chainId": 31337,
        "steps": [step],
        "feeCapWei": 10**18,
    }
    message = {
        "planHash": "0x" + plan_hash(payment_request_id, MODULE, 31337, [step]).hex(),
        "requestId": payment_request_id,
        "stepIds": [step["stepId"]],
        "stepAmounts": [amount],
        "policyVersion": "0x" + "66" * 32,
        "executor": EXECUTOR.address,
        "validUntil": VALID_UNTIL,
        "nonce": nonce,
        "evidenceDigest": "0x" + "77" * 32,
    }
    typed_data = plan_attestation_typed_data(message, chain_id=31337, verifying_contract=MODULE)
    signature = POLICY.sign_message(encode_typed_data(full_message=typed_data)).signature
    approval = (
        bytes.fromhex(payment_request_id[2:]),
        bytes.fromhex(("0x" + "88" * 32)[2:]),
        bytes.fromhex(("0x" + "99" * 32)[2:]),
        MODULE,
        WALLET,
        ASSET,
        PAYEE,
        123,  # the later PAY amount differs from the REFILL amount
        0,
        0,
        int((datetime.now(UTC) + timedelta(minutes=10)).timestamp()),
        bytes.fromhex(("0x" + "bb" * 32)[2:]),
        int((datetime.now(UTC) + timedelta(minutes=10)).timestamp()),
        False,
    )
    attestation = (
        bytes.fromhex(message["planHash"][2:]),
        bytes.fromhex(payment_request_id[2:]),
        [bytes.fromhex(step["stepId"][2:])],
        [amount],
        bytes.fromhex(message["policyVersion"][2:]),
        EXECUTOR.address,
        message["validUntil"],
        nonce,
        bytes.fromhex(message["evidenceDigest"][2:]),
    )
    args: list[Any] = [approval, b"approver-signature", bytes.fromhex(step["stepId"][2:])]
    types = [
        "(bytes32,bytes32,bytes32,address,address,address,address,uint256,uint256,uint64,uint64,bytes32,uint64,bool)",
        "bytes",
        "bytes32",
    ]
    if refill:
        args.extend([calldata_from or step_from, step_to, amount])
        types.extend(["address", "address", "uint256"])
    else:
        args.append(amount)
        types.append("uint256")
    args.extend([attestation, signature])
    types.extend([ATTESTATION_ABI, "bytes"])
    function_name = "refill" if refill else "pay"
    calldata = keccak(f"{function_name}({','.join(types)})".encode())[:4] + encode(types, args)
    return SignRequest(
        treasuryId="01890000-0000-7000-8000-000000000001",
        plan=plan,
        attestation=typed_data,
        signature="0x" + signature.hex(),
        stepSeq=0,
        payload={"to": EXECUTOR_CONTRACT, "data": "0x" + calldata.hex()},
        fees={
            "maxFeePerGas": 2_000_000_000,
            "maxPriorityFeePerGas": 1_000_000_000,
            "feeCapWei": 10**18,
        },
    )


class FakeStore:
    def __init__(self) -> None:
        self.bindings: dict[int, bytes] = {}
        self.uses: dict[tuple[int, bytes], tuple[bytes, bytes, int]] = {}
        self.signed: dict[tuple[int, bytes], tuple[str, bytes]] = {}
        self.released = 0

    async def reserve(
        self,
        *,
        attestation_nonce: int,
        plan_hash: bytes,
        step_id: bytes,
        payload_hash: bytes,
        executor: bytes,
        pending_nonce: int,
    ) -> ReservedNonce:
        del executor
        existing_hash = self.bindings.get(attestation_nonce)
        if existing_hash is not None and existing_hash != plan_hash:
            raise NonceAlreadyBound
        self.bindings[attestation_nonce] = plan_hash
        key = (attestation_nonce, step_id)
        prior = self.uses.get(key)
        if prior is not None:
            if prior[:2] != (plan_hash, payload_hash):
                raise StepAlreadyUsed
            tx_hash, raw = self.signed.get(key, (None, None))
            return ReservedNonce(prior[2], True, tx_hash, raw)
        self.uses[key] = (plan_hash, payload_hash, pending_nonce)
        return ReservedNonce(pending_nonce, False)

    async def record_signed(
        self, *, attestation_nonce: int, step_id: bytes, tx_hash: str, raw_transaction: bytes
    ) -> None:
        self.signed[(attestation_nonce, step_id)] = (tx_hash, raw_transaction)

    async def release(
        self, *, attestation_nonce: int, step_id: bytes, executor: bytes, transaction_nonce: int
    ) -> None:
        del executor, transaction_nonce
        self.uses.pop((attestation_nonce, step_id))
        self.signed.pop((attestation_nonce, step_id), None)
        self.released += 1


class FakeRpc:
    def __init__(
        self,
        *,
        revert_simulation: bool = False,
        send_failure: RpcFailure | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> None:
        self.revert_simulation = revert_simulation
        self.send_failure = send_failure
        self.overrides = overrides or {}
        self.sent: list[str] = []
        self.calls: list[str] = []

    async def call(self, method: str, params: Sequence[Any]) -> Any:
        self.calls.append(method)
        if method in self.overrides:
            return self.overrides[method]
        if method == "eth_chainId":
            return "0x7a69"
        if method == "eth_getCode":
            return "0x6000"
        if method == "eth_call":
            data = params[0]["data"]
            if data == "0x" + keccak(b"mandate()")[:4].hex():
                return (
                    "0x"
                    + encode(
                        MANDATE_OUTPUTS,
                        [
                            1,
                            1,
                            2,
                            0,
                            EXECUTOR_CONTRACT,
                            EXECUTOR.address,
                            (0, 0),
                            (0, 0),
                            0,
                            (0, 0),
                        ],
                    ).hex()
                )
            if data == "0x" + keccak(b"safeT()")[:4].hex():
                return "0x" + "00" * 12 + SAFE_T[2:]
            if self.revert_simulation:
                raise RpcFailure(method, reverted=True)
            return "0x"
        if method == "eth_getBalance":
            return hex(10**18)
        if method == "eth_estimateGas":
            return "0x5208"
        if method == "eth_getTransactionCount":
            return "0x0"
        if method == "eth_sendRawTransaction":
            self.sent.append(params[0])
            if self.send_failure is not None:
                raise self.send_failure
            return "0x" + f"{len(self.sent):064x}"
        raise AssertionError(method)


def _service(
    *,
    rpc: FakeRpc | None = None,
    store: FakeStore | None = None,
    executor: LocalAccount = EXECUTOR,
    settings: Settings | None = None,
) -> tuple[SigningService, FakeRpc, FakeStore]:
    node = rpc or FakeRpc()
    database = store or FakeStore()
    settings = settings or Settings(
        allowed_chain_ids=[31337], trusted_policy_signers=[POLICY.address]
    )
    return SigningService(settings, database, node, lambda _treasury: executor), node, database


def _rpc(url: str, method: str, params: list[Any]) -> Any:
    request = UrlRequest(
        url,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=2) as response:
        body = json.loads(response.read())
    if "error" in body:
        raise RuntimeError(f"Anvil RPC {method} failed")
    return body["result"]


def _wait_for_receipt(url: str, transaction_hash: str) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        receipt = _rpc(url, "eth_getTransactionReceipt", [transaction_hash])
        if receipt is not None:
            return receipt
        time.sleep(0.05)
    pytest.fail("Anvil did not mine the signer transaction within 10 seconds")


@pytest.fixture
def anvil_url() -> Iterator[str]:
    if "TP_TEST_ANVIL_URL" in os.environ:  # a node started elsewhere (chain id 31337)
        yield os.environ["TP_TEST_ANVIL_URL"]
        return
    executable = shutil.which("anvil")
    if executable is None:
        pytest.skip("anvil is required for the signer broadcast integration test")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    process = subprocess.Popen(
        [executable, "--silent", "--port", str(port), "--chain-id", "31337"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("Anvil exited before it became ready")
            try:
                if _rpc(url, "eth_chainId", []) == "0x7a69":
                    break
            except (OSError, TimeoutError, URLError):
                time.sleep(0.1)
        else:
            pytest.fail("Anvil did not start")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=5)


def _return_runtime(data: bytes) -> str:
    length = len(data)
    offset = 14
    prefix = bytes.fromhex(f"61{length:04x}60{offset:02x}60003961{length:04x}6000f3")
    return "0x" + (prefix + data).hex()


def test_step_payload_must_match_the_attested_plan() -> None:
    service, node, _ = _service()
    request = _make_request()
    request.payload.data = _make_request(amount=124).payload.data

    with pytest.raises(SignerFault, match="PAYLOAD_MISMATCH"):
        asyncio.run(service.sign_and_send(request))
    assert node.sent == []


def test_withdraw_payload_is_supported() -> None:
    service, node, _ = _service()

    asyncio.run(service.sign_and_send(_make_request(action=WITHDRAW)))

    assert len(node.sent) == 1


@pytest.mark.parametrize("refill", [False, True])
def test_pay_and_refill_payloads_are_supported(refill: bool) -> None:
    service, node, _ = _service()

    asyncio.run(service.sign_and_send(_make_payment_request(refill=refill)))

    assert len(node.sent) == 1


def test_refill_from_wallet_must_match_the_planned_source() -> None:
    service, node, _ = _service()

    with pytest.raises(SignerFault, match="PAYLOAD_MISMATCH"):
        asyncio.run(service.sign_and_send(_make_payment_request(refill=True, calldata_from=PAYEE)))

    assert not node.sent


def test_swap_for_gas_payload_is_supported() -> None:
    service, node, _ = _service()

    asyncio.run(service.sign_and_send(_make_swap_request()))

    assert len(node.sent) == 1


@pytest.mark.parametrize(
    "request_fields",
    [
        {"calldata_min_out": 1},  # a lower bound than the engine computed
        {"plan_min_out": None},  # the plan names no swap
        {"venue": "UNISWAP"},  # anything but the labelled test router
        {"plan_min_out": 0, "calldata_min_out": 0},
    ],
)
def test_swap_for_gas_must_match_the_planned_min_out_and_test_router(
    request_fields: dict[str, Any],
) -> None:
    service, node, _ = _service()

    with pytest.raises(SignerFault, match="PAYLOAD_MISMATCH"):
        asyncio.run(service.sign_and_send(_make_swap_request(**request_fields)))
    assert node.sent == []


def test_swap_for_gas_amount_must_match_the_attested_amount() -> None:
    service, node, _ = _service()
    request = _make_swap_request()
    request.payload.data = _make_swap_request(amount_in=101).payload.data

    with pytest.raises(SignerFault, match="PAYLOAD_MISMATCH"):
        asyncio.run(service.sign_and_send(request))
    assert node.sent == []


def test_nonce_cannot_be_reused_for_a_different_plan_hash() -> None:
    service, _, _ = _service()
    asyncio.run(service.sign_and_send(_make_request()))

    with pytest.raises(SignerFault, match="NONCE_REUSED"):
        asyncio.run(service.sign_and_send(_make_request(amount=124)))


def test_reverted_simulation_is_never_broadcast() -> None:
    node = FakeRpc(revert_simulation=True)
    service, _, _ = _service(rpc=node)

    with pytest.raises(SignerFault, match="SIMULATION_REVERTED"):
        asyncio.run(service.sign_and_send(_make_request()))
    assert node.sent == []


def test_same_step_payload_can_be_resigned_with_its_original_transaction_nonce() -> None:
    service, node, _ = _service()
    first = asyncio.run(service.sign_and_send(_make_request()))
    replacement = asyncio.run(service.sign_and_send(_make_request()))

    assert first.nonce == replacement.nonce == 0
    assert len(node.sent) == 2


def test_replay_returns_the_original_hash_and_rebroadcasts_the_stored_transaction() -> None:
    service, node, _ = _service()
    first = asyncio.run(service.sign_and_send(_make_request()))
    changed_fees = _make_request().model_copy(
        update={"fees": Fees(maxFeePerGas=2, maxPriorityFeePerGas=1, feeCapWei=10**18)}
    )
    replay = asyncio.run(service.sign_and_send(changed_fees))

    assert replay.tx_hash == first.tx_hash
    assert node.sent[0] == node.sent[1]


def test_rejected_broadcast_releases_the_reservation_for_a_retry() -> None:
    rejected = RpcFailure("eth_sendRawTransaction", rejected=True)
    node = FakeRpc(send_failure=rejected)
    service, _, store = _service(rpc=node)

    with pytest.raises(SignerFault, match="BROADCAST_FAILED"):
        asyncio.run(service.sign_and_send(_make_request()))
    assert store.released == 1
    assert store.uses == {}

    node.send_failure = None
    assert asyncio.run(service.sign_and_send(_make_request())).nonce == 0


def test_ambiguous_broadcast_failure_keeps_the_reservation() -> None:
    node = FakeRpc(send_failure=RpcFailure("eth_sendRawTransaction"))
    service, _, store = _service(rpc=node)

    with pytest.raises(SignerFault, match="BROADCAST_FAILED"):
        asyncio.run(service.sign_and_send(_make_request()))
    assert store.released == 0
    assert len(store.uses) == 1


def test_signer_fee_ceiling_applies_without_a_plan_fee_cap() -> None:
    request = _make_request()
    request.plan.pop("feeCapWei")
    service, node, _ = _service(
        settings=Settings(
            allowed_chain_ids=[31337], trusted_policy_signers=[POLICY.address], max_fee_cap_wei=1
        )
    )

    with pytest.raises(SignerFault, match="FEE_CAP_EXCEEDED"):
        asyncio.run(service.sign_and_send(request))
    assert node.sent == []


def test_owner_accepted_plan_fee_cap_is_enforced_by_the_signer() -> None:
    request = _make_request()
    request.plan["feeCapWei"] = 1  # the accepted cap, far below gas_limit * maxFeePerGas
    service, node, store = _service()

    with pytest.raises(SignerFault, match="FEE_CAP_EXCEEDED"):
        asyncio.run(service.sign_and_send(request))
    assert node.sent == [] and not store.uses


def test_insufficient_executor_gas_refuses_before_reserving() -> None:
    service, node, store = _service(rpc=FakeRpc(overrides={"eth_getBalance": "0x1"}))

    with pytest.raises(SignerFault, match="INSUFFICIENT_GAS"):
        asyncio.run(service.sign_and_send(_make_request()))
    assert node.sent == []
    assert not store.uses


def test_failed_balance_lookup_fails_closed() -> None:
    class BalanceDown(FakeRpc):
        async def call(self, method: str, params: Sequence[Any]) -> Any:
            if method == "eth_getBalance":
                raise RpcFailure(method)
            return await super().call(method, params)

    service, node, store = _service(rpc=BalanceDown())

    with pytest.raises(SignerFault) as raised:
        asyncio.run(service.sign_and_send(_make_request()))
    assert raised.value.code == "CHAIN_RPC_UNAVAILABLE"
    assert node.sent == [] and not store.uses


@pytest.mark.parametrize(
    ("method", "value"),
    [
        ("eth_chainId", 5),
        ("eth_estimateGas", "nope"),
        ("eth_getTransactionCount", None),
        ("eth_getBalance", None),
    ],
)
def test_malformed_rpc_results_are_an_rpc_fault(method: str, value: Any) -> None:
    service, node, _ = _service(rpc=FakeRpc(overrides={method: value}))

    with pytest.raises(SignerFault) as raised:
        asyncio.run(service.sign_and_send(_make_request()))
    assert raised.value.code == "CHAIN_RPC_UNAVAILABLE"
    assert raised.value.status_code == 503
    assert node.sent == []


def test_non_ascii_shared_secret_is_unauthorized_not_a_server_error() -> None:
    app = create_app(settings_override=Settings(signer_shared_secret="expected-secret"))
    payload = _make_request().model_dump(mode="json", by_alias=True)

    with TestClient(app) as client:
        response = client.post(
            "/sign-and-send", json=payload, headers={"X-Signer-Secret": "sécret".encode("latin-1")}
        )

    assert response.status_code == 401


def test_non_allowlisted_chain_is_refused_before_rpc_or_broadcast() -> None:
    service, node, _ = _service()

    with pytest.raises(SignerFault, match="CHAIN_NOT_ALLOWED"):
        asyncio.run(service.sign_and_send(_make_request(chain_id=1)))
    assert node.calls == []
    assert node.sent == []


def test_signing_endpoint_requires_the_shared_secret() -> None:
    app = create_app(settings_override=Settings(signer_shared_secret="expected-secret"))
    payload = _make_request().model_dump(mode="json", by_alias=True)

    with TestClient(app) as client:
        unauthorized = client.post(
            "/sign-and-send", json=payload, headers={"X-Signer-Secret": "wrong-secret"}
        )
        unavailable = client.post(
            "/sign-and-send", json=payload, headers={"X-Signer-Secret": "expected-secret"}
        )

    assert unauthorized.status_code == 401
    assert unauthorized.json()["code"] == "UNAUTHORIZED"
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "SIGNER_NOT_CONFIGURED"


def test_signed_transaction_is_broadcast_to_anvil(anvil_url: str) -> None:
    executor = Account.from_key(
        "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
    )
    mandate_data = encode(
        MANDATE_OUTPUTS,
        [
            1,
            1,
            2,
            0,
            EXECUTOR_CONTRACT,
            executor.address,
            (0, 0),
            (0, 0),
            0,
            (0, 0),
        ],
    )
    _rpc(anvil_url, "anvil_setCode", [MODULE, _return_runtime(mandate_data)])
    _rpc(anvil_url, "anvil_setCode", [EXECUTOR_CONTRACT, "0x00"])

    rpc = JsonRpc(anvil_url)
    service = SigningService(
        Settings(allowed_chain_ids=[31337], trusted_policy_signers=[POLICY.address]),
        FakeStore(),
        rpc,
        lambda _treasury: executor,
    )

    async def sign_and_close_rpc() -> Any:
        try:
            return await service.sign_and_send(_make_request(executor=executor))
        finally:
            await rpc.close()

    result = asyncio.run(sign_and_close_rpc())

    receipt = _wait_for_receipt(anvil_url, result.tx_hash)
    transaction = _rpc(anvil_url, "eth_getTransactionByHash", [result.tx_hash])
    assert receipt["status"] == "0x1"
    assert transaction["from"].lower() == executor.address.lower()
    assert int(transaction["nonce"], 16) == result.nonce


def test_swap_for_gas_transaction_is_broadcast_to_anvil(anvil_url: str) -> None:
    executor = Account.from_key(
        "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
    )
    mandate_data = encode(
        MANDATE_OUTPUTS,
        [1, 1, 2, 0, EXECUTOR_CONTRACT, executor.address, (0, 0), (0, 0), 0, (0, 0)],
    )
    _rpc(anvil_url, "anvil_setCode", [MODULE, _return_runtime(mandate_data)])
    # The executor stub reverts unless the call is exactly swapForGas(bytes32,uint256,uint256).
    selector = keccak(b"swapForGas(bytes32,uint256,uint256)")[:4].hex()
    stub = (  # PUSH0 CALLDATALOAD PUSH1 0xe0 SHR PUSH4 sel EQ PUSH1 0x0e JUMPI PUSH0 PUSH0 REVERT JUMPDEST STOP
        "5f35" + "60e01c" + "63" + selector + "14" + "6011" + "57" + "5f5ffd" + "5b00"
    )
    _rpc(anvil_url, "anvil_setCode", [EXECUTOR_CONTRACT, "0x" + stub])

    rpc = JsonRpc(anvil_url)
    service = SigningService(
        Settings(allowed_chain_ids=[31337], trusted_policy_signers=[POLICY.address]),
        FakeStore(),
        rpc,
        lambda _treasury: executor,
    )
    request = _make_swap_request(executor=executor)

    async def sign_and_close_rpc() -> Any:
        try:
            return await service.sign_and_send(request)
        finally:
            await rpc.close()

    result = asyncio.run(sign_and_close_rpc())

    receipt = _wait_for_receipt(anvil_url, result.tx_hash)
    transaction = _rpc(anvil_url, "eth_getTransactionByHash", [result.tx_hash])
    assert receipt["status"] == "0x1"
    assert transaction["input"] == request.payload.data
    assert transaction["input"].startswith("0x" + selector)


def test_unmapped_treasury_key_is_refused_as_not_configured() -> None:
    def unmapped(_treasury: str) -> LocalAccount:
        raise ExecutorKeyNotConfigured

    service, _node, _store = _service()
    service._resolve_account = unmapped  # noqa: SLF001
    with pytest.raises(SignerFault) as fault:
        asyncio.run(service.sign_and_send(_make_request()))
    assert fault.value.code == "NOT_CONFIGURED"
