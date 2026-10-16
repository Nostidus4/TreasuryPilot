"""Signed swap quotes for the production adapter (F-065, EXE-L02 / SC-L03).

Mirrors ``SwapQuoteHash.sol`` and ``SignedQuoteSwapAdapter.submitQuote`` so a bad quote is stopped
off-chain, before any transaction is sent. The chain stays the authority: the adapter re-checks every
rule. Pure and deterministic: no I/O, no clock (``now`` is passed in), money in integer base units.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from eth_abi import encode
from eth_hash.auto import keccak

from treasurypilot_core.domain.models import FrozenModel
from treasurypilot_core.eip712 import _typed_data, digest, verify_signature

SIGNED_QUOTE_VENUE: Literal["SIGNED_QUOTE"] = "SIGNED_QUOTE"
SWAP_QUOTE_DOMAIN = "TreasuryPilot Swap Quote"

SWAP_QUOTE_TYPE = [
    {"name": "taker", "type": "address"},
    {"name": "recipient", "type": "address"},
    {"name": "tokenIn", "type": "address"},
    {"name": "tokenOut", "type": "address"},
    {"name": "amountIn", "type": "uint256"},
    {"name": "minAmountOut", "type": "uint256"},
    {"name": "venue", "type": "address"},
    {"name": "routeHash", "type": "bytes32"},
    {"name": "expiry", "type": "uint64"},
    {"name": "nonce", "type": "uint256"},
]
_QUOTE_TUPLE = "(address,address,address,address,uint256,uint256,address,bytes32,uint64,uint256)"
_SUBMIT_QUOTE = f"submitQuote({_QUOTE_TUPLE},bytes,bytes)"


class QuoteRejected(ValueError):
    """A quote must not be used. ``code`` is stable and becomes the plan's stop code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class SwapQuote(FrozenModel):
    taker: str
    recipient: str
    token_in: str
    token_out: str
    amount_in: int
    min_amount_out: int
    venue: str
    route_hash: str  # 0x + 32 bytes: keccak256 of the exact route calldata
    expiry: int  # last valid unix second
    nonce: int


class QuotePolicy(FrozenModel):
    """What the worker accepts, mirroring the adapter's on-chain configuration."""

    chain_id: int
    adapter: str
    safe_t: str  # taker and recipient
    token_in: str
    token_out: str
    signers: tuple[str, ...]  # allowlisted quote signers
    venues: tuple[str, ...]  # allowlisted routers
    max_ttl_seconds: int


def route_hash(route: bytes) -> str:
    return "0x" + keccak(route).hex()


def quote_typed_data(quote: SwapQuote, *, chain_id: int, adapter: str) -> dict[str, Any]:
    message = {
        "taker": quote.taker,
        "recipient": quote.recipient,
        "tokenIn": quote.token_in,
        "tokenOut": quote.token_out,
        "amountIn": quote.amount_in,
        "minAmountOut": quote.min_amount_out,
        "venue": quote.venue,
        "routeHash": quote.route_hash,
        "expiry": quote.expiry,
        "nonce": quote.nonce,
    }
    return _typed_data("SwapQuote", SWAP_QUOTE_TYPE, SWAP_QUOTE_DOMAIN, message, chain_id, adapter)


def quote_digest(quote: SwapQuote, *, chain_id: int, adapter: str) -> bytes:
    """Equals ``SignedQuoteSwapAdapter.quoteDigest`` for the same quote, chain and adapter."""
    return digest(quote_typed_data(quote, chain_id=chain_id, adapter=adapter))


def _same(a: str, b: str) -> bool:
    return a.lower() == b.lower()


def verify_swap_quote(
    quote: SwapQuote,
    route: bytes,
    signature: bytes,
    policy: QuotePolicy,
    *,
    amount_in: int,
    min_out: int,
    now: int,
) -> str:
    """Return the signer address, or raise ``QuoteRejected`` with a stable code.

    ``amount_in`` and ``min_out`` are what the plan step carries: the quote must swap exactly that
    input and its signed floor must equal the step's ``min_out`` (a lower floor weakens the plan's
    price bound; a higher one makes the adapter revert ``QuoteMismatch``).
    """
    if now > quote.expiry:
        raise QuoteRejected("SWAP_QUOTE_EXPIRED")
    if quote.expiry - now > policy.max_ttl_seconds:
        raise QuoteRejected("SWAP_QUOTE_TTL_TOO_LONG")
    if not _same(quote.taker, policy.safe_t) or not _same(quote.recipient, policy.safe_t):
        raise QuoteRejected("SWAP_QUOTE_WRONG_RECIPIENT")
    if not _same(quote.token_in, policy.token_in) or not _same(quote.token_out, policy.token_out):
        raise QuoteRejected("SWAP_QUOTE_WRONG_PAIR")
    if quote.amount_in != amount_in or amount_in <= 0:
        raise QuoteRejected("SWAP_QUOTE_AMOUNT_MISMATCH")
    if min_out <= 0 or quote.min_amount_out < min_out:
        raise QuoteRejected("SWAP_QUOTE_BELOW_PLAN_MIN_OUT")
    # The adapter reverts unless the executor's minOut (fixed by the attested plan) >= the signed
    # floor, so a floor above the plan's minOut could never execute: stop now, not on chain.
    if quote.min_amount_out > min_out:
        raise QuoteRejected("SWAP_QUOTE_FLOOR_ABOVE_PLAN_MIN_OUT")
    if not any(_same(quote.venue, venue) for venue in policy.venues):
        raise QuoteRejected("SWAP_QUOTE_VENUE_NOT_ALLOWED")
    if quote.route_hash.lower() != route_hash(route):
        raise QuoteRejected("SWAP_QUOTE_ROUTE_MISMATCH")
    typed = quote_typed_data(quote, chain_id=policy.chain_id, adapter=policy.adapter)
    signers: Sequence[str] = policy.signers
    for signer in signers:  # forged = signed by nobody on the allowlist
        if verify_signature(typed, signer, signature):
            return signer
    raise QuoteRejected("SWAP_QUOTE_FORGED")


def submit_quote_calldata(quote: SwapQuote, route: bytes, signature: bytes) -> bytes:
    """``SignedQuoteSwapAdapter.submitQuote(quote, route, signature)`` calldata (permissionless)."""
    args = (
        quote.taker,
        quote.recipient,
        quote.token_in,
        quote.token_out,
        quote.amount_in,
        quote.min_amount_out,
        quote.venue,
        bytes.fromhex(quote.route_hash[2:]),
        quote.expiry,
        quote.nonce,
    )
    selector = keccak(_SUBMIT_QUOTE.encode())[:4]
    return selector + encode([_QUOTE_TUPLE, "bytes", "bytes"], [args, route, signature])


__all__ = [
    "SIGNED_QUOTE_VENUE",
    "QuotePolicy",
    "QuoteRejected",
    "SwapQuote",
    "quote_digest",
    "quote_typed_data",
    "route_hash",
    "submit_quote_calldata",
    "verify_swap_quote",
]
