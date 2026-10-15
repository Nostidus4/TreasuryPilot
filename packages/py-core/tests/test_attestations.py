import pytest

from treasurypilot_core.attestations import (
    PaymentReceipt,
    easscan_url,
    verify_payment_finality,
    verify_payment_receipt,
)


def fixture_receipt() -> dict[str, object]:
    return {
        "requestId": "0x" + "01" * 32,
        "invoiceHash": "0x" + "02" * 32,
        "approvalHash": "0x" + "03" * 32,
        "planHash": "0x" + "04" * 32,
        "payTxHash": "0x" + "05" * 32,
        "payee": "0x" + "06" * 20,
        "amount": "9007199254740993000000",
        "policyVersion": "0x" + "07" * 32,
    }


def test_exact_schema_order_and_integer_abi_encoding() -> None:
    receipt = PaymentReceipt.from_mapping(fixture_receipt())
    encoded = receipt.encode()
    assert len(encoded) == 256
    assert encoded[:32] == bytes.fromhex("01" * 32)
    assert encoded[160:192] == bytes(12) + bytes.fromhex("06" * 20)
    assert int.from_bytes(encoded[192:224], "big") == 9007199254740993000000
    assert encoded[224:] == bytes.fromhex("07" * 32)


@pytest.mark.parametrize("field", ["vendorName", "invoiceText", "signature", "revocable"])
def test_extra_fields_are_rejected(field: str) -> None:
    values = fixture_receipt()
    values[field] = "not permitted"
    with pytest.raises(ValueError, match="exactly match"):
        PaymentReceipt.from_mapping(values)


@pytest.mark.parametrize("amount", [True, False, 0, -1, 1.5, "1.5", "+1", 2**256])
def test_money_must_be_positive_integer_base_units(amount: object) -> None:
    values = fixture_receipt()
    values["amount"] = amount
    with pytest.raises(ValueError, match="uint256"):
        PaymentReceipt.from_mapping(values)


def test_missing_fields_and_wrong_hash_lengths_are_rejected() -> None:
    values = fixture_receipt()
    del values["invoiceHash"]
    with pytest.raises(ValueError, match="missing"):
        PaymentReceipt.from_mapping(values)
    values = fixture_receipt()
    values["payTxHash"] = "0x1234"
    with pytest.raises(ValueError, match="32-byte"):
        PaymentReceipt.from_mapping(values)


def test_attest_payload_is_non_revocable_has_no_expiry_and_no_eth() -> None:
    receipt = PaymentReceipt.from_mapping(fixture_receipt())
    payload = receipt.attest_tuple("0x" + "08" * 32)
    assert ",0,false,0x" in payload
    assert payload.endswith(",0))")


def test_receipt_requires_matching_successful_module_event() -> None:
    values = fixture_receipt()
    event_topic = "0x" + "ab" * 32
    module = "0x" + "11" * 20
    payee = str(values["payee"])
    amount = int(str(values["amount"]))
    data = "0x" + "00" * 32 + "00" * 12 + payee[2:] + amount.to_bytes(32, "big").hex() + "00" * 96
    transaction: dict[str, object] = {
        "status": "0x1",
        "blockNumber": "0x20",
        "logs": [{"address": module, "topics": [event_topic, values["requestId"]], "data": data}],
    }
    assert (
        verify_payment_receipt(
            transaction, module, str(values["requestId"]), payee, amount, event_topic
        )
        == 32
    )
    transaction["status"] = "0x0"
    with pytest.raises(ValueError, match="did not succeed"):
        verify_payment_receipt(
            transaction, module, str(values["requestId"]), payee, amount, event_topic
        )
    transaction["status"] = "0x1"
    transaction["logs"] = []
    with pytest.raises(ValueError, match="matching treasury event"):
        verify_payment_receipt(
            transaction, module, str(values["requestId"]), payee, amount, event_topic
        )


def test_payment_finality_requires_a_canonical_finalized_block() -> None:
    block_hash = "0x" + "ab" * 32
    receipt = {"blockNumber": "0x64", "blockHash": block_hash}
    canonical = {"number": 100, "hash": block_hash}
    with pytest.raises(ValueError, match="has not reached finalized"):
        verify_payment_finality(receipt, canonical, {"number": 99, "hash": "0x" + "cd" * 32})
    verify_payment_finality(receipt, canonical, {"number": 100, "hash": block_hash})
    verify_payment_finality(receipt, canonical, {"number": 110, "hash": "0x" + "cd" * 32})
    with pytest.raises(ValueError, match="canonical chain"):
        verify_payment_finality(receipt, {"number": 100, "hash": "0x" + "cd" * 32}, canonical)
    with pytest.raises(ValueError, match="Finalized block hash"):
        verify_payment_finality(receipt, canonical, {"number": 100, "hash": "0x" + "cd" * 32})


@pytest.mark.parametrize("number", [True, False, -1, "-1", "+1", "1.5", None])
def test_finality_rejects_invalid_block_quantities(number: object) -> None:
    block_hash = "0x" + "ab" * 32
    with pytest.raises(ValueError, match="Invalid"):
        verify_payment_finality(
            {"blockNumber": 1, "blockHash": block_hash},
            {"number": 1, "hash": block_hash},
            {"number": number, "hash": block_hash},
        )


def test_easscan_url_links_the_published_uid() -> None:
    uid = "0x" + "AB" * 32
    assert (
        easscan_url(11155111, uid) == "https://sepolia.easscan.org/attestation/view/0x" + "ab" * 32
    )
    assert easscan_url(1, bytes.fromhex("cd" * 32)) == (
        "https://easscan.org/attestation/view/0x" + "cd" * 32
    )
    assert easscan_url(31337, uid) is None  # local Anvil has no explorer
    assert easscan_url(11155111, None) is None
    with pytest.raises(ValueError, match="attestationUid"):
        easscan_url(11155111, "0x1234")
