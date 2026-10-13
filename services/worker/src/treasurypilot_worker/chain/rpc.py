"""JSON-RPC access to the chain through ordered providers with failover (M06 §6)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol
from urllib.parse import urlsplit

import aiohttp
import asyncpg  # type: ignore[import-untyped]
from eth_abi import decode, encode
from eth_abi.exceptions import DecodingError
from web3 import AsyncHTTPProvider, Web3

TIMEOUT_SECONDS: Final = 4.0
RETRIES_PER_PROVIDER: Final = 2
RETRY_BACKOFF_SECONDS: Final = 0.25
# Health is telemetry: a slow sink must not stall chain reads for longer than this.
HEALTH_TIMEOUT_SECONDS: Final = 0.5
# What a provider's transport can raise; anything else is a bug and propagates.
TRANSPORT_ERRORS: Final = (TimeoutError, OSError, aiohttp.ClientError, json.JSONDecodeError)
SAFE_SENTINEL: Final = "0x" + "00" * 19 + "01"
SAFE_MODULES_PAGE_SIZE: Final = 50
SAFE_MODULES_MAX_PAGES: Final = 20
# keccak256("guard_manager.guard.address") and keccak256("fallback_manager.handler.address")
SAFE_GUARD_SLOT: Final = "0x4a204f620c8c5ccdca3fd54d003badd85ba500436a431f0cbda4f558c93c34c8"
SAFE_FALLBACK_HANDLER_SLOT: Final = (
    "0x6c9a6c4a39284e37ed1cf53d337577d14212a4870fb976a4366c693b939918d5"
)

# Stored RPC URLs reference keys as ${ENV_VAR} placeholders (TRS-002).
_URL_PLACEHOLDER = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")

logger = logging.getLogger(__name__)


class RpcError(Exception):
    """A chain read failed. Callers never receive a default value instead."""


class RpcUnavailable(RpcError):
    """No provider answered within its retries."""


class RpcResponseError(RpcError):
    """Every provider answered with a JSON-RPC error (e.g. the call reverts)."""

    def __init__(self, code: int | None, message: str) -> None:
        super().__init__(f"JSON-RPC error {code}: {message}")
        self.code = code


class Transport(Protocol):
    """The part of a web3.py provider the client uses."""

    def make_request(self, method: Any, params: Any) -> Awaitable[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class RpcProvider:
    # A display name only; the URL can embed an API key and must never be logged or stored.
    name: str
    transport: Transport


@dataclass(frozen=True)
class RpcHealthSample:
    provider: str
    ok: bool
    latency_ms: int
    head: int | None
    last_error: str | None


class CrossCheck(StrEnum):
    MATCH = "Match"
    MISMATCH = "Mismatch"
    UNAVAILABLE = "Unavailable"


@dataclass(frozen=True)
class FeeHistory:
    """``eth_feeHistory`` in wei, oldest block first."""

    oldest_block: int
    base_fee_per_gas: tuple[int, ...]
    gas_used_ratio: tuple[float, ...]
    reward: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class SafeConfig:
    """A Safe's configuration read at one block; addresses are lowercase hex."""

    block_number: int
    block_hash: str
    owners: tuple[str, ...]
    threshold: int
    modules: tuple[str, ...]
    guard: str | None
    fallback_handler: str | None
    nonce: int


HealthSink = Callable[[RpcHealthSample], Awaitable[None]]


class RpcClient:
    def __init__(
        self, providers: Sequence[RpcProvider], *, on_health: HealthSink | None = None
    ) -> None:
        if not providers:
            raise ValueError("at least one RPC provider is required")
        self.providers = tuple(providers)
        self._on_health = on_health

    async def call(self, method: str, params: Sequence[Any]) -> Any:
        """Ask each provider in order (with retries) and return the first answer."""

        failures: list[RpcError] = []
        for provider in self.providers:
            try:
                return await self._call_provider(provider, method, params)
            except RpcError as failure:
                # A JSON-RPC error can be a lagging or rate-limited node, so fail over too.
                failures.append(failure)
        if all(isinstance(failure, RpcResponseError) for failure in failures):
            raise failures[-1]
        raise RpcUnavailable(f"{method}: all {len(self.providers)} providers failed")

    async def fee_history(
        self, blocks: int = 20, percentiles: Sequence[int] = (25, 50, 75)
    ) -> FeeHistory:
        raw = await self.call("eth_feeHistory", [hex(blocks), "latest", list(percentiles)])
        return FeeHistory(
            oldest_block=int(raw["oldestBlock"], 16),
            base_fee_per_gas=tuple(int(fee, 16) for fee in raw["baseFeePerGas"]),
            gas_used_ratio=tuple(raw["gasUsedRatio"]),
            reward=tuple(tuple(int(tip, 16) for tip in row) for row in raw.get("reward") or ()),
        )

    async def safe_config(self, safe: str) -> SafeConfig:
        """Read owners, threshold, modules, guard, fallback handler and nonce at the head block."""

        head = await self.call("eth_getBlockByNumber", ["latest", False])
        # Pin by hash (EIP-1898): reads can fail over to another provider or cross a reorg.
        block = {"blockHash": head["hash"]}
        (owners,) = await self._safe_view(safe, block, "getOwners()", ["address[]"])
        (threshold,) = await self._safe_view(safe, block, "getThreshold()", ["uint256"])
        (nonce,) = await self._safe_view(safe, block, "nonce()", ["uint256"])
        modules: list[str] = []
        cursor = SAFE_SENTINEL
        for _ in range(SAFE_MODULES_MAX_PAGES):
            page, cursor = await self._safe_view(
                safe,
                block,
                "getModulesPaginated(address,uint256)",
                ["address[]", "address"],
                ["address", "uint256"],
                [cursor, SAFE_MODULES_PAGE_SIZE],
            )
            modules += page
            if not page or cursor.lower() == SAFE_SENTINEL:
                break
        else:
            raise RpcError(f"{safe}: getModulesPaginated did not end after {len(modules)} modules")
        return SafeConfig(
            block_number=int(head["number"], 16),
            block_hash=str(head["hash"]).lower(),
            owners=tuple(owner.lower() for owner in owners),
            threshold=threshold,
            modules=tuple(module.lower() for module in modules),
            guard=await self._storage_address(safe, SAFE_GUARD_SLOT, block),
            fallback_handler=await self._storage_address(safe, SAFE_FALLBACK_HANDLER_SLOT, block),
            nonce=nonce,
        )

    async def _safe_view(
        self,
        safe: str,
        block: Mapping[str, str],
        signature: str,
        output_types: list[str],
        input_types: Sequence[str] = (),
        args: Sequence[Any] = (),
    ) -> tuple[Any, ...]:
        data = Web3.keccak(text=signature)[:4] + encode(list(input_types), list(args))
        raw = await self.call("eth_call", [{"to": safe, "data": "0x" + data.hex()}, block])
        try:
            return decode(output_types, bytes.fromhex(str(raw).removeprefix("0x")))
        except (DecodingError, ValueError):
            raise RpcError(f"{safe} is not a Safe: {signature} returned {raw!r}") from None

    async def _storage_address(
        self, contract: str, slot: str, block: Mapping[str, str]
    ) -> str | None:
        word = await self.call("eth_getStorageAt", [contract, slot, block])
        address = "0x" + str(word).removeprefix("0x").rjust(64, "0")[-40:].lower()
        return None if int(address, 16) == 0 else address

    async def crosscheck_receipt(self, tx_hash: str) -> CrossCheck:
        """Compare the primary's receipt with the secondary's receipt and canonical block (M06-D1).

        Each side is read from its own provider only: failing over would let one provider
        confirm itself, so an unreachable side is ``UNAVAILABLE``.
        """

        if len(self.providers) < 2:
            return CrossCheck.UNAVAILABLE
        primary, secondary = self.providers[:2]
        try:
            primary_receipt = await self._call_provider(
                primary, "eth_getTransactionReceipt", [tx_hash]
            )
            receipt = await self._call_provider(secondary, "eth_getTransactionReceipt", [tx_hash])
            block = (
                await self._call_provider(
                    secondary, "eth_getBlockByNumber", [receipt["blockNumber"], False]
                )
                if receipt
                else None
            )
        except RpcError:
            return CrossCheck.UNAVAILABLE
        if not primary_receipt or not receipt or not block:
            # A side that has not seen the transaction yet is lagging, not disagreeing.
            return CrossCheck.UNAVAILABLE
        agree = _hex_equal(block.get("hash"), primary_receipt.get("blockHash")) and all(
            _hex_equal(receipt.get(field), primary_receipt.get(field))
            for field in ("blockHash", "blockNumber", "status")
        )
        return CrossCheck.MATCH if agree else CrossCheck.MISMATCH

    async def _call_provider(
        self, provider: RpcProvider, method: str, params: Sequence[Any]
    ) -> Any:
        error = "unknown"
        for attempt in range(1 + RETRIES_PER_PROVIDER):
            if attempt:
                # Back off so a rate-limited (HTTP 429) provider is not hit again at once.
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1))
            started = time.monotonic()
            try:
                async with asyncio.timeout(TIMEOUT_SECONDS):
                    response = await provider.transport.make_request(method, list(params))
            except TRANSPORT_ERRORS as exc:
                # The type only: transport messages can contain the URL and its API key.
                error = type(exc).__name__
                await self._record(provider, started, ok=False, error=error)
                continue
            if "error" in response:
                failure = response["error"] or {}
                code = failure.get("code")
                await self._record(provider, started, ok=False, error=f"JSON-RPC {code}")
                raise RpcResponseError(code, str(failure.get("message")))
            await self._record(provider, started, ok=True, head=_head(method, response))
            return response.get("result")
        raise RpcUnavailable(f"{provider.name}: {method} failed ({error})")

    async def _record(
        self,
        provider: RpcProvider,
        started: float,
        *,
        ok: bool,
        head: int | None = None,
        error: str | None = None,
    ) -> None:
        if self._on_health is None:
            return
        latency_ms = round((time.monotonic() - started) * 1000)
        try:
            async with asyncio.timeout(HEALTH_TIMEOUT_SECONDS):
                await self._on_health(RpcHealthSample(provider.name, ok, latency_ms, head, error))
        except Exception:
            # Health is telemetry: losing a sample must not fail a chain read.
            logger.warning("rpc health sample dropped", exc_info=True)


def rpc_health_sink(pool: asyncpg.Pool) -> HealthSink:
    """Persist health samples to ``rpc_health``."""

    async def record(sample: RpcHealthSample) -> None:
        await pool.execute(
            "INSERT INTO rpc_health (provider, ok, latency_ms, head, last_error)"
            " VALUES ($1, $2, $3, $4, $5)",
            sample.provider,
            sample.ok,
            sample.latency_ms,
            sample.head,
            sample.last_error,
        )

    return record


def build_rpc_client(
    rpc_urls: Sequence[str],
    *,
    environ: Mapping[str, str] = os.environ,
    on_health: HealthSink | None = None,
) -> RpcClient:
    """Wrap a chain's ``rpc_urls`` (primary first) in web3.py providers."""

    def expand(match: re.Match[str]) -> str:
        if match.group(1) not in environ:
            raise ValueError(f"RPC URL references unset variable {match.group(1)}")
        return environ[match.group(1)]

    providers = [
        RpcProvider(
            urlsplit(template).hostname or f"provider-{index}",
            # Retries and failover are ours; web3's own retry loop would multiply them.
            AsyncHTTPProvider(
                _URL_PLACEHOLDER.sub(expand, template), exception_retry_configuration=None
            ),
        )
        for index, template in enumerate(rpc_urls)
    ]
    return RpcClient(providers, on_health=on_health)


def _hex_equal(left: Any, right: Any) -> bool:
    return left is not None and str(left).lower() == str(right).lower()


def _head(method: str, response: Mapping[str, Any]) -> int | None:
    result = response.get("result")
    return int(result, 16) if method == "eth_blockNumber" and isinstance(result, str) else None
