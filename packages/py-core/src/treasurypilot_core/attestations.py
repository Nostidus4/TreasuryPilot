"""Pure encoding of the non-revocable ADR-018 payment receipt; no signing or I/O."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

PAYMENT_RECEIPT_SCHEMA = (
    "bytes32 requestId,bytes32 invoiceHash,bytes32 approvalHash,bytes32 planHash,"
    "bytes32 payTxHash,address payee,uint256 amount,bytes32 policyVersion"
)
RECEIPT_FIELDS = (
    "requestId",
    "invoiceHash",
    "approvalHash",
    "planHash",
    "payTxHash",
    "payee",
    "amount",
    "policyVersion",
)


def _hex_field(value: object, size: int, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(rf"0x[0-9a-fA-F]{{{size * 2}}}", value) is None:
        raise ValueError(f"{field} must be a {size}-byte hex value")
    if int(value[2:], 16) == 0:
        raise ValueError(f"{field} must be nonzero")
    return value.lower()


def _amount(value: object) -> int:
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        value = int(value)
    if type(value) is not int or not 0 < value < 2**256:
        raise ValueError("amount must be a positive uint256 in integer base units")
    return value


@dataclass(frozen=True, slots=True)
class PaymentReceipt:
    request_id: str
    invoice_hash: str
    approval_hash: str
    plan_hash: str
    pay_tx_hash: str
    payee: str
    amount: int
    policy_version: str

    def __post_init__(self) -> None:
        for name in (
            "request_id",
            "invoice_hash",
            "approval_hash",
            "plan_hash",
            "pay_tx_hash",
            "policy_version",
        ):
            object.__setattr__(self, name, _hex_field(getattr(self, name), 32, name))
        object.__setattr__(self, "payee", _hex_field(self.payee, 20, "payee"))
        object.__setattr__(self, "amount", _amount(self.amount))

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> PaymentReceipt:
        if set(values) != set(RECEIPT_FIELDS):
            unexpected = sorted(set(values) - set(RECEIPT_FIELDS))
            missing = sorted(set(RECEIPT_FIELDS) - set(values))
            raise ValueError(
                f"receipt fields must exactly match the schema: extra={unexpected}, missing={missing}"
            )
        return cls(
            request_id=_hex_field(values["requestId"], 32, "requestId"),
            invoice_hash=_hex_field(values["invoiceHash"], 32, "invoiceHash"),
            approval_hash=_hex_field(values["approvalHash"], 32, "approvalHash"),
            plan_hash=_hex_field(values["planHash"], 32, "planHash"),
            pay_tx_hash=_hex_field(values["payTxHash"], 32, "payTxHash"),
            payee=_hex_field(values["payee"], 20, "payee"),
            amount=_amount(values["amount"]),
            policy_version=_hex_field(values["policyVersion"], 32, "policyVersion"),
        )

    def encode(self) -> bytes:
        """ABI encode the eight static fields in the exact registered order."""
        return b"".join(
            (
                bytes.fromhex(self.request_id[2:]),
                bytes.fromhex(self.invoice_hash[2:]),
                bytes.fromhex(self.approval_hash[2:]),
                bytes.fromhex(self.plan_hash[2:]),
                bytes.fromhex(self.pay_tx_hash[2:]),
                bytes(12) + bytes.fromhex(self.payee[2:]),
                self.amount.to_bytes(32, "big"),
                bytes.fromhex(self.policy_version[2:]),
            )
        )

    def attest_tuple(self, schema_uid: str) -> str:
        """The EAS attest tuple: no expiry, no revocation, no reference, no ETH."""
        uid = _hex_field(schema_uid, 32, "schemaUid")
        return f"({uid},({self.payee},0,false,0x{'00' * 32},0x{self.encode().hex()},0))"


def _quantity(value: object, field: str) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 16) if value.startswith("0x") else int(value)
    raise ValueError(f"Invalid {field} in chain receipt")


def verify_payment_receipt(
    transaction: dict[str, object],
    module: str,
    request_id: str,
    payee: str,
    amount: int,
    payment_topic: str,
) -> int:
    """Return the mined block only for one successful, matching module payment event."""
    if _quantity(transaction.get("status"), "transaction status") != 1:
        raise ValueError("The payment transaction did not succeed")
    logs = transaction.get("logs")
    if not isinstance(logs, list):
        raise ValueError("The payment transaction has no logs")
    matches: list[dict[str, object]] = []
    for raw_log in logs:
        if (
            not isinstance(raw_log, dict)
            or str(raw_log.get("address", "")).lower() != module.lower()
        ):
            continue
        topics = raw_log.get("topics")
        if (
            isinstance(topics, list)
            and len(topics) >= 2
            and str(topics[0]).lower() == payment_topic.lower()
            and str(topics[1]).lower() == request_id.lower()
        ):
            matches.append(raw_log)
    if len(matches) != 1:
        raise ValueError("Payment transaction must contain exactly one matching treasury event")
    data = matches[0].get("data")
    if not isinstance(data, str) or not data.startswith("0x") or len(data) != 2 + 6 * 64:
        raise ValueError("Payment event data does not match the contract ABI")
    words = [data[2 + 64 * index : 2 + 64 * (index + 1)] for index in range(6)]
    observed_payee = "0x" + words[1][-40:]
    observed_amount = int(words[2], 16)
    if observed_payee.lower() != payee.lower() or observed_amount != amount:
        raise ValueError("Payment event payee or amount does not match the attestation payload")
    return _quantity(transaction.get("blockNumber"), "block number")
