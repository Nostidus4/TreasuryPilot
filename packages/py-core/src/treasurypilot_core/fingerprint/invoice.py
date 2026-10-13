"""Invoice duplicate fingerprint implementation."""

from __future__ import annotations

import re
import unicodedata

from eth_abi import encode
from eth_hash.auto import keccak

from treasurypilot_core.money import BaseUnits

_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_SEPARATORS = frozenset("-_/ .#")
_UINT256_LIMIT = 1 << 256


def normalize(value: str) -> str:
    """Return the canonical invoice/vendor identifier used for fingerprints.

    The value is trimmed and Unicode-case-folded. All Unicode whitespace and
    the separators ``- _ / . #`` are removed. Digits are otherwise untouched,
    so significant leading zeroes remain part of an invoice number.
    """

    if not isinstance(value, str):
        raise TypeError("fingerprint components must be strings")

    canonical = value.strip().casefold()
    normalized = "".join(
        character
        for character in canonical
        if not character.isspace() and character not in _SEPARATORS
    )
    if not normalized:
        raise ValueError("fingerprint components cannot be empty after normalization")
    if any(unicodedata.category(character) == "Cs" for character in normalized):
        raise ValueError("fingerprint components must contain valid Unicode scalar values")
    return normalized


def fingerprint(
    vendor_id: str,
    invoice_no: str,
    amount: BaseUnits,
    asset: str,
) -> bytes:
    """Compute the contract-compatible duplicate-invoice fingerprint.

    ``amount`` is encoded as a Solidity ``uint256`` in integer base units and
    ``asset`` as an EVM ``address``. The returned 32 bytes are suitable for a
    Solidity ``bytes32`` value; use ``"0x" + value.hex()`` at JSON boundaries.
    """

    if not isinstance(amount, BaseUnits):
        raise TypeError("amount must be BaseUnits")
    if amount >= _UINT256_LIMIT:
        raise ValueError("amount does not fit in a Solidity uint256")
    if not isinstance(asset, str):
        raise TypeError("asset must be an EVM address string")
    if _EVM_ADDRESS.fullmatch(asset) is None:
        raise ValueError("asset must be a 0x-prefixed 20-byte EVM address")

    normalized_vendor = normalize(vendor_id)
    normalized_invoice = normalize(invoice_no)
    asset_bytes = bytes.fromhex(asset[2:])
    encoded = encode(
        ["string", "string", "uint256", "address"],
        [normalized_vendor, normalized_invoice, int(amount), asset_bytes],
    )
    return keccak(encoded)
