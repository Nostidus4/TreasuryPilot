from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from eth_abi import decode, encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_hash.auto import keccak

from treasurypilot_api.mandate.governance import (
    GovernanceCall,
    build_safe_transaction,
    decode_multisend_calls,
    exec_transaction_data,
    pack_signatures,
    safe_tx_hash,
)

_ROOT = Path(__file__).resolve().parents[3]
_OUT = _ROOT / "contracts" / "out"
_CHAIN_ID = 31337
_ZERO_ADDRESS = "0x" + "00" * 20
_OWNER_KEYS = tuple(bytes.fromhex(f"{number:064x}") for number in (1, 2, 3))
_RECEIVER = "0x" + "a1" * 20
_SPENDER = "0x" + "b2" * 20
_MINT_AMOUNT = 123_456
_ALLOWANCE = 78_900


def _rpc(url: str, method: str, params: list[object]) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
    if "error" in payload:
        raise AssertionError(f"{method} failed: {payload['error']}")
    return payload["result"]


def _artifact(name: str) -> dict[str, Any]:
    matches = list(_OUT.rglob(f"{name}.json"))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected one Foundry artifact for {name}, found {len(matches)}")
    return json.loads(matches[0].read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def governance_artifacts() -> dict[str, dict[str, Any]]:
    required = os.environ.get("TP_REQUIRE_GOVERNANCE_ANVIL") == "1"
    try:
        return {
            name: _artifact(name)
            for name in ("Safe", "SafeProxyFactory", "MultiSendCallOnly", "TestUSDC")
        }
    except (FileNotFoundError, OSError) as error:
        reason = f"build contracts first to run the Safe governance integration test: {error}"
        if required:
            pytest.fail(reason)
        pytest.skip(reason)


@pytest.fixture(scope="module")
def anvil_url() -> Iterator[str]:
    configured_url = os.environ.get("TP_TEST_GOVERNANCE_ANVIL_URL")
    if configured_url:
        yield configured_url
        return

    binary = shutil.which("anvil")
    if binary is None:
        if os.environ.get("TP_REQUIRE_GOVERNANCE_ANVIL") == "1":
            pytest.fail("anvil is required for the Safe governance integration test")
        pytest.skip("anvil is required for the Safe governance integration test")

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    process = subprocess.Popen(
        [
            binary,
            "--silent",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--chain-id",
            str(_CHAIN_ID),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if process.poll() is not None:
                pytest.fail("anvil exited before the RPC endpoint became available")
            try:
                if int(_rpc(url, "eth_chainId", []), 16) == _CHAIN_ID:
                    break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            pytest.fail("anvil did not start")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=5)


def _bytecode(artifact: dict[str, Any]) -> str:
    bytecode = artifact.get("bytecode")
    if isinstance(bytecode, dict):
        bytecode = bytecode.get("object")
    if not isinstance(bytecode, str) or not bytecode:
        raise AssertionError("Foundry artifact has no deployable bytecode")
    return bytecode if bytecode.startswith("0x") else "0x" + bytecode


def _wait_receipt(url: str, transaction_hash: str) -> dict[str, Any]:
    for _ in range(100):
        receipt = _rpc(url, "eth_getTransactionReceipt", [transaction_hash])
        if receipt is not None:
            return receipt
        time.sleep(0.1)
    raise AssertionError(f"transaction was not mined: {transaction_hash}")


def _deploy(url: str, sender: str, artifact: dict[str, Any]) -> str:
    transaction_hash = _rpc(
        url,
        "eth_sendTransaction",
        [{"from": sender, "data": _bytecode(artifact), "gas": hex(12_000_000)}],
    )
    receipt = _wait_receipt(url, transaction_hash)
    assert receipt["status"] == "0x1", receipt
    address = receipt.get("contractAddress")
    assert isinstance(address, str) and address != _ZERO_ADDRESS
    return address


def _calldata(signature: str, types: list[str], values: list[object]) -> bytes:
    return keccak(signature.encode())[:4] + encode(types, values)


def _eth_call(url: str, to: str, data: bytes) -> bytes:
    result = _rpc(url, "eth_call", [{"to": to, "data": "0x" + data.hex()}, "latest"])
    return bytes.fromhex(result[2:])


def _send_call(url: str, sender: str, to: str, data: bytes) -> dict[str, Any]:
    transaction_hash = _rpc(
        url,
        "eth_sendTransaction",
        [
            {
                "from": sender,
                "to": to,
                "data": "0x" + data.hex(),
                "gas": hex(12_000_000),
            }
        ],
    )
    return _wait_receipt(url, transaction_hash)


def test_app_built_two_of_three_governance_bundle_executes_on_safe_141(
    governance_artifacts: dict[str, dict[str, Any]], anvil_url: str
) -> None:
    chain_id = int(_rpc(anvil_url, "eth_chainId", []), 16)
    assert chain_id == _CHAIN_ID
    accounts = _rpc(anvil_url, "eth_accounts", [])
    assert len(accounts) >= 4
    deployer, executor = accounts[0], accounts[1]

    singleton = _deploy(anvil_url, deployer, governance_artifacts["Safe"])
    factory = _deploy(anvil_url, deployer, governance_artifacts["SafeProxyFactory"])
    multisend = _deploy(anvil_url, deployer, governance_artifacts["MultiSendCallOnly"])
    token = _deploy(anvil_url, deployer, governance_artifacts["TestUSDC"])

    owner_accounts = [Account.from_key(key) for key in _OWNER_KEYS]
    owner_addresses = [account.address for account in owner_accounts]
    setup = _calldata(
        "setup(address[],uint256,address,bytes,address,address,uint256,address)",
        ["address[]", "uint256", "address", "bytes", "address", "address", "uint256", "address"],
        [owner_addresses, 2, _ZERO_ADDRESS, b"", _ZERO_ADDRESS, _ZERO_ADDRESS, 0, _ZERO_ADDRESS],
    )
    create_proxy = _calldata(
        "createProxyWithNonce(address,bytes,uint256)",
        ["address", "bytes", "uint256"],
        [singleton, setup, 247],
    )
    prediction = bytes.fromhex(
        _rpc(
            anvil_url,
            "eth_call",
            [{"from": deployer, "to": factory, "data": "0x" + create_proxy.hex()}, "latest"],
        )[2:]
    )
    safe = decode(["address"], prediction)[0]
    safe_receipt = _send_call(anvil_url, deployer, factory, create_proxy)
    assert safe_receipt["status"] == "0x1", safe_receipt

    version_data = _calldata("VERSION()", [], [])
    assert decode(["string"], _eth_call(anvil_url, safe, version_data))[0] == "1.4.1"
    assert (
        int.from_bytes(_eth_call(anvil_url, safe, _calldata("getThreshold()", [], [])), "big") == 2
    )
    configured_owners = decode(
        ["address[]"], _eth_call(anvil_url, safe, _calldata("getOwners()", [], []))
    )[0]
    assert {address.lower() for address in configured_owners} == {
        address.lower() for address in owner_addresses
    }

    token_address = bytes.fromhex(token[2:])
    calls = (
        GovernanceCall(
            token_address,
            0,
            _calldata("mint(address,uint256)", ["address", "uint256"], [_RECEIVER, _MINT_AMOUNT]),
        ),
        GovernanceCall(
            token_address,
            0,
            _calldata("approve(address,uint256)", ["address", "uint256"], [_SPENDER, _ALLOWANCE]),
        ),
    )
    safe_transaction = build_safe_transaction(
        calls, multisend_call_only=bytes.fromhex(multisend[2:])
    )
    assert decode_multisend_calls(safe_transaction.data) == calls

    typed_data = safe_transaction.typed_data(
        chain_id=chain_id, safe_address=bytes.fromhex(safe[2:]), nonce=0
    )
    signatures = [
        (
            bytes.fromhex(account.address[2:]),
            bytes(account.sign_message(encode_typed_data(full_message=typed_data)).signature),
        )
        for account in owner_accounts[:2]
    ]
    packed_signatures = pack_signatures(
        typed_data,
        signatures,
        [bytes.fromhex(account.address[2:]) for account in owner_accounts],
        threshold=2,
    )
    python_hash = safe_tx_hash(typed_data)
    onchain_hash = _eth_call(
        anvil_url,
        safe,
        _calldata(
            "getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,uint256)",
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
                "uint256",
            ],
            [
                safe_transaction.to,
                safe_transaction.value,
                safe_transaction.data,
                safe_transaction.operation,
                0,
                0,
                0,
                _ZERO_ADDRESS,
                _ZERO_ADDRESS,
                0,
            ],
        ),
    )
    assert onchain_hash == python_hash

    exec_data = exec_transaction_data(
        safe_transaction, nonce=0, packed_signatures=packed_signatures
    )
    execution_receipt = _send_call(anvil_url, executor, safe, exec_data)
    assert execution_receipt["status"] == "0x1", execution_receipt
    success_topic = "0x" + keccak(b"ExecutionSuccess(bytes32,uint256)").hex()
    assert any(
        log["address"].lower() == safe.lower() and log["topics"][0] == success_topic
        for log in execution_receipt["logs"]
    )

    balance = _eth_call(
        anvil_url,
        token,
        _calldata("balanceOf(address)", ["address"], [_RECEIVER]),
    )
    allowance = _eth_call(
        anvil_url,
        token,
        _calldata("allowance(address,address)", ["address", "address"], [safe, _SPENDER]),
    )
    assert int.from_bytes(balance, "big") == _MINT_AMOUNT
    assert int.from_bytes(allowance, "big") == _ALLOWANCE
    assert int.from_bytes(_eth_call(anvil_url, safe, _calldata("nonce()", [], [])), "big") == 1
