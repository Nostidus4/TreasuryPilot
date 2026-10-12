"""Read-only Foundry adapters with strict ABI decoding and redacted failures."""

from __future__ import annotations

import json
import os
import subprocess
from typing import cast

from treasurypilot_core.attestations import PAYMENT_RECEIPT_SCHEMA, PAYMENT_RECEIPT_SCHEMA_UID


def run_cast(arguments: list[str]) -> str:
    # Large runtime bytecode exceeds Windows' command-line limit; cast accepts keccak input on stdin.
    process_arguments = list(arguments)
    environment = os.environ.copy()
    if "--rpc-url" in process_arguments:
        index = process_arguments.index("--rpc-url")
        environment["ETH_RPC_URL"] = process_arguments[index + 1]
        del process_arguments[index : index + 2]
    command = ["cast", *process_arguments]
    stdin = None
    if len(arguments) == 2 and arguments[0] == "keccak":
        command = ["cast", "keccak"]
        stdin = arguments[1]
    try:
        result = subprocess.run(
            command, input=stdin, env=environment, capture_output=True, text=True, check=False
        )
    except OSError:
        raise RuntimeError("Cannot run cast; check the local Foundry installation") from None
    if result.returncode:
        raise RuntimeError(
            "cast command failed; check RPC connectivity and local wallet configuration"
        )
    return result.stdout.strip()


def json_object(output: str) -> dict[str, object]:
    """Accept RPC receipt objects and Foundry's versioned JSON block envelopes."""
    value = json.loads(output)
    if isinstance(value, dict) and "schema_version" in value:
        if value.get("schema_version") != 1 or value.get("success") is not True:
            raise ValueError("Cast returned an unsuccessful or unsupported JSON response")
        value = value.get("data")
    if not isinstance(value, dict):
        raise ValueError("Cast returned no JSON block or transaction object")
    return cast(dict[str, object], value)


def read_call(
    address: str,
    signature: str,
    arguments: list[str],
    rpc_url: str,
    block: str = "latest",
) -> list[object]:
    # All inputs here are flat types; omit output types so cast call returns raw ABI bytes.
    input_signature = signature[: signature.index(")") + 1]
    raw = run_cast(
        ["call", address, input_signature, *arguments, "--rpc-url", rpc_url, "--block", block]
    )
    decoded = json.loads(run_cast(["abi-decode", signature, raw, "--json"]))
    if not isinstance(decoded, dict) or decoded.get("success") is not True:
        raise ValueError("Invalid ABI response from the configured contract")
    data = decoded.get("data")
    if not isinstance(data, list):
        raise ValueError("Missing decoded contract response")
    return cast(list[object], data)


def read_scalar(
    address: str,
    signature: str,
    arguments: list[str],
    rpc_url: str,
    block: str = "latest",
) -> object:
    data = read_call(address, signature, arguments, rpc_url, block)
    if len(data) != 1:
        raise ValueError("Expected a single contract return value")
    return data[0]


def verify_schema(registry: str, uid: str, rpc_url: str, block: str = "latest") -> None:
    if uid.lower() != PAYMENT_RECEIPT_SCHEMA_UID:
        raise ValueError("The schema UID does not match TreasuryPilot Payment Receipt v1")
    data = read_scalar(
        registry, "getSchema(bytes32)((bytes32,address,bool,string))", [uid], rpc_url, block
    )
    if (
        not isinstance(data, list)
        or len(data) != 4
        or str(data[0]).lower() != PAYMENT_RECEIPT_SCHEMA_UID
        or str(data[1]).lower() != "0x" + "00" * 20
        or data[2] is not False
        or data[3] != PAYMENT_RECEIPT_SCHEMA
    ):
        raise ValueError("The registered receipt schema is missing or does not match its exact ABI")
