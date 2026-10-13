from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict, cast

import pytest

from treasurypilot_core.fingerprint import fingerprint, normalize
from treasurypilot_core.money import BaseUnits

ASSET = "0x1111111111111111111111111111111111111111"
SEPARATORS = " -_/ .#\t\n\u2003"
VECTOR_PATH = (
    Path(__file__).resolve().parents[3]
    / "contracts"
    / "test"
    / "vectors"
    / "invoice_fingerprints.json"
)


class FingerprintVector(TypedDict):
    name: str
    vendor_id: str
    invoice_no: str
    normalized_vendor_id: str
    normalized_invoice_no: str
    amount: str
    asset: str
    fingerprint: str


def test_invoice_number_variants_produce_the_same_fingerprint() -> None:
    results = {
        fingerprint("vendor-001", invoice_no, BaseUnits(1_000_000), ASSET)
        for invoice_no in ("INV-001", "inv 001", "INV001")
    }

    assert len(results) == 1


def test_each_business_field_is_bound_into_the_fingerprint() -> None:
    baseline = fingerprint("vendor-001", "INV-001", BaseUnits(1_000_000), ASSET)
    changed_values = (
        fingerprint("vendor-002", "INV-001", BaseUnits(1_000_000), ASSET),
        fingerprint("vendor-001", "INV-002", BaseUnits(1_000_000), ASSET),
        fingerprint("vendor-001", "INV-001", BaseUnits(1_000_001), ASSET),
        fingerprint(
            "vendor-001",
            "INV-001",
            BaseUnits(1_000_000),
            "0x2222222222222222222222222222222222222222",
        ),
    )

    assert all(changed != baseline for changed in changed_values)
    assert len(set(changed_values)) == len(changed_values)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  INV-001  ", "inv001"),
        ("Café　SOCIÉTÉ", "cafésociété"),
        ("Straße_GmbH", "strassegmbh"),
        ("\t00012 / A#\n", "00012a"),
        ("INV:001", "inv:001"),
    ],
)
def test_normalize_handles_unicode_separators_and_leading_zeroes(value: str, expected: str) -> None:
    assert normalize(value) == expected


@pytest.mark.parametrize("value", ["AbC123", "InvoiceZero01", "Vendor9Z"])
def test_normalization_is_invariant_to_case_and_inserted_separators(value: str) -> None:
    for separator in SEPARATORS:
        decorated = separator + separator.join(value) + separator
        assert normalize(decorated) == value.casefold()


def test_shared_vectors_match_solidity_abi_encoding() -> None:
    document = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
    vectors = cast(list[FingerprintVector], document["vectors"])

    assert document["encoding"] == "keccak256(abi.encode(string,string,uint256,address))"
    for vector in vectors:
        assert normalize(vector["vendor_id"]) == vector["normalized_vendor_id"]
        assert normalize(vector["invoice_no"]) == vector["normalized_invoice_no"]
        actual = fingerprint(
            vector["vendor_id"],
            vector["invoice_no"],
            BaseUnits(int(vector["amount"])),
            vector["asset"],
        )
        assert "0x" + actual.hex() == vector["fingerprint"], vector["name"]


def test_asset_address_hex_casing_does_not_change_fingerprint() -> None:
    lowercase = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"
    uppercase = "0xABCDEFABCDEFABCDEFABCDEFABCDEFABCDEFABCD"

    assert fingerprint("vendor", "invoice", BaseUnits(1), lowercase) == fingerprint(
        "vendor", "invoice", BaseUnits(1), uppercase
    )


@pytest.mark.parametrize("value", ["", " - / # \t", "\ud800"])
def test_normalize_rejects_values_without_a_valid_identifier(value: str) -> None:
    with pytest.raises(ValueError):
        normalize(value)


def test_normalize_rejects_non_string_input() -> None:
    with pytest.raises(TypeError):
        normalize(123)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "asset",
    [
        "1111111111111111111111111111111111111111",
        "0x1111",
        "0xgggggggggggggggggggggggggggggggggggggggg",
    ],
)
def test_fingerprint_rejects_invalid_asset_address(asset: str) -> None:
    with pytest.raises(ValueError, match="EVM address"):
        fingerprint("vendor", "invoice", BaseUnits(1), asset)


def test_fingerprint_requires_integer_base_units() -> None:
    with pytest.raises(TypeError, match="BaseUnits"):
        fingerprint("vendor", "invoice", 1, ASSET)  # type: ignore[arg-type]


def test_fingerprint_rejects_amount_outside_uint256() -> None:
    with pytest.raises(ValueError, match="uint256"):
        fingerprint("vendor", "invoice", BaseUnits(1 << 256), ASSET)
