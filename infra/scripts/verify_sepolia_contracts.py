"""Verify a published Sepolia deployment on Etherscan from its manifest."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import cast

from cast_helpers import run_cast

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
MANIFEST = ROOT / "deployments" / "11155111.json"
CONTRACTS_TO_VERIFY = (
    ("implementation", "src/TreasuryPilotModule.sol:TreasuryPilotModule"),
    ("factory", "src/TreasuryPilotModuleFactory.sol:TreasuryPilotModuleFactory"),
    ("testToken", "src/test-assets/TestUSDC.sol:TestUSDC"),
)


def _address(value: object, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"0x[0-9a-fA-F]{40}", value) is None:
        raise ValueError(f"Missing or invalid {field} in the Sepolia deployment manifest")
    if int(value[2:], 16) == 0:
        raise ValueError(f"Missing or invalid {field} in the Sepolia deployment manifest")
    return value


def _load_manifest(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("The Sepolia deployment manifest must be a JSON object")
    manifest = cast(dict[str, object], value)
    if manifest.get("chainId") != 11155111 or manifest.get("deploymentStatus") != "deployed":
        raise ValueError("Etherscan verification requires a published Sepolia deployment manifest")
    for field, _ in CONTRACTS_TO_VERIFY:
        _address(manifest.get(field), field)
        expected = manifest.get(field + "CodeHash")
        if not isinstance(expected, str) or re.fullmatch(r"0x[0-9a-fA-F]{64}", expected) is None:
            raise ValueError(
                f"Missing or invalid {field}CodeHash in the Sepolia deployment manifest"
            )
    return manifest


def _verify_mined_code(manifest: dict[str, object], rpc_url: str) -> None:
    if int(run_cast(["chain-id", "--rpc-url", rpc_url])) != 11155111:
        raise ValueError("RPC chain does not match Ethereum Sepolia (11155111)")
    for field, _ in CONTRACTS_TO_VERIFY:
        deployed = _address(manifest.get(field), field)
        code = run_cast(["code", deployed, "--rpc-url", rpc_url])
        if code == "0x" or re.fullmatch(r"0x(?:[0-9a-fA-F]{2})+", code) is None:
            raise ValueError(f"No mined runtime code for {field}")
        if run_cast(["keccak", code]).lower() != str(manifest[field + "CodeHash"]).lower():
            raise ValueError(f"Mined runtime hash differs for {field}")


def _forge_verify(
    address: str, contract: str, rpc_url: str, constructor_args: str | None = None
) -> None:
    command = [
        "forge",
        "verify-contract",
        address,
        contract,
        "--chain-id",
        "11155111",
        "--verifier",
        "etherscan",
        "--watch",
    ]
    if constructor_args is not None:
        command.extend(("--constructor-args", constructor_args))

    environment = os.environ.copy()
    environment["ETH_RPC_URL"] = rpc_url
    # Foundry reads the key from its supported environment variable so it never
    # appears in a process argument or the command printed in a CI log.
    try:
        result = subprocess.run(
            command, cwd=CONTRACTS, env=environment, capture_output=True, text=True, check=False
        )
    except OSError:
        raise RuntimeError("Cannot run forge; install the pinned Foundry toolchain") from None
    if result.returncode:
        raise RuntimeError(
            f"Etherscan verification failed for {contract} (forge exit {result.returncode})"
        )


def verify(manifest_path: Path = MANIFEST) -> None:
    rpc_url = os.environ.get("SEPOLIA_RPC_URL") or os.environ.get("ETH_RPC_URL")
    if not rpc_url:
        raise ValueError("Set SEPOLIA_RPC_URL or ETH_RPC_URL for mined-state verification")
    if not os.environ.get("ETHERSCAN_API_KEY"):
        raise ValueError("Set ETHERSCAN_API_KEY to verify the deployment on Etherscan")

    manifest = _load_manifest(manifest_path)
    _verify_mined_code(manifest, rpc_url)
    factory_args = run_cast(
        [
            "abi-encode",
            "constructor(address)",
            _address(manifest.get("implementation"), "implementation"),
        ]
    )
    for field, contract in CONTRACTS_TO_VERIFY:
        _forge_verify(
            _address(manifest.get(field), field),
            contract,
            rpc_url,
            factory_args if field == "factory" else None,
        )


def main() -> None:
    verify()
    print("Sepolia implementation, factory and tUSDC verified on Etherscan")


if __name__ == "__main__":
    main()
