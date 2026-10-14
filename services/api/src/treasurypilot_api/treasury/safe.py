"""Safe smart-account verification (M02 §8, M02-D2, FR-103).

Enforcement is only real when every wallet in scope supports the module control path,
so an address is accepted only if it is a Safe v1.4.1 proxy: non-empty code, a
``masterCopy`` (storage slot 0) in the allowlisted v1.4.1 singletons, and
``VERSION() == "1.4.1"``. EOAs and arbitrary contracts are ``NOT_A_SAFE``.

shortcut: detection uses the Safe ABI through plain JSON-RPC instead of safe-eth-py. The
library pins web3 8 and eth-account 0.13, which cannot resolve in this workspace (siwe needs
eth-account <0.14, treasurypilot-core needs >=0.14, the worker needs web3 7). The checks
here are the same ones the library performs and need no extra dependency.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from eth_abi import decode as abi_decode
from eth_utils import keccak, to_checksum_address

from treasurypilot_api.treasury.config import (
    ChainConfig,
    PlatformConfiguration,
    PlatformConfigurationError,
    resolve_rpc_url,
)

SUPPORTED_SAFE_VERSION = "1.4.1"
# Deployment names in the chain manifest (L1 and L2 singletons of Safe v1.4.1).
SAFE_SINGLETON_DEPLOYMENTS = frozenset({"SAFE_SINGLETON_L1", "SAFE_SINGLETON_L2"})
TIMEOUT_SECONDS = 4.0

_MASTER_COPY_SLOT = "0x" + "00" * 32
_VERSION = "0x" + keccak(text="VERSION()")[:4].hex()
_GET_OWNERS = "0x" + keccak(text="getOwners()")[:4].hex()
_GET_THRESHOLD = "0x" + keccak(text="getThreshold()")[:4].hex()


class SafeVerificationError(Exception):
    """The address is not an acceptable Safe; ``code`` is the API error code."""

    def __init__(self, code: str, detail: str, *, address: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.address = address


class RpcUnavailable(Exception):
    """No configured RPC provider could answer the verification reads."""


class _ProviderError(Exception):
    """A provider failed (transport, rate limit, wrong chain); the next one is tried."""


class _Reverted(Exception):
    """``eth_call`` reverted or targeted an address without the function."""


@dataclass(frozen=True, slots=True)
class SafeInfo:
    address: str  # EIP-55 checksum
    master_copy: str
    version: str
    owners: tuple[str, ...]  # EIP-55 checksum
    threshold: int
    block_number: int


class SafeVerifier(Protocol):
    async def verify(self, chain_id: int, addresses: Sequence[str]) -> list[SafeInfo]:
        """Verify every address on the chain; raises ``SafeVerificationError`` or
        ``RpcUnavailable``. Results are in input order."""
        ...


def safe_singletons(configuration: PlatformConfiguration, chain_id: int) -> frozenset[str]:
    """Allowlisted v1.4.1 Safe singletons (lowercase 0x addresses) for the chain."""

    return frozenset(
        deployment.address
        for manifest in configuration.manifests
        if manifest.chain_id == chain_id
        for deployment in manifest.deployments
        if deployment.name in SAFE_SINGLETON_DEPLOYMENTS
        and deployment.version == SUPPORTED_SAFE_VERSION
    )


def _rpc(url: str, method: str, params: list[object]) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload: dict[str, Any] = json.load(response)
    except (OSError, ValueError):
        # The URL can embed an API key, so the transport error is not echoed.
        raise _ProviderError(method) from None
    error = payload.get("error")
    if error is not None:
        message = str(error.get("message", "")).lower()
        if method == "eth_call" and (error.get("code") == 3 or "revert" in message):
            raise _Reverted
        raise _ProviderError(method)
    if "result" not in payload:
        raise _ProviderError(method)
    return payload["result"]


def _call(url: str, address: str, data: str, block: str) -> bytes:
    result = _rpc(url, "eth_call", [{"to": address, "data": data}, block])
    raw = bytes.fromhex(str(result).removeprefix("0x"))
    if not raw:  # no code at the address, or no such function
        raise _Reverted
    return raw


def _verify_address(
    url: str, address: str, block: str, block_number: int, singletons: frozenset[str]
) -> SafeInfo:
    checksum = to_checksum_address(address)
    not_a_safe = SafeVerificationError(
        "NOT_A_SAFE", f"{checksum} is not a Safe smart account.", address=checksum
    )
    if not bytes.fromhex(str(_rpc(url, "eth_getCode", [address, block])).removeprefix("0x")):
        raise not_a_safe  # EOA or empty address
    slot = bytes.fromhex(
        str(_rpc(url, "eth_getStorageAt", [address, _MASTER_COPY_SLOT, block])).removeprefix("0x")
    ).rjust(32, b"\x00")
    master_copy = "0x" + slot[-20:].hex()
    if not any(slot[-20:]):
        raise not_a_safe  # no masterCopy: not a Safe proxy
    try:
        version = abi_decode(["string"], _call(url, address, _VERSION, block))[0]
        owners = abi_decode(["address[]"], _call(url, address, _GET_OWNERS, block))[0]
        threshold = abi_decode(["uint256"], _call(url, address, _GET_THRESHOLD, block))[0]
    except (_Reverted, ValueError, OverflowError):
        raise not_a_safe from None
    if not owners or not 1 <= threshold <= len(owners):
        raise not_a_safe
    if version != SUPPORTED_SAFE_VERSION or master_copy not in singletons:
        raise SafeVerificationError(
            "SAFE_VERSION_UNSUPPORTED",
            f"{checksum} is not a Safe v{SUPPORTED_SAFE_VERSION} proxy of an allowlisted "
            f"singleton (reported version {version!r}).",
            address=checksum,
        )
    return SafeInfo(
        address=checksum,
        master_copy=to_checksum_address(master_copy),
        version=version,
        owners=tuple(to_checksum_address(owner) for owner in owners),
        threshold=int(threshold),
        block_number=block_number,
    )


def _verify_all(
    url: str, chain_id: int, addresses: Sequence[str], singletons: frozenset[str]
) -> list[SafeInfo]:
    if int(str(_rpc(url, "eth_chainId", [])), 16) != chain_id:
        raise _ProviderError("eth_chainId")  # misconfigured provider, not the user's fault
    block_number = int(str(_rpc(url, "eth_blockNumber", [])), 16)
    # One block for every read so a Safe reconfigured mid-request cannot be seen half-way.
    block = hex(block_number)
    return [_verify_address(url, a, block, block_number, singletons) for a in addresses]


class RpcSafeVerifier:
    """Verifies Safes over the chain's configured HTTP(S) RPC providers, in failover order."""

    def __init__(
        self,
        configuration: PlatformConfiguration,
        environ: Mapping[str, str] = os.environ,
    ) -> None:
        self._configuration = configuration
        self._environ = environ

    def _chain(self, chain_id: int) -> ChainConfig:
        for chain in self._configuration.chains:
            if chain.chain_id == chain_id and chain.enabled:
                return chain
        raise SafeVerificationError("WRONG_CHAIN", f"Chain {chain_id} is not supported.")

    async def verify(self, chain_id: int, addresses: Sequence[str]) -> list[SafeInfo]:
        chain = self._chain(chain_id)
        singletons = safe_singletons(self._configuration, chain_id)
        for template in chain.rpc_urls:
            if not template.startswith(("http://", "https://")):
                continue
            try:
                url = resolve_rpc_url(template, self._environ)
                return await asyncio.to_thread(_verify_all, url, chain_id, addresses, singletons)
            except (_ProviderError, PlatformConfigurationError, OSError, ValueError):
                continue
        raise RpcUnavailable(f"no RPC provider answered for chain {chain_id}")

    async def call(self, chain_id: int, method: str, params: list[object]) -> Any:
        """One JSON-RPC read with the same provider failover as ``verify``."""
        chain = self._chain(chain_id)
        for template in chain.rpc_urls:
            if not template.startswith(("http://", "https://")):
                continue
            try:
                url = resolve_rpc_url(template, self._environ)
                return await asyncio.to_thread(_rpc, url, method, params)
            except (_ProviderError, _Reverted, PlatformConfigurationError, OSError, ValueError):
                continue
        raise RpcUnavailable(f"no RPC provider answered for chain {chain_id}")
