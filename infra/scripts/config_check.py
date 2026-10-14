"""Verify configured chain, asset and Aave reserve against a live RPC."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import cast

from cast_helpers import read_scalar, run_cast

_ADDRESS_PATTERN = re.compile(r"0x[0-9a-fA-F]{40}")
_RESERVE_SIGNATURE = (
    "getReserveData(address)((uint256,uint128,uint128,uint128,uint128,uint128,uint40,"
    "uint16,address,address,address,address,uint128,uint128,uint128))"
)
# Pinned by test_reserve_signature_matches_recorded_sepolia_output; Pool has no getReserveAToken.
_RESERVE_FIELDS = 15
_RESERVE_A_TOKEN_INDEX = 8


def _address(value: object, field: str) -> str:
    if not isinstance(value, str) or _ADDRESS_PATTERN.fullmatch(value) is None:
        raise ValueError(f"Manifest {field} must be a 20-byte address")
    if int(value[2:], 16) == 0:
        raise ValueError(f"Manifest {field} must not be the zero address")
    return value.lower()


def check_configuration(manifest: dict[str, object], rpc_url: str) -> None:
    """Fail closed unless current RPC state agrees with the reviewed manifest."""
    if not rpc_url.strip():
        raise ValueError("Set SEPOLIA_RPC_URL (or ETH_RPC_URL) to run config-check")
    chain_id = manifest.get("chainId")
    if type(chain_id) is not int or chain_id <= 0:
        raise ValueError("Manifest chainId must be a positive integer")
    asset = _address(manifest.get("asset"), "asset")
    pool = _address(manifest.get("aavePool"), "aavePool")
    a_token = _address(manifest.get("aToken"), "aToken")
    decimals = manifest.get("assetDecimals")
    if type(decimals) is not int or not 0 <= decimals <= 255:
        raise ValueError("Manifest assetDecimals must be a uint8")
    if int(run_cast(["chain-id", "--rpc-url", rpc_url])) != chain_id:
        raise ValueError("RPC chain id does not match the deployment manifest")

    for name, address in (("asset", asset), ("aavePool", pool), ("aToken", a_token)):
        code = run_cast(["code", address, "--rpc-url", rpc_url])
        if code == "0x" or re.fullmatch(r"0x(?:[0-9a-fA-F]{2})+", code) is None:
            raise ValueError(f"Manifest {name} has no on-chain runtime code")

    observed_decimals = read_scalar(asset, "decimals()(uint8)", [], rpc_url)
    try:
        observed = int(str(observed_decimals).split()[0])  # cast may print "6 [6e0]"
    except (IndexError, ValueError):
        raise ValueError(f"Unparseable on-chain decimals: {observed_decimals!r}") from None
    if observed != decimals:
        raise ValueError(
            f"On-chain token decimals ({observed}) differ from manifest assetDecimals ({decimals})"
        )

    reserve = read_scalar(pool, _RESERVE_SIGNATURE, [asset], rpc_url)
    if not isinstance(reserve, list) or len(reserve) != _RESERVE_FIELDS:
        raise ValueError("Aave Pool returned an invalid reserve record for the configured asset")
    if str(reserve[_RESERVE_A_TOKEN_INDEX]).lower() != a_token:
        raise ValueError("Aave Pool reserve-to-aToken mapping differs from manifest aToken")

    underlying = read_scalar(a_token, "UNDERLYING_ASSET_ADDRESS()(address)", [], rpc_url)
    if str(underlying).lower() != asset:
        raise ValueError("Manifest aToken does not report the configured asset as its underlying")
    token_pool = read_scalar(a_token, "POOL()(address)", [], rpc_url)
    if str(token_pool).lower() != pool:
        raise ValueError("Manifest aToken does not report the configured Aave Pool")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("deployments/11155111.json"))
    parser.add_argument(
        "--rpc-url", default=os.environ.get("SEPOLIA_RPC_URL") or os.environ.get("ETH_RPC_URL")
    )
    args = parser.parse_args()
    try:
        raw = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Manifest root must be a JSON object")
        check_configuration(cast(dict[str, object], raw), args.rpc_url or "")
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        print(f"config-check failed: {exc}", file=sys.stderr)
        return 1
    print(f"config-check passed: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
