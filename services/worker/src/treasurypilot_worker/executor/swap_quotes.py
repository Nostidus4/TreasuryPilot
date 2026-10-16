"""Quote source adapter and pre-send guard for production swaps (EXE-L02, F-065).

A SWAP step whose venue is ``SIGNED_QUOTE`` runs through ``SignedQuoteSwapAdapter``: before the
executor's ``swapForGas`` is signed, a quote for exactly the step's ``amount_in`` is fetched from a
``QuoteSource``, verified off-chain (``verify_swap_quote``: signature of an allowlisted signer, expiry,
pair, recipient, venue, route hash, plan floor) and staged on the adapter. A stale or forged quote
raises ``QuoteRejected`` and the sequencer stops the plan with that code; nothing is sent. The chain
re-checks every rule, so this guard only fails early and is never the sole defence.

No business rule depends on an LLM; amounts are integer base units. The quote source is an interface:
``FakeQuoteSource`` is the deterministic implementation for tests, ``HttpQuoteSource`` talks to a
configured endpoint (URL and API key come from settings, never from code).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import aiohttp
from eth_account import Account
from eth_account.messages import encode_typed_data

from treasurypilot_core.engine.swap_quote import (
    SIGNED_QUOTE_VENUE,
    QuotePolicy,
    QuoteRejected,
    SwapQuote,
    quote_typed_data,
    route_hash,
    submit_quote_calldata,
    verify_swap_quote,
)

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)


class QuoteSourceUnavailable(RuntimeError):
    """The quote source did not answer with a usable quote (transport, status or shape)."""


@dataclass(frozen=True)
class QuoteRequest:
    chain_id: int
    adapter: str
    taker: str  # Safe T: taker and recipient
    token_in: str
    token_out: str
    amount_in: int
    min_out: int  # the plan floor; the quote must promise at least this


@dataclass(frozen=True)
class SignedQuote:
    quote: SwapQuote
    route: bytes  # exact venue calldata whose hash the signer signed
    signature: bytes


class QuoteSource(Protocol):
    async def fetch(self, request: QuoteRequest) -> SignedQuote: ...


class FakeQuoteSource:
    """Deterministic signed quotes for tests: a fixed key, caller-supplied clock and route."""

    def __init__(
        self,
        private_key: str,
        venue: str,
        route_for: Callable[[QuoteRequest], bytes],
        *,
        now: Callable[[], int],
        ttl_seconds: int = 300,
        first_nonce: int = 1,
    ) -> None:
        self._account = Account.from_key(private_key)
        self._venue = venue
        self._route_for = route_for
        self._now = now
        self._ttl = ttl_seconds
        self._nonce = first_nonce

    @property
    def signer(self) -> str:
        return str(self._account.address)

    async def fetch(self, request: QuoteRequest) -> SignedQuote:
        route = self._route_for(request)
        quote = SwapQuote(
            taker=request.taker,
            recipient=request.taker,
            token_in=request.token_in,
            token_out=request.token_out,
            amount_in=request.amount_in,
            min_amount_out=request.min_out,  # the floor the plan fixed: the adapter requires equality
            venue=self._venue,
            route_hash=route_hash(route),
            expiry=self._now() + self._ttl,
            nonce=self._nonce,
        )
        self._nonce += 1
        typed = quote_typed_data(quote, chain_id=request.chain_id, adapter=request.adapter)
        signed = self._account.sign_message(encode_typed_data(full_message=typed))
        return SignedQuote(quote, route, bytes(signed.signature))


class HttpQuoteSource:
    """POSTs the request to a configured quote service and parses its JSON reply.

    Request: ``{chainId, adapter, taker, tokenIn, tokenOut, amountIn, minOut}`` (amounts as decimal
    strings). Reply: ``{quote: {...SwapQuote fields as decimal strings/hex...}, route, signature}``.
    The reply is untrusted: ``SwapQuoteGuard`` verifies it before anything is staged.
    """

    def __init__(self, url: str, api_key: str | None = None) -> None:
        self._url = url
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def fetch(self, request: QuoteRequest) -> SignedQuote:
        body = {
            "chainId": request.chain_id,
            "adapter": request.adapter,
            "taker": request.taker,
            "tokenIn": request.token_in,
            "tokenOut": request.token_out,
            "amountIn": str(request.amount_in),
            "minOut": str(request.min_out),
        }
        try:
            async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
                async with session.post(self._url, json=body, headers=self._headers) as reply:
                    if reply.status != 200:
                        raise QuoteSourceUnavailable(f"HTTP_{reply.status}")
                    data = await reply.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as error:
            raise QuoteSourceUnavailable(type(error).__name__) from error
        return parse_quote_reply(data)


def quote_source_from_settings(settings: Any) -> QuoteSource | None:
    """The configured production source, or None when ``TP_SWAP_QUOTE_URL`` is unset."""

    if not settings.swap_quote_url:
        return None
    key = settings.swap_quote_api_key.get_secret_value() if settings.swap_quote_api_key else None
    return HttpQuoteSource(settings.swap_quote_url, key)


def parse_quote_reply(data: Any) -> SignedQuote:
    try:
        q = data["quote"]
        quote = SwapQuote(
            taker=str(q["taker"]),
            recipient=str(q["recipient"]),
            token_in=str(q["tokenIn"]),
            token_out=str(q["tokenOut"]),
            amount_in=int(q["amountIn"]),
            min_amount_out=int(q["minAmountOut"]),
            venue=str(q["venue"]),
            route_hash=str(q["routeHash"]),
            expiry=int(q["expiry"]),
            nonce=int(q["nonce"]),
        )
        return SignedQuote(
            quote,
            bytes.fromhex(str(data["route"]).removeprefix("0x")),
            bytes.fromhex(str(data["signature"]).removeprefix("0x")),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise QuoteSourceUnavailable("MALFORMED_QUOTE_REPLY") from error


# (adapter address, calldata) -> returns once the staging transaction is mined, or raises.
Stager = Callable[[str, bytes], Awaitable[None]]


class SwapQuoteGuard:
    """Sequencer pre-send hook: fetch, verify and stage the quote of a ``SIGNED_QUOTE`` SWAP step."""

    def __init__(
        self,
        source: QuoteSource,
        policy: QuotePolicy,
        stager: Stager,
        *,
        now: Callable[[], int],
    ) -> None:
        self._source = source
        self._policy = policy
        self._stager = stager
        self._now = now

    async def __call__(self, step: Any) -> None:
        """No-op for any other step. Raises ``QuoteRejected`` when the step must not be sent."""

        request = step.sign_request
        step_hex = request["plan"]["steps"][request["stepSeq"]]["stepId"]
        swap = request["plan"].get("swaps", {}).get(step_hex)
        if step.kind != "SWAP" or swap is None or swap.get("venue") != SIGNED_QUOTE_VENUE:
            return
        plan_step = request["plan"]["steps"][request["stepSeq"]]
        amount_in, min_out = int(plan_step["amount"]), int(swap["minOut"])
        try:
            fetched = await self._source.fetch(
                QuoteRequest(
                    chain_id=self._policy.chain_id,
                    adapter=self._policy.adapter,
                    taker=self._policy.safe_t,
                    token_in=self._policy.token_in,
                    token_out=self._policy.token_out,
                    amount_in=amount_in,
                    min_out=min_out,
                )
            )
        except QuoteSourceUnavailable as error:
            raise QuoteRejected("SWAP_QUOTE_UNAVAILABLE", str(error)) from error
        signer = verify_swap_quote(
            fetched.quote,
            fetched.route,
            fetched.signature,
            self._policy,
            amount_in=amount_in,
            min_out=min_out,
            now=self._now(),
        )
        try:
            await self._stager(
                self._policy.adapter,
                submit_quote_calldata(fetched.quote, fetched.route, fetched.signature),
            )
        except Exception as error:  # a reverted or unsent staging tx must stop the plan too
            raise QuoteRejected("SWAP_QUOTE_STAGING_FAILED", type(error).__name__) from error
        logger.info(
            "swap quote staged",
            extra={"signer": signer, "amount_in": amount_in, "nonce": fetched.quote.nonce},
        )


__all__ = [
    "FakeQuoteSource",
    "HttpQuoteSource",
    "QuoteRequest",
    "QuoteSource",
    "QuoteSourceUnavailable",
    "SignedQuote",
    "SwapQuoteGuard",
    "parse_quote_reply",
    "quote_source_from_settings",
]
