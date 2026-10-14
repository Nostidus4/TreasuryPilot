"""On-chain checks for platform configuration (M02 §8)."""

from __future__ import annotations

import asyncio
import json
import string
import urllib.request
from collections.abc import Mapping
from typing import Any

from treasurypilot_api.treasury.config import (
    AssetConfig,
    ChainConfig,
    PlatformConfigurationError,
    resolve_rpc_url,
)

DECIMALS_SELECTOR = "0x313ce567"  # bytes4(keccak256("decimals()"))
TIMEOUT_SECONDS = 4.0


def _eth_call(url: str, to: str, data: str) -> str:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [{"to": to, "data": data}, "latest"],
        }
    ).encode()
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        payload: dict[str, Any] = json.load(response)
    # A JSON-RPC error (revert, rate limit) has no "result": the KeyError fails over.
    return str(payload["result"])


async def verify_asset_decimals(
    chain: ChainConfig, asset: AssetConfig, environ: Mapping[str, str]
) -> None:
    """Refuse the asset unless its on-chain ``decimals()`` equals the configured value.

    Providers are tried in order; an asset that cannot be verified is refused too.
    """

    label = f"asset {asset.symbol} ({asset.address}) on chain {chain.chain_id}"
    for template in chain.rpc_urls:
        # shortcut: one-off startup read over HTTP only; ws(s) providers are skipped.
        if not template.startswith(("http://", "https://")):
            continue
        url = resolve_rpc_url(template, environ)
        try:
            result = await asyncio.to_thread(_eth_call, url, asset.address, DECIMALS_SELECTOR)
        except (OSError, ValueError, KeyError):
            # The URL can embed an API key, so the transport error is not echoed.
            continue
        raw = result.removeprefix("0x")
        if len(raw) != 64 or set(raw) - set(string.hexdigits) or int(raw, 16) > 255:
            raise PlatformConfigurationError(f"{label}: decimals() did not return a uint8")
        on_chain = int(raw, 16)
        if on_chain != asset.decimals:
            raise PlatformConfigurationError(
                f"{label}: on-chain decimals {on_chain} != configured {asset.decimals}"
            )
        return
    raise PlatformConfigurationError(f"{label}: no RPC provider returned decimals()")
