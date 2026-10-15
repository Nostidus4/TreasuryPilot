"""Web3 receipt publisher against a fake web3 (REC-005); the live-chain path is verified on Sepolia."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from eth_account import Account
from web3 import Web3
from web3.exceptions import TransactionNotFound

from treasurypilot_core.attestations import ATTESTED_EVENT, PAYMENT_RECEIPT_SCHEMA_UID
from treasurypilot_worker.reconcile.receipt import ReceiptReverted, Web3ReceiptPublisher

_KEY = "0x" + "11" * 32
_EAS = "0x" + "ea" * 20
_UID = bytes.fromhex("ee" * 32)


def _publisher(mined: Any) -> Web3ReceiptPublisher:
    publisher = object.__new__(Web3ReceiptPublisher)
    publisher.account = Account.from_key(_KEY)
    publisher.eas = Web3.to_checksum_address(_EAS)
    publisher.schema_uid = PAYMENT_RECEIPT_SCHEMA_UID

    def get_transaction_receipt(_: object) -> Any:
        if mined is None:
            raise TransactionNotFound("pending")
        return mined

    publisher.web3 = SimpleNamespace(  # type: ignore[assignment]
        eth=SimpleNamespace(get_transaction_receipt=get_transaction_receipt)
    )
    return publisher


def _log(publisher: Web3ReceiptPublisher, **overrides: Any) -> dict[str, Any]:
    attester = bytes(12) + bytes.fromhex(publisher.account.address[2:])
    entry = {
        "address": publisher.eas,
        "topics": [
            Web3.keccak(text=ATTESTED_EVENT),
            bytes(32),
            attester,
            bytes.fromhex(PAYMENT_RECEIPT_SCHEMA_UID[2:]),
        ],
        "data": _UID,
    }
    return {**entry, **overrides}


def test_result_returns_the_uid_of_the_single_matching_attested_event() -> None:
    probe = _publisher(None)
    assert probe.result(bytes(32)) is None  # not mined yet
    publisher = _publisher({"status": 1, "logs": [_log(probe)]})
    assert publisher.result(bytes(32)) == _UID


@pytest.mark.parametrize(
    "mined",
    [
        {"status": 0, "logs": []},
        {"status": 1, "logs": []},
        {"status": 1, "logs": [{"address": "0x" + "00" * 20, "topics": [], "data": b""}]},
    ],
)
def test_result_rejects_reverted_or_foreign_receipts(mined: dict[str, Any]) -> None:
    with pytest.raises(ReceiptReverted):
        _publisher(mined).result(bytes(32))
