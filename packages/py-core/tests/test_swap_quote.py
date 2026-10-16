"""EXE-L02 / SC-L03: off-chain verification of signed swap quotes mirrors the adapter's staging checks."""

from __future__ import annotations

from typing import Any

import pytest
from eth_abi import decode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_hash.auto import keccak

from treasurypilot_core.engine.swap_quote import (
    QuotePolicy,
    QuoteRejected,
    SwapQuote,
    quote_digest,
    quote_typed_data,
    route_hash,
    submit_quote_calldata,
    verify_swap_quote,
)

SIGNER = Account.from_key("0x" + "a1" * 32)
OTHER = Account.from_key("0x" + "b2" * 32)
SAFE_T = "0x" + "22" * 20
TOKEN_IN = "0x" + "55" * 20
TOKEN_OUT = "0x" + "66" * 20
VENUE = "0x" + "77" * 20
ADAPTER = "0x" + "88" * 20
ROUTE = b"\x12\x34swap"
NOW = 1_800_000_000

POLICY = QuotePolicy(
    chain_id=31337,
    adapter=ADAPTER,
    safe_t=SAFE_T,
    token_in=TOKEN_IN,
    token_out=TOKEN_OUT,
    signers=(SIGNER.address,),
    venues=(VENUE,),
    max_ttl_seconds=600,
)


def _quote(**overrides: Any) -> SwapQuote:
    fields: dict[str, Any] = {
        "taker": SAFE_T,
        "recipient": SAFE_T,
        "token_in": TOKEN_IN,
        "token_out": TOKEN_OUT,
        "amount_in": 100,
        "min_amount_out": 190,
        "venue": VENUE,
        "route_hash": route_hash(ROUTE),
        "expiry": NOW + 300,
        "nonce": 1,
    }
    fields.update(overrides)
    return SwapQuote(**fields)


def _sign(quote: SwapQuote, account: Any = SIGNER) -> bytes:
    typed = quote_typed_data(quote, chain_id=31337, adapter=ADAPTER)
    return bytes(account.sign_message(encode_typed_data(full_message=typed)).signature)


def _verify(
    quote: SwapQuote, signature: bytes | None = None, *, route: bytes = ROUTE, now: int = NOW
) -> str:
    return verify_swap_quote(
        quote,
        route,
        signature if signature is not None else _sign(quote),
        POLICY,
        amount_in=100,
        min_out=190,
        now=now,
    )


def test_a_valid_quote_returns_its_signer() -> None:
    assert _verify(_quote()) == SIGNER.address


def test_digest_binds_chain_and_adapter() -> None:
    quote = _quote()
    base = quote_digest(quote, chain_id=31337, adapter=ADAPTER)
    assert len(base) == 32
    assert quote_digest(quote, chain_id=1, adapter=ADAPTER) != base
    assert quote_digest(quote, chain_id=31337, adapter="0x" + "99" * 20) != base


def test_expired_quote_is_rejected_but_the_last_second_is_valid() -> None:
    quote = _quote()
    assert _verify(quote, now=quote.expiry) == SIGNER.address
    with pytest.raises(QuoteRejected) as raised:
        _verify(quote, now=quote.expiry + 1)
    assert raised.value.code == "SWAP_QUOTE_EXPIRED"


def test_forged_quotes_are_rejected() -> None:
    quote = _quote()
    for signature in (
        _sign(quote, OTHER),  # signed by a key that is not allowlisted
        b"\x00" * 65,
        b"short",
        _sign(_quote(min_amount_out=195)),  # a signature over different terms
    ):
        with pytest.raises(QuoteRejected) as raised:
            _verify(quote, signature)
        assert raised.value.code == "SWAP_QUOTE_FORGED"


def test_a_tampered_field_breaks_the_signature() -> None:
    signature = _sign(_quote())
    with pytest.raises(QuoteRejected) as raised:
        _verify(_quote(nonce=2), signature)
    assert raised.value.code == "SWAP_QUOTE_FORGED"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"recipient": "0x" + "01" * 20}, "SWAP_QUOTE_WRONG_RECIPIENT"),
        ({"taker": "0x" + "01" * 20}, "SWAP_QUOTE_WRONG_RECIPIENT"),
        ({"token_out": "0x" + "01" * 20}, "SWAP_QUOTE_WRONG_PAIR"),
        ({"token_in": TOKEN_OUT, "token_out": TOKEN_IN}, "SWAP_QUOTE_WRONG_PAIR"),
        ({"amount_in": 101}, "SWAP_QUOTE_AMOUNT_MISMATCH"),
        ({"min_amount_out": 189}, "SWAP_QUOTE_BELOW_PLAN_MIN_OUT"),
        ({"min_amount_out": 191}, "SWAP_QUOTE_FLOOR_ABOVE_PLAN_MIN_OUT"),
        ({"venue": "0x" + "01" * 20}, "SWAP_QUOTE_VENUE_NOT_ALLOWED"),
        ({"route_hash": route_hash(b"other")}, "SWAP_QUOTE_ROUTE_MISMATCH"),
        ({"expiry": NOW + 601}, "SWAP_QUOTE_TTL_TOO_LONG"),
    ],
)
def test_signed_but_unacceptable_quotes_are_rejected(overrides: dict[str, Any], code: str) -> None:
    quote = _quote(**overrides)
    with pytest.raises(QuoteRejected) as raised:
        _verify(quote, _sign(quote))
    assert raised.value.code == code


def test_a_swapped_route_does_not_match_the_signed_hash() -> None:
    with pytest.raises(QuoteRejected) as raised:
        _verify(_quote(), route=b"\xde\xad")
    assert raised.value.code == "SWAP_QUOTE_ROUTE_MISMATCH"


def test_address_comparison_ignores_case() -> None:
    upper = "0x" + SAFE_T[2:].upper()
    quote = _quote(taker=upper, recipient=upper)
    assert _verify(quote, _sign(quote)) == SIGNER.address


def test_submit_quote_calldata_roundtrips() -> None:
    quote, signature = _quote(), _sign(_quote())
    data = submit_quote_calldata(quote, ROUTE, signature)
    tuple_type = "(address,address,address,address,uint256,uint256,address,bytes32,uint64,uint256)"
    assert data[:4] == keccak(f"submitQuote({tuple_type},bytes,bytes)".encode())[:4]
    args, route, sig = decode([tuple_type, "bytes", "bytes"], data[4:])
    assert (route, sig) == (ROUTE, signature)
    assert args[4] == 100 and args[5] == 190 and args[9] == 1
    assert "0x" + args[7].hex() == quote.route_hash
