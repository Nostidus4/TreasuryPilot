from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from collections.abc import Iterator

import pytest

from treasurypilot_api.treasury.config import (
    AssetConfig,
    ChainConfig,
    PlatformConfigurationError,
)
from treasurypilot_api.treasury.onchain import verify_asset_decimals

TOKEN = "0x" + "ab" * 20
NO_CODE = "0x" + "cd" * 20
# Runtime code answering every call with uint256(6): PUSH1 6, MSTORE at 0, RETURN 32 bytes.
SIX_DECIMALS_CODE = "0x600660005260206000f3"


def _rpc(url: str, method: str, params: list[object]) -> object:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=2) as response:
        return json.load(response)["result"]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(scope="module")
def anvil_url() -> Iterator[str]:
    if "TP_TEST_ANVIL_URL" in os.environ:
        url = os.environ["TP_TEST_ANVIL_URL"]
        _rpc(url, "anvil_setCode", [TOKEN, SIX_DECIMALS_CODE])
        yield url
        return
    if shutil.which("anvil") is None:
        pytest.skip("anvil is required for the on-chain decimals integration test")
    port = _free_port()
    process = subprocess.Popen(
        ["anvil", "--silent", "--port", str(port)],
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
        _rpc(url, "anvil_setCode", [TOKEN, SIX_DECIMALS_CODE])
        yield url
    finally:
        process.terminate()
        process.wait(timeout=5)


def _chain(anvil_url: str) -> ChainConfig:
    # The unreachable provider comes first so every read exercises failover.
    return ChainConfig.model_validate(
        {
            "chainId": 31337,
            "name": "Anvil",
            "isTestnet": True,
            "confirmations": 0,
            "explorerUrl": "https://explorer.example",
            "rpcUrls": [f"http://127.0.0.1:{_free_port()}", anvil_url],
        }
    )


def _asset(address: str = TOKEN, decimals: int = 6) -> AssetConfig:
    return AssetConfig.model_validate(
        {
            "address": address,
            "symbol": "tUSDC",
            "decimals": decimals,
            "issuerLabel": "Test",
            "isTest": True,
        }
    )


def test_matching_on_chain_decimals_accepts_the_asset(anvil_url: str) -> None:
    asyncio.run(verify_asset_decimals(_chain(anvil_url), _asset(), {}))


def test_decimals_mismatch_refuses_the_asset(anvil_url: str) -> None:
    with pytest.raises(PlatformConfigurationError, match="decimals.*6.*18"):
        asyncio.run(verify_asset_decimals(_chain(anvil_url), _asset(decimals=18), {}))


def test_address_without_a_token_is_refused(anvil_url: str) -> None:
    with pytest.raises(PlatformConfigurationError, match="decimals"):
        asyncio.run(verify_asset_decimals(_chain(anvil_url), _asset(address=NO_CODE), {}))
