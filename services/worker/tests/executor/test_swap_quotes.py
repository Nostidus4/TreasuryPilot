"""EXE-L02: the quote source adapter and the pre-send guard (no database, no chain)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from eth_account import Account

from treasurypilot_core.engine.swap_quote import (
    SIGNED_QUOTE_VENUE,
    QuotePolicy,
    QuoteRejected,
    route_hash,
)
from treasurypilot_worker.executor.swap_quotes import (
    FakeQuoteSource,
    HttpQuoteSource,
    QuoteRequest,
    QuoteSourceUnavailable,
    SignedQuote,
    SwapQuoteGuard,
    parse_quote_reply,
    quote_source_from_settings,
)

KEY = "0x" + "a1" * 32
OTHER_KEY = "0x" + "b2" * 32
SAFE_T, TOKEN_IN, TOKEN_OUT = "0x" + "22" * 20, "0x" + "55" * 20, "0x" + "66" * 20
VENUE, ADAPTER = "0x" + "77" * 20, "0x" + "88" * 20
NOW = 1_800_000_000


def _policy(signer: str) -> QuotePolicy:
    return QuotePolicy(
        chain_id=31337,
        adapter=ADAPTER,
        safe_t=SAFE_T,
        token_in=TOKEN_IN,
        token_out=TOKEN_OUT,
        signers=(signer,),
        venues=(VENUE,),
        max_ttl_seconds=600,
    )


def _step(kind: str = "SWAP", venue: str | None = SIGNED_QUOTE_VENUE) -> Any:
    step_id = "0x" + "ab" * 32
    plan: dict[str, Any] = {"steps": [{"stepId": step_id, "amount": 100}]}
    if venue:
        plan["swaps"] = {step_id: {"minOut": 190, "venue": venue}}
    return SimpleNamespace(kind=kind, sign_request={"plan": plan, "stepSeq": 0})


def _source(key: str = KEY, **kw: Any) -> FakeQuoteSource:
    return FakeQuoteSource(
        key,
        VENUE,
        lambda request: b"route:" + str(request.amount_in).encode(),
        now=lambda: NOW,
        **kw,
    )


class Stager:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, bytes]] = []
        self.fail = fail

    async def __call__(self, to: str, data: bytes) -> None:
        if self.fail:
            raise RuntimeError("reverted")
        self.calls.append((to, data))


def _guard(source: Any, stager: Stager, *, now: int = NOW) -> SwapQuoteGuard:
    return SwapQuoteGuard(source, _policy(Account.from_key(KEY).address), stager, now=lambda: now)


def test_a_valid_quote_is_verified_and_staged_on_the_adapter() -> None:
    stager = Stager()
    asyncio.run(_guard(_source(), stager)(_step()))
    ((to, data),) = stager.calls
    assert to == ADAPTER and len(data) > 4


def test_other_steps_and_the_test_router_are_left_alone() -> None:
    stager = Stager()
    for step in (_step("PAY", None), _step("SWAP", "TEST_ROUTER")):
        asyncio.run(_guard(_source(), stager)(step))
    assert stager.calls == []


def test_forged_quote_stops_before_staging() -> None:
    stager = Stager()
    with pytest.raises(QuoteRejected) as raised:
        asyncio.run(_guard(_source(OTHER_KEY), stager)(_step()))
    assert raised.value.code == "SWAP_QUOTE_FORGED" and stager.calls == []


def test_stale_quote_stops_before_staging() -> None:
    stager = Stager()
    stale = _source(ttl_seconds=-1)  # already expired when it is handed over
    with pytest.raises(QuoteRejected) as raised:
        asyncio.run(_guard(stale, stager)(_step()))
    assert raised.value.code == "SWAP_QUOTE_EXPIRED" and stager.calls == []


def test_a_quote_that_ages_out_before_verification_stops() -> None:
    stager = Stager()
    with pytest.raises(QuoteRejected) as raised:
        asyncio.run(_guard(_source(), stager, now=NOW + 301)(_step()))
    assert raised.value.code == "SWAP_QUOTE_EXPIRED"


def test_quote_below_the_plan_floor_stops() -> None:
    stager = Stager()
    weak = _source()
    # FakeQuoteSource honours the requested floor, so tamper with the request it receives.
    real_fetch = weak.fetch

    async def undercut(request: QuoteRequest) -> SignedQuote:
        return await real_fetch(QuoteRequest(**{**request.__dict__, "min_out": 1}))

    weak.fetch = undercut  # type: ignore[method-assign]
    with pytest.raises(QuoteRejected) as raised:
        asyncio.run(_guard(weak, stager)(_step()))
    assert raised.value.code == "SWAP_QUOTE_BELOW_PLAN_MIN_OUT" and stager.calls == []


def test_unavailable_source_and_failed_staging_stop_the_plan() -> None:
    class Down:
        async def fetch(self, request: QuoteRequest) -> SignedQuote:
            raise QuoteSourceUnavailable("HTTP_503")

    with pytest.raises(QuoteRejected) as raised:
        asyncio.run(_guard(Down(), Stager())(_step()))
    assert raised.value.code == "SWAP_QUOTE_UNAVAILABLE"
    with pytest.raises(QuoteRejected) as raised:
        asyncio.run(_guard(_source(), Stager(fail=True))(_step()))
    assert raised.value.code == "SWAP_QUOTE_STAGING_FAILED"


def test_fake_source_is_deterministic_and_nonces_never_repeat() -> None:
    request = QuoteRequest(31337, ADAPTER, SAFE_T, TOKEN_IN, TOKEN_OUT, 100, 190)
    first = asyncio.run(_source().fetch(request))
    again = asyncio.run(_source().fetch(request))
    assert first == again  # same key, clock and counter: identical quote and signature
    source = _source()
    one, two = asyncio.run(source.fetch(request)), asyncio.run(source.fetch(request))
    assert one.quote.nonce != two.quote.nonce
    assert first.quote.route_hash == route_hash(first.route)
    assert first.quote.min_amount_out == 190 and first.quote.amount_in == 100


def test_http_reply_parsing_rejects_malformed_bodies() -> None:
    request = QuoteRequest(31337, ADAPTER, SAFE_T, TOKEN_IN, TOKEN_OUT, 100, 190)
    fetched = asyncio.run(_source().fetch(request))
    q = fetched.quote
    body = {
        "quote": {
            "taker": q.taker,
            "recipient": q.recipient,
            "tokenIn": q.token_in,
            "tokenOut": q.token_out,
            "amountIn": str(q.amount_in),
            "minAmountOut": str(q.min_amount_out),
            "venue": q.venue,
            "routeHash": q.route_hash,
            "expiry": str(q.expiry),
            "nonce": str(q.nonce),
        },
        "route": "0x" + fetched.route.hex(),
        "signature": "0x" + fetched.signature.hex(),
    }
    assert parse_quote_reply(body) == fetched
    for bad in ({}, {**body, "signature": "zz"}, {**body, "quote": {"taker": "x"}}, None):
        with pytest.raises(QuoteSourceUnavailable):
            parse_quote_reply(bad)


def test_http_source_sends_the_key_only_from_configuration() -> None:
    assert HttpQuoteSource("https://quotes.example/q", "k")._headers == {
        "Authorization": "Bearer k"
    }
    assert HttpQuoteSource("https://quotes.example/q")._headers == {}


def test_source_is_built_from_settings_and_absent_without_a_url() -> None:
    from treasurypilot_worker.config import Settings

    assert quote_source_from_settings(Settings()) is None
    configured = Settings(swap_quote_url="https://quotes.example/q", swap_quote_api_key="k-123456")
    source = quote_source_from_settings(configured)
    assert isinstance(source, HttpQuoteSource)
    assert source._headers == {"Authorization": "Bearer k-123456"}
    assert "k-123456" not in repr(configured)
