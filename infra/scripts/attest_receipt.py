"""SC-019 receipt helper. Default is payload-only; broadcasting requires a dedicated keystore."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import cast

from treasurypilot_core.attestations import (
    PAYMENT_RECEIPT_SCHEMA,
    PaymentReceipt,
    verify_payment_receipt,
)


def run_cast(arguments: list[str]) -> str:
    result = subprocess.run(["cast", *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        # Do not echo RPC URLs, credential paths, passwords or provider error bodies.
        raise RuntimeError(
            "cast command failed; check RPC connectivity and the dedicated receipt keystore"
        )
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--rpc-url")
    parser.add_argument("--broadcast", action="store_true")
    parser.add_argument("--keystore", type=Path)
    parser.add_argument("--password-file", type=Path)
    parser.add_argument("--confirmations", type=int)
    args = parser.parse_args()
    values = cast(dict[str, object], json.loads(args.receipt.read_text(encoding="utf-8")))
    receipt = PaymentReceipt.from_mapping(values)
    manifest = cast(dict[str, object], json.loads(args.manifest.read_text(encoding="utf-8")))
    if manifest.get("chainId") not in (31337, 11155111):
        raise ValueError("Only local Anvil and Ethereum Sepolia are supported")
    schema_uid = str(manifest["easSchemaUid"])
    eas = str(manifest["eas"])
    payload = receipt.attest_tuple(schema_uid)
    if not args.broadcast:
        print(
            json.dumps(
                {
                    "chainId": manifest["chainId"],
                    "eas": eas,
                    "schema": PAYMENT_RECEIPT_SCHEMA,
                    "attest": payload,
                }
            )
        )
        return
    if not args.rpc_url or not args.keystore or not args.password_file:
        raise ValueError(
            "Broadcast requires --rpc-url, --keystore and --password-file for the dedicated receipt key"
        )
    observed_chain = int(run_cast(["chain-id", "--rpc-url", args.rpc_url]))
    if observed_chain != manifest["chainId"]:
        raise ValueError("RPC chain does not match the deployment manifest")
    paid = run_cast(
        [
            "call",
            str(manifest["module"]),
            "requestPaid(bytes32)(bool)",
            receipt.request_id,
            "--rpc-url",
            args.rpc_url,
        ]
    )
    if paid != "true":
        raise ValueError("The treasury module does not confirm this request as paid")
    payment_receipt = cast(
        dict[str, object],
        json.loads(run_cast(["receipt", receipt.pay_tx_hash, "--rpc-url", args.rpc_url, "--json"])),
    )
    topic = run_cast(
        [
            "keccak",
            "PaymentExecuted(bytes32,bytes32,bytes32,address,address,uint256,uint256,bool,bool)",
        ]
    )
    payment_block = verify_payment_receipt(
        payment_receipt,
        str(manifest["module"]),
        receipt.request_id,
        receipt.payee,
        receipt.amount,
        topic,
    )
    confirmations = (
        args.confirmations
        if args.confirmations is not None
        else (0 if observed_chain == 31337 else 12)
    )
    if confirmations < 0:
        raise ValueError("Confirmations cannot be negative")
    head = int(run_cast(["block-number", "--rpc-url", args.rpc_url]))
    if head - payment_block < confirmations:
        raise ValueError("Payment transaction has not reached the required confirmation count")

    schema = run_cast(
        [
            "call",
            str(manifest["easRegistry"]),
            "getSchema(bytes32)((bytes32,address,bool,string))",
            schema_uid,
            "--rpc-url",
            args.rpc_url,
        ]
    )
    if "false" not in schema.lower() or PAYMENT_RECEIPT_SCHEMA not in schema:
        raise ValueError(
            "The manifest EAS schema is missing, revocable, or does not match the receipt contract"
        )
    result = run_cast(
        [
            "send",
            eas,
            "attest((bytes32,(address,uint64,bool,bytes32,bytes,uint256)))(bytes32)",
            payload,
            "--rpc-url",
            args.rpc_url,
            "--keystore",
            str(args.keystore),
            "--password-file",
            str(args.password_file),
            "--json",
        ]
    )
    transaction = cast(dict[str, object], json.loads(result))
    print(
        json.dumps({"transactionHash": transaction.get("transactionHash"), "schemaUid": schema_uid})
    )


if __name__ == "__main__":
    main()
