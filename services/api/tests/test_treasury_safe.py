from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from eth_abi import encode as abi_encode
from eth_utils import keccak, to_checksum_address

from treasurypilot_api.treasury.config import (
    ChainConfig,
    DeploymentConfig,
    DeploymentManifest,
    PlatformConfiguration,
)
from treasurypilot_api.treasury.safe import (
    RpcSafeVerifier,
    RpcUnavailable,
    SafeVerificationError,
    _ProviderError,
    _Reverted,
    safe_singletons,
)
from treasurypilot_api.treasury.safe import (
    _rpc as safe_rpc,
)

SINGLETON_L1 = "0x41675c099f32341bf84bfc5382af534df5c7461a"
SINGLETON_L2 = "0x29fcb43b46531bca003ddc8fcb67ffe91900c762"
UNLISTED_SINGLETON = "0x" + "99" * 20
OWNERS = ["0x" + f"{i:040x}" for i in (0xA1, 0xA2, 0xA3)]
EOA = "0x" + "e0" * 20
CHAIN_ID = 31337


def _selector(signature: str) -> str:
    return "0x" + keccak(text=signature)[:4].hex()


VERSION = _selector("VERSION()")
GET_OWNERS = _selector("getOwners()")
GET_THRESHOLD = _selector("getThreshold()")


def safe_answers(
    *, version: str = "1.4.1", owners: list[str] | None = None, threshold: int = 2
) -> dict[str, bytes]:
    return {
        VERSION: abi_encode(["string"], [version]),
        GET_OWNERS: abi_encode(["address[]"], [owners or OWNERS]),
        GET_THRESHOLD: abi_encode(["uint256"], [threshold]),
    }


class FakeChain:
    """In-memory chain answering the JSON-RPC reads the verifier uses."""

    def __init__(self, chain_id: int = CHAIN_ID) -> None:
        self.chain_id = chain_id
        self.accounts: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, list[Any]]] = []
        self.fail = False

    def add_safe(self, address: str, *, master_copy: str = SINGLETON_L1, **answers: Any) -> None:
        self.accounts[address.lower()] = {
            "code": "0x6080",
            "slot0": master_copy,
            "answers": safe_answers(**answers),
        }

    def add_contract(self, address: str, *, slot0: str = "0x" + "00" * 20) -> None:
        self.accounts[address.lower()] = {"code": "0x6080", "slot0": slot0, "answers": {}}

    def handle(self, method: str, params: list[Any]) -> Any:
        self.calls.append((method, params))
        if self.fail:
            raise RuntimeError("provider down")
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_blockNumber":
            return "0x10"
        account = self.accounts.get(
            str(params[0] if method != "eth_call" else params[0]["to"]).lower()
        )
        if method == "eth_getCode":
            return account["code"] if account else "0x"
        if method == "eth_getStorageAt":
            return "0x" + (account["slot0"][2:] if account else "00" * 20).rjust(64, "0")
        if method == "eth_call":
            if account is None:
                return "0x"
            answer = account["answers"].get(params[0]["data"])
            if answer is None:
                raise LookupError("execution reverted")
            return "0x" + answer.hex()
        raise NotImplementedError(method)


@pytest.fixture
def chain() -> Iterator[tuple[FakeChain, str]]:
    fake = FakeChain()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            try:
                body: dict[str, Any] = {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": fake.handle(request["method"], request["params"]),
                }
            except LookupError:
                body = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": 3, "message": "execution reverted"},
                }
            except RuntimeError:
                body = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": -32005, "message": "rate limited"},
                }
            payload = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield fake, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def configuration(
    rpc_urls: tuple[str, ...],
    *,
    chain_id: int = CHAIN_ID,
    singletons: tuple[tuple[str, str, str], ...] = (
        ("SAFE_SINGLETON_L1", SINGLETON_L1, "1.4.1"),
        ("SAFE_SINGLETON_L2", SINGLETON_L2, "1.4.1"),
    ),
) -> PlatformConfiguration:
    deployments = [
        DeploymentConfig(
            name="TREASURY_MODULE_IMPLEMENTATION",
            address="0x" + "11" * 20,
            code_hash="0x" + "22" * 32,
            version="1.0.0",
        ),
        *(
            DeploymentConfig(
                name=name, address=address, code_hash="0x" + "33" * 32, version=version
            )
            for name, address, version in singletons
        ),
    ]
    return PlatformConfiguration(
        chains=(
            ChainConfig(
                chain_id=chain_id,
                name="Local",
                is_testnet=True,
                confirmations=0,
                explorer_url="https://explorer.example.test",  # type: ignore[arg-type]
                rpc_urls=rpc_urls,
            ),
        ),
        manifests=(DeploymentManifest(chain_id=chain_id, deployments=tuple(deployments)),),
    )


def verify(url: str | tuple[str, ...], addresses: list[str], **kwargs: Any) -> list[Any]:
    urls = (url,) if isinstance(url, str) else url
    return asyncio.run(
        RpcSafeVerifier(configuration(urls, **kwargs), {}).verify(CHAIN_ID, addresses)
    )


SAFES = ["0x" + f"{i:040x}" for i in (0x501, 0x502, 0x503)]


def _urls(url: str) -> tuple[str, str]:
    return (url, url.replace("127.0.0.1", "localhost"))


def test_three_valid_safes_are_verified_with_owners_and_threshold(
    chain: tuple[FakeChain, str],
) -> None:
    fake, url = chain
    fake.add_safe(SAFES[0])
    fake.add_safe(SAFES[1], master_copy=SINGLETON_L2)  # L2 singleton is allowlisted too
    fake.add_safe(SAFES[2], owners=OWNERS[:2], threshold=1)

    results = verify(_urls(url), SAFES)

    assert [r.address for r in results] == [to_checksum_address(a) for a in SAFES]
    assert results[0].version == "1.4.1"
    assert results[0].owners == tuple(to_checksum_address(o) for o in OWNERS)
    assert (results[0].threshold, results[2].threshold) == (2, 1)
    assert results[1].master_copy == to_checksum_address(SINGLETON_L2)
    # Every read is pinned to one block.
    blocks = {p[-1] for m, p in fake.calls if m in {"eth_getCode", "eth_getStorageAt", "eth_call"}}
    assert blocks == {"0x10"}


def test_eoa_is_rejected_as_not_a_safe(chain: tuple[FakeChain, str]) -> None:
    fake, url = chain
    fake.add_safe(SAFES[0])
    with pytest.raises(SafeVerificationError) as raised:
        verify(_urls(url), [SAFES[0], EOA])
    assert raised.value.code == "NOT_A_SAFE"
    assert raised.value.address == to_checksum_address(EOA)


def test_contracts_that_are_not_safe_proxies_are_rejected(
    chain: tuple[FakeChain, str],
) -> None:
    fake, url = chain
    fake.add_contract(SAFES[0])  # no masterCopy
    fake.add_contract(SAFES[1], slot0=SINGLETON_L1)  # fakes the slot but has no Safe ABI
    fake.add_safe(SAFES[2], master_copy="0x" + "00" * 20)  # the singleton itself, not a proxy
    for address in SAFES:
        with pytest.raises(SafeVerificationError) as raised:
            verify(_urls(url), [address])
        assert raised.value.code == "NOT_A_SAFE", address


def test_garbage_abi_answers_are_not_a_safe_rather_than_a_crash(
    chain: tuple[FakeChain, str],
) -> None:
    fake, url = chain
    fake.add_contract(SAFES[0], slot0=SINGLETON_L1)
    fake.accounts[SAFES[0].lower()]["answers"] = {VERSION: b"\x01"}  # too short to decode
    with pytest.raises(SafeVerificationError) as raised:
        verify(_urls(url), [SAFES[0]])
    assert raised.value.code == "NOT_A_SAFE"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"[]", _ProviderError),
        (b'{"error": "rate limited"}', _ProviderError),
        (b'{"error": {"code": -32000, "message": "revert quota exceeded"}}', _ProviderError),
        (b'{"error": {"code": 3, "message": "boom"}}', _Reverted),
        (b'{"error": {"code": -32000, "message": "execution reverted"}}', _Reverted),
    ],
)
def test_malformed_or_non_revert_errors_fail_over(
    monkeypatch: pytest.MonkeyPatch, body: bytes, expected: type[Exception]
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(body))
    with pytest.raises(expected):
        safe_rpc("http://rpc.test", "eth_call", [])


def test_other_safe_versions_are_rejected(chain: tuple[FakeChain, str]) -> None:
    fake, url = chain
    fake.add_safe(SAFES[0], version="1.3.0", master_copy=SINGLETON_L1)
    fake.add_safe(SAFES[1], version="1.4.1", master_copy=UNLISTED_SINGLETON)
    fake.add_safe(SAFES[2], version="1.3.0+L2", master_copy=UNLISTED_SINGLETON)
    for address in SAFES:
        with pytest.raises(SafeVerificationError) as raised:
            verify(_urls(url), [address])
        assert raised.value.code == "SAFE_VERSION_UNSUPPORTED", address


def test_missing_singleton_allowlist_fails_closed(chain: tuple[FakeChain, str]) -> None:
    fake, url = chain
    fake.add_safe(SAFES[0])
    with pytest.raises(SafeVerificationError) as raised:
        verify(_urls(url), [SAFES[0]], singletons=(("SAFE_SINGLETON_L1", SINGLETON_L1, "1.3.0"),))
    assert raised.value.code == "SAFE_VERSION_UNSUPPORTED"


def test_unconfigured_chain_is_wrong_chain(chain: tuple[FakeChain, str]) -> None:
    _, url = chain
    with pytest.raises(SafeVerificationError) as raised:
        asyncio.run(RpcSafeVerifier(configuration(_urls(url)), {}).verify(1, SAFES))
    assert raised.value.code == "WRONG_CHAIN"


def test_failover_skips_a_failing_provider_and_never_trusts_a_wrong_chain(
    chain: tuple[FakeChain, str],
) -> None:
    fake, url = chain
    fake.add_safe(SAFES[0])
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{probe.getsockname()[1]}"
    assert [r.address for r in verify((dead, url), [SAFES[0]])] == [to_checksum_address(SAFES[0])]

    fake.chain_id = 1  # the provider serves another chain than configured
    with pytest.raises(RpcUnavailable):
        verify(_urls(url), [SAFES[0]])

    fake.chain_id = CHAIN_ID
    fake.fail = True
    with pytest.raises(RpcUnavailable):
        verify(_urls(url), [SAFES[0]])


def test_singleton_allowlist_comes_from_the_manifest() -> None:
    config = configuration(("http://a.test", "http://b.test"))
    assert safe_singletons(config, CHAIN_ID) == {SINGLETON_L1, SINGLETON_L2}
    assert safe_singletons(config, 1) == frozenset()


# --- Anvil integration: real JSON-RPC node, contract stubs implementing the Safe read ABI ---


def _dispatcher(answers: dict[str, bytes]) -> str:
    """Runtime bytecode returning a fixed answer per selector and reverting otherwise."""

    entries = [(bytes.fromhex(selector[2:]), data) for selector, data in answers.items()]
    head_size = 6 + 11 * len(entries) + 4  # selector load, one test per entry, REVERT
    block_size = 16
    data_offset = head_size + block_size * len(entries)
    head = bytearray(bytes.fromhex("60003560e01c"))  # PUSH1 0 CALLDATALOAD PUSH1 0xe0 SHR
    blocks = bytearray()
    data = bytearray()
    for index, (selector, answer) in enumerate(entries):
        target = head_size + block_size * index
        # DUP1 PUSH4 <selector> EQ PUSH2 <target> JUMPI
        head += b"\x80\x63" + selector + b"\x14\x61" + target.to_bytes(2, "big") + b"\x57"
        size = len(answer).to_bytes(2, "big")
        # JUMPDEST; CODECOPY(0, offset, size); RETURN(0, size)
        blocks += b"\x5b\x61" + size + b"\x61" + (data_offset + len(data)).to_bytes(2, "big")
        blocks += b"\x60\x00\x39\x61" + size + b"\x60\x00\xf3"
        data += answer
    head += bytes.fromhex("600080fd")  # PUSH1 0 DUP1 REVERT
    assert len(head) == head_size and len(blocks) == block_size * len(entries)
    return "0x" + (bytes(head) + bytes(blocks) + bytes(data)).hex()


def _rpc(url: str, method: str, params: list[object]) -> object:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.load(response)
    assert "error" not in payload, payload
    return payload["result"]


@pytest.fixture(scope="module")
def anvil_url() -> Iterator[str]:
    if "TP_TEST_ANVIL_URL" in os.environ:
        yield os.environ["TP_TEST_ANVIL_URL"]
        return
    if shutil.which("anvil") is None:
        pytest.skip("anvil is required for the Safe verification integration test")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    process = subprocess.Popen(
        ["anvil", "--silent", "--port", str(port), "--chain-id", str(CHAIN_ID)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                _rpc(url, "eth_chainId", [])
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("anvil did not start")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=5)


def _install_safe(
    url: str, address: str, *, master_copy: str = SINGLETON_L1, **answers: Any
) -> None:
    _rpc(url, "anvil_setCode", [address, _dispatcher(safe_answers(**answers))])
    _rpc(url, "anvil_setStorageAt", [address, "0x0", "0x" + master_copy[2:].rjust(64, "0")])


def test_anvil_safe_verification_end_to_end(anvil_url: str) -> None:
    urls = _urls(anvil_url)
    for address in SAFES[:2]:
        _install_safe(anvil_url, address)
    _install_safe(anvil_url, SAFES[2], owners=OWNERS[:2], threshold=1)

    verified = verify(urls, SAFES)
    assert [(s.threshold, len(s.owners)) for s in verified] == [(2, 3), (2, 3), (1, 2)]

    with pytest.raises(SafeVerificationError) as eoa:
        verify(urls, [SAFES[0], EOA])
    assert eoa.value.code == "NOT_A_SAFE"

    old = "0x" + "b1" * 20
    _install_safe(anvil_url, old, version="1.3.0")
    with pytest.raises(SafeVerificationError) as old_version:
        verify(urls, [old])
    assert old_version.value.code == "SAFE_VERSION_UNSUPPORTED"

    other_singleton = "0x" + "b2" * 20
    _install_safe(anvil_url, other_singleton, master_copy=UNLISTED_SINGLETON)
    with pytest.raises(SafeVerificationError) as other:
        verify(urls, [other_singleton])
    assert other.value.code == "SAFE_VERSION_UNSUPPORTED"
