"""SC-019 receipt helper. Default is payload-only; broadcasting requires a dedicated keystore."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import cast

from cast_helpers import json_object, read_scalar, run_cast, verify_schema
from receipt_journal import load_journal, write_journal

from treasurypilot_core.attestations import (
    PAYMENT_RECEIPT_SCHEMA,
    PaymentReceipt,
    verify_payment_finality,
    verify_payment_receipt,
)


def trusted_attester(manifest: dict[str, object]) -> str:
    value = manifest.get("easAttester")
    if (
        not isinstance(value, str)
        or re.fullmatch(r"0x[0-9a-fA-F]{40}", value) is None
        or int(value[2:], 16) == 0
    ):
        raise ValueError("Configure a nonzero easAttester in the deployment manifest")
    return value.lower()


def verify_existing_receipt(
    eas: str, uid: str, schema: str, attester: str, receipt: PaymentReceipt, rpc_url: str
) -> None:
    if re.fullmatch(r"0x[0-9a-fA-F]{64}", uid) is None or int(uid[2:], 16) == 0:
        raise ValueError("Existing attestation UID must be nonzero bytes32")
    record = read_scalar(
        eas,
        "getAttestation(bytes32)((bytes32,bytes32,uint64,uint64,uint64,bytes32,address,address,bool,bytes))",
        [uid],
        rpc_url,
    )
    if (
        not isinstance(record, list)
        or len(record) != 10
        or str(record[0]).lower() != uid.lower()
        or str(record[1]).lower() != schema.lower()
        or str(record[3]) != "0"
        or str(record[4]) != "0"
        or str(record[5]).lower() != "0x" + "00" * 32
        or str(record[6]).lower() != receipt.payee
        or str(record[7]).lower() != attester
        or record[8] is not False
        or str(record[9]).lower() != "0x" + receipt.encode().hex()
    ):
        raise ValueError(
            "Existing EAS receipt does not match the trusted attester and payment payload"
        )


def receipt_uid(
    transaction: dict[str, object], eas: str, schema: str, attester: str, payee: str
) -> str:
    status = transaction.get("status")
    if isinstance(status, bool) or status not in (1, "1", "0x1"):
        raise ValueError("EAS transaction did not succeed; reconcile before retrying")
    topic = run_cast(["keccak", "Attested(address,address,bytes32,bytes32)"])
    expected_topics = [
        topic.lower(),
        "0x" + payee[2:].zfill(64),
        "0x" + attester[2:].zfill(64),
        schema.lower(),
    ]
    logs = transaction.get("logs")
    if not isinstance(logs, list):
        raise ValueError("EAS transaction has no attestation logs")
    matches = [
        entry
        for entry in logs
        if isinstance(entry, dict)
        and str(entry.get("address")).lower() == eas.lower()
        and [str(v).lower() for v in entry.get("topics", [])] == expected_topics
    ]
    if (
        len(matches) != 1
        or not isinstance(matches[0].get("data"), str)
        or re.fullmatch(r"0x[0-9a-fA-F]{64}", matches[0]["data"]) is None
    ):
        raise ValueError("EAS transaction must contain one matching trusted attestation")
    return str(matches[0]["data"]).lower()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--rpc-url", default=os.environ.get("ETH_RPC_URL"))
    parser.add_argument("--broadcast", action="store_true")
    parser.add_argument("--keystore", type=Path)
    parser.add_argument("--password-file", type=Path)
    parser.add_argument("--confirmations", type=int)
    parser.add_argument(
        "--journal", type=Path, help="Persistent per-request journal required for new submissions"
    )
    parser.add_argument(
        "--existing-uid", help="Verify and reuse a reconciled attestation; never sends"
    )
    args = parser.parse_args()
    values = cast(dict[str, object], json.loads(args.receipt.read_text(encoding="utf-8")))
    receipt = PaymentReceipt.from_mapping(values)
    manifest = cast(dict[str, object], json.loads(args.manifest.read_text(encoding="utf-8")))
    if manifest.get("chainId") not in (31337, 11155111):
        raise ValueError("Only local Anvil and Ethereum Sepolia are supported")
    schema_uid = str(manifest["easSchemaUid"])
    eas = str(manifest["eas"])
    payload = receipt.attest_tuple(schema_uid)
    if not args.broadcast and not args.existing_uid:
        print(
            json.dumps(
                {
                    "chainId": manifest["chainId"],
                    "eas": eas,
                    "schema": PAYMENT_RECEIPT_SCHEMA,
                    "attester": manifest.get("easAttester"),
                    "attest": payload,
                }
            )
        )
        return
    if not args.rpc_url or (
        not args.existing_uid and (not args.keystore or not args.password_file or not args.journal)
    ):
        raise ValueError(
            "New submission requires RPC, --keystore, --password-file and a persistent --journal"
        )
    observed_chain = int(run_cast(["chain-id", "--rpc-url", args.rpc_url]))
    if observed_chain != manifest["chainId"]:
        raise ValueError("RPC chain does not match the deployment manifest")
    attester = trusted_attester(manifest)
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
    payment_receipt = json_object(
        run_cast(["receipt", receipt.pay_tx_hash, "--rpc-url", args.rpc_url, "--json"])
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
    confirmations = args.confirmations if args.confirmations is not None else 0
    if confirmations < 0:
        raise ValueError("Confirmations cannot be negative")
    head = int(run_cast(["block-number", "--rpc-url", args.rpc_url]))
    if head - payment_block < confirmations:
        raise ValueError("Payment transaction has not reached the required confirmation count")
    canonical = json_object(
        run_cast(["block", str(payment_block), "--rpc-url", args.rpc_url, "--json"])
    )
    if observed_chain == 11155111:
        finalized = json_object(
            run_cast(["block", "finalized", "--rpc-url", args.rpc_url, "--json"])
        )
    else:
        # Local Anvil has no consensus finality; canonical receipt matching still applies.
        finalized = canonical
    verify_payment_finality(payment_receipt, canonical, finalized)
    verify_schema(str(manifest["easRegistry"]), schema_uid, args.rpc_url)
    if args.existing_uid:
        verify_existing_receipt(eas, args.existing_uid, schema_uid, attester, receipt, args.rpc_url)
        if not args.journal:
            print(
                json.dumps(
                    {"attestationUid": args.existing_uid, "schemaUid": schema_uid, "reused": True}
                )
            )
            return
    else:
        signer = run_cast(
            [
                "wallet",
                "address",
                "--keystore",
                str(args.keystore),
                "--password-file",
                str(args.password_file),
            ]
        )
        if signer.lower() != attester:
            raise ValueError("Receipt keystore address differs from the manifest easAttester")
    identity: dict[str, object] = {
        "chainId": observed_chain,
        "module": str(manifest["module"]).lower(),
        "eas": eas.lower(),
        "attester": attester,
        "requestId": receipt.request_id,
        "payloadHash": hashlib.sha256(receipt.encode()).hexdigest(),
    }
    journal = cast(Path, args.journal)
    lock = journal.with_name(journal.name + ".lock")
    try:
        with lock.open("x", encoding="utf-8") as handle:
            handle.write("submission lock\n")
    except FileExistsError:
        raise ValueError(
            "Receipt submission is already locked; reconcile before retrying"
        ) from None
    try:
        stored = load_journal(journal, identity)
        if args.existing_uid:
            # Recovery is explicit and read-only on chain. Never replace another confirmed UID.
            if (
                stored is not None
                and stored.get("state") == "confirmed"
                and stored.get("attestationUid") != args.existing_uid.lower()
            ):
                raise ValueError("Reconciled UID differs from the confirmed receipt journal")
            write_journal(
                journal, identity, state="confirmed", attestationUid=args.existing_uid.lower()
            )
            print(
                json.dumps(
                    {
                        "attestationUid": args.existing_uid.lower(),
                        "schemaUid": schema_uid,
                        "reused": True,
                    }
                )
            )
            return
        if stored is not None:
            uid = stored.get("attestationUid")
            if stored.get("state") != "confirmed" or not isinstance(uid, str):
                raise ValueError(
                    "Receipt submission outcome is uncertain; reconcile its UID before retrying"
                )
            verify_existing_receipt(eas, uid, schema_uid, attester, receipt, args.rpc_url)
            print(json.dumps({"attestationUid": uid, "schemaUid": schema_uid, "reused": True}))
            return
        # Persist before sending: even an RPC timeout or process exit blocks a second submission.
        write_journal(journal, identity, state="submitting")
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
        transaction = json_object(result)
        uid = receipt_uid(transaction, eas, schema_uid, attester, receipt.payee)
        verify_existing_receipt(eas, uid, schema_uid, attester, receipt, args.rpc_url)
        write_journal(
            journal,
            identity,
            state="confirmed",
            transactionHash=transaction.get("transactionHash"),
            attestationUid=uid,
        )
        print(
            json.dumps(
                {
                    "transactionHash": transaction.get("transactionHash"),
                    "attestationUid": uid,
                    "schemaUid": schema_uid,
                }
            )
        )
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
