"""Publish a deployment or schema manifest only after checking real, mined RPC state."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, cast

from cast_helpers import read_scalar, run_cast, verify_schema

RUNTIME_CONTRACTS = (
    "implementation",
    "factory",
    "testToken",
    "module",
    "safeT",
    "safeO1",
    "safeO2",
    "safeSingleton",
    "safeProxyFactory",
    "multiSend",
    "asset",
    "eas",
    "easRegistry",
)
SEPOLIA_INFRASTRUCTURE = (
    "asset",
    "aavePool",
    "eas",
    "easRegistry",
    "safeSingleton",
    "safeProxyFactory",
    "multiSend",
)


def address(value: object, field: str, *, allow_zero: bool = False) -> str:
    if not isinstance(value, str) or re.fullmatch(r"0x[0-9a-fA-F]{40}", value) is None:
        raise ValueError(f"Invalid {field} address in prediction")
    if not allow_zero and int(value[2:], 16) == 0:
        raise ValueError(f"Missing {field} address in prediction")
    return value.lower()


def require_address_call(
    contract: str, signature: str, expected: str, rpc_url: str, block: str
) -> None:
    observed = read_scalar(contract, signature, [], rpc_url, block)
    if address(observed, signature, allow_zero=True) != expected.lower():
        raise ValueError(f"Mined contract does not match prediction: {signature}")


def verify_deployment(prediction: dict[str, object], rpc_url: str, block: str) -> None:
    if prediction.get("deploymentStatus") != "predicted":
        raise ValueError("Expected a prediction artifact, not a published deployment")
    pool = address(prediction.get("aavePool"), "aavePool", allow_zero=True)
    a_token = address(prediction.get("aToken"), "aToken", allow_zero=True)
    count = prediction.get("operationalWalletCount")
    expected_count = 1 if prediction.get("chainId") == 11155111 else 2
    if type(count) is not int or count != expected_count:
        raise ValueError("Operational wallet count does not match the chain's demo profile")
    safe_fields = ("safeT", "safeO1") if count == 1 else ("safeT", "safeO1", "safeO2")
    if count == 1 and int(address(prediction.get("safeO2"), "safeO2", allow_zero=True)[2:], 16):
        raise ValueError("The single-wallet Sepolia demo must not configure safeO2")
    runtimes = tuple(field for field in RUNTIME_CONTRACTS if field != "safeO2" or count == 2)
    contracts = (*runtimes, "aavePool", "aToken") if int(pool[2:], 16) else runtimes
    for field in contracts:
        deployed = address(prediction.get(field), field)
        expected_hash = prediction.get(field + "CodeHash")
        if (
            not isinstance(expected_hash, str)
            or re.fullmatch(r"0x[0-9a-fA-F]{64}", expected_hash) is None
        ):
            raise ValueError(f"Missing runtime hash for {field}")
        code = run_cast(["code", deployed, "--rpc-url", rpc_url, "--block", block])
        if code == "0x" or re.fullmatch(r"0x(?:[0-9a-fA-F]{2})+", code) is None:
            raise ValueError(f"No mined runtime code for {field}")
        if run_cast(["keccak", code]).lower() != expected_hash.lower():
            raise ValueError(f"Mined runtime hash differs for {field}")

    module = address(prediction.get("module"), "module")
    asset = address(prediction.get("asset"), "asset")
    treasury = address(prediction.get("safeT"), "safeT")
    owner = address(prediction.get("demoOwner"), "demoOwner")
    attester = address(prediction.get("easAttester"), "easAttester")
    if attester == owner:
        raise ValueError("The receipt attester must be a dedicated identity")
    require_address_call(module, "safeT()(address)", treasury, rpc_url, block)
    require_address_call(module, "asset()(address)", asset, rpc_url, block)
    require_address_call(module, "aavePool()(address)", pool, rpc_url, block)
    require_address_call(module, "aToken()(address)", a_token, rpc_url, block)
    require_address_call(
        address(prediction.get("factory"), "factory"),
        "implementation()(address)",
        address(prediction.get("implementation"), "implementation"),
        rpc_url,
        block,
    )
    if (
        prediction.get("assetDecimals") != 6
        or int(str(read_scalar(asset, "decimals()(uint8)", [], rpc_url, block))) != 6
    ):
        raise ValueError("Asset decimals do not match the six-decimal deployment configuration")
    if int(pool[2:], 16):
        require_address_call(a_token, "UNDERLYING_ASSET_ADDRESS()(address)", asset, rpc_url, block)
        require_address_call(a_token, "POOL()(address)", pool, rpc_url, block)
        reserve = read_scalar(
            pool,
            "getReserveData(address)((uint256,uint128,uint128,uint128,uint128,uint128,uint40,uint16,address,address,address,address,uint128,uint128,uint128))",
            [asset],
            rpc_url,
            block,
        )
        if (
            not isinstance(reserve, list)
            or len(reserve) != 15
            or str(reserve[8]).lower() != a_token
        ):
            raise ValueError(
                "The mined Aave reserve-to-aToken mapping does not match the prediction"
            )
    elif int(a_token[2:], 16):
        raise ValueError("Anvil without an Aave pool must not have an aToken")

    operations = read_scalar(module, "operationalList()(address[])", [], rpc_url, block)
    if not isinstance(operations, list) or [str(value).lower() for value in operations] != [
        address(prediction.get(field), field) for field in safe_fields if field != "safeT"
    ]:
        raise ValueError("Mined operational wallet list differs from the demo profile")
    for field in safe_fields:
        safe = address(prediction.get(field), field)
        require_address_call(
            safe,
            "masterCopy()(address)",
            address(prediction.get("safeSingleton"), "safeSingleton"),
            rpc_url,
            block,
        )
        enabled = read_scalar(safe, "isModuleEnabled(address)(bool)", [module], rpc_url, block)
        owners = read_scalar(safe, "getOwners()(address[])", [], rpc_url, block)
        threshold = read_scalar(safe, "getThreshold()(uint256)", [], rpc_url, block)
        if enabled is not True or int(str(threshold)) != 1 or not isinstance(owners, list):
            raise ValueError(f"Mined module enablement or threshold differs for {field}")
        if [str(value).lower() for value in owners] != [owner]:
            raise ValueError(f"Mined demo owner differs for {field}")
        if (
            field != "safeT"
            and read_scalar(module, "isOperational(address)(bool)", [safe], rpc_url, block)
            is not True
        ):
            raise ValueError(f"Mined module does not register {field} as operational")


def publish(
    prediction_path: Path, manifest_path: Path, rpc_url: str, *, schema_only: bool = False
) -> None:
    prediction = cast(dict[str, object], json.loads(prediction_path.read_text(encoding="utf-8")))
    chain_id = prediction.get("chainId")
    if type(chain_id) is not int or chain_id not in (31337, 11155111):
        raise ValueError("Only Anvil and Ethereum Sepolia predictions are supported")
    if int(run_cast(["chain-id", "--rpc-url", rpc_url])) != chain_id:
        raise ValueError("RPC chain does not match the prediction")
    block = str(int(run_cast(["block-number", "--rpc-url", rpc_url])))
    current: dict[str, object] = {}
    if manifest_path.exists():
        current = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
        if current.get("chainId") != chain_id:
            raise ValueError("Existing manifest belongs to another chain")
    if schema_only and not current:
        raise ValueError("Schema publication requires an existing deployment manifest")
    if chain_id == 11155111 and not schema_only:
        if not current:
            raise ValueError("Sepolia publication requires the reviewed configuration manifest")
        for field in SEPOLIA_INFRASTRUCTURE:
            if address(current.get(field), field) != address(prediction.get(field), field):
                raise ValueError(
                    f"Prediction differs from the reviewed Sepolia configuration: {field}"
                )
        for field in ("assetDecimals", "operationalWalletCount"):
            if type(current.get(field)) is not int or current[field] != prediction.get(field):
                raise ValueError(
                    f"Prediction differs from the reviewed Sepolia configuration: {field}"
                )
        if current.get("aToken") is not None and address(current["aToken"], "aToken") != address(
            prediction.get("aToken"), "aToken"
        ):
            raise ValueError("Prediction differs from the reviewed Sepolia configuration: aToken")
        if current.get("easAttester") is not None and address(
            current["easAttester"], "easAttester"
        ) != address(prediction.get("easAttester"), "easAttester"):
            raise ValueError("Prediction differs from the configured trusted attester")
    registry = address(prediction.get("easRegistry"), "easRegistry")
    uid = prediction.get("easSchemaUid")
    if not isinstance(uid, str):
        raise ValueError("Schema UID must be a scalar hex string")
    if schema_only and address(current.get("easRegistry"), "easRegistry") != registry:
        raise ValueError("Schema registry does not match the deployment manifest")
    verify_schema(registry, uid, rpc_url, block)
    if not schema_only:
        verify_deployment(prediction, rpc_url, block)
        current.update(_unset_as_null(prediction))
        current["deploymentStatus"] = "deployed"
        current["verifiedAtBlock"] = int(block)
    current.update(
        easSchemaUid=uid.lower(), easSchemaRegistered=True, easSchemaVerifiedAtBlock=int(block)
    )
    # Only replace the real manifest after every read-only verification has succeeded.
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=manifest_path.parent, delete=False
        ) as output:
            temporary = Path(output.name)
            json.dump(current, output, indent=2)
            output.write("\n")
        temporary.replace(manifest_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


_ZERO_ADDRESS = "0x" + "0" * 40
_ZERO_HASH = "0x" + "0" * 64


def _unset_as_null(prediction: dict[str, Any]) -> dict[str, Any]:
    """Forge serializes an unset address or code hash as zeros; record it as absent.

    A zero string is truthy, so leaving it in place would make consumers treat an
    un-deployed wallet (for example Sepolia's optional second Safe) as a real one.
    """

    return {
        key: None
        if isinstance(value, str) and value.lower() in (_ZERO_ADDRESS, _ZERO_HASH)
        else value
        for key, value in prediction.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--rpc-url", default=os.environ.get("ETH_RPC_URL"))
    parser.add_argument("--schema-only", action="store_true")
    args = parser.parse_args()
    if not args.rpc_url:
        raise ValueError("Set ETH_RPC_URL or --rpc-url for mined-state verification")
    publish(args.prediction, args.manifest, args.rpc_url, schema_only=args.schema_only)
    print("Manifest published from verified mined RPC state")


if __name__ == "__main__":
    main()
