from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest

from treasurypilot_api.recovery.review_queue import ReviewType
from treasurypilot_core.policy import PolicyReasonCode
from treasurypilot_worker.chain.rpc import RpcClient, RpcProvider, RpcResponseError, RpcUnavailable
from treasurypilot_worker.recovery.retry import (
    OperationIds,
    Remedy,
    ReviewIntent,
    Stop,
    backoff_seconds,
    classify,
    run_with_retry,
)

IDS = OperationIds("req-1", "step-1", "op-1", "key-1")


def _http_error(status: int) -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(None, (), status=status)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "error",
    [
        RpcUnavailable("all providers failed"),
        _http_error(503),
        TimeoutError(),
        ConnectionResetError(),
        json.JSONDecodeError("bad", "", 0),
    ],
)
def test_transient_errors_are_retryable(error: BaseException) -> None:
    assert classify(error) == classify(RpcUnavailable("x"))
    assert classify(error).retryable


def test_nonce_and_fee_errors_are_retryable_with_a_remedy() -> None:
    assert classify(RpcResponseError(-32000, "Nonce too low")).remedy is Remedy.RESYNC_NONCE
    assert (
        classify(RpcResponseError(-32000, "replacement transaction underpriced")).remedy
        is Remedy.BUMP_FEE
    )


@pytest.mark.parametrize(
    ("error", "kind", "code"),
    [
        (PolicyReasonCode.PAYLOAD_MISMATCH, "AI_REJECTED", "PAYLOAD_MISMATCH"),
        (PolicyReasonCode.ATTESTATION_EXPIRED, "POLICY_BLOCK", "ATTESTATION_EXPIRED"),
        (PolicyReasonCode.SIMULATION_REVERTED, "POLICY_BLOCK", "SIMULATION_REVERTED"),
        (RpcResponseError(3, "execution reverted"), "POLICY_BLOCK", "SIMULATION_REVERTED"),
        (RpcResponseError(-32000, "insufficient funds for gas"), "INFRA", "INSUFFICIENT_GAS"),
        (_http_error(400), "INFRA", "UNCLASSIFIED_ERROR"),
        (ValueError("boom"), "INFRA", "UNCLASSIFIED_ERROR"),
    ],
)
def test_everything_else_is_terminal(
    error: BaseException | PolicyReasonCode, kind: str, code: str
) -> None:
    result = classify(error)
    assert not result.retryable
    assert result.review == ReviewIntent(kind, code)  # type: ignore[arg-type]
    assert ReviewType(kind)


def test_nothing_is_retried_after_broadcast() -> None:
    result = classify(RpcUnavailable("x"), broadcast=True)
    assert result.review == ReviewIntent("UNCERTAIN_TX", "TX_UNKNOWN")


def test_backoff_doubles_from_two_seconds() -> None:
    assert [backoff_seconds(n) for n in range(1, 7)] == [2, 4, 8, 16, 32, 64]


class _Flaky:
    def __init__(self, errors: list[BaseException]) -> None:
        self.errors = errors
        self.calls: list[tuple[OperationIds, int, Remedy]] = []

    async def __call__(self, ids: OperationIds, attempt: int, remedy: Remedy) -> str:
        self.calls.append((ids, attempt, remedy))
        if self.errors:
            raise self.errors.pop(0)
        return "sent"


def _run(send: _Flaky, delays: list[float], **kwargs: int) -> object:
    async def sleep(seconds: float) -> None:
        delays.append(seconds)

    return asyncio.run(run_with_retry(send, IDS, sleep=sleep, **kwargs))


def test_a_503_is_retried_and_succeeds_with_identical_ids() -> None:
    send, delays = _Flaky([_http_error(503), RpcUnavailable("x")]), []
    assert _run(send, delays) == "sent"
    assert delays == [2, 4]
    assert [call[1] for call in send.calls] == [1, 2, 3]
    assert all(call[0] is IDS for call in send.calls)


def test_remedy_is_passed_to_the_next_attempt() -> None:
    send = _Flaky([RpcResponseError(-32000, "nonce too low")])
    assert _run(send, []) == "sent"
    assert send.calls[1][2] is Remedy.RESYNC_NONCE


def test_max_attempts_exhausted_asks_for_an_infra_review() -> None:
    send, delays = _Flaky([TimeoutError()] * 10), []
    assert _run(send, delays) == Stop(ReviewIntent("INFRA", "RETRY_EXHAUSTED"), 6)
    assert len(send.calls) == 6
    assert delays == [2, 4, 8, 16, 32]
    assert {call[0] for call in send.calls} == {IDS}


def test_terminal_error_stops_on_first_attempt() -> None:
    send, delays = _Flaky([RpcResponseError(3, "execution reverted")]), []
    assert _run(send, delays) == Stop(ReviewIntent("POLICY_BLOCK", "SIMULATION_REVERTED"), 1)
    assert delays == []


def test_retries_a_real_rpc_client_that_is_down_then_recovers() -> None:
    class Provider:
        failures = 3

        async def make_request(self, method: str, params: object) -> dict[str, object]:
            if self.failures:
                self.failures -= 1
                raise _http_error(503)
            return {"jsonrpc": "2.0", "id": 1, "result": "0x10"}

    rpc = RpcClient([RpcProvider("p", Provider())])

    async def send(ids: OperationIds, attempt: int, remedy: Remedy) -> object:
        return await rpc.call("eth_blockNumber", [])

    async def no_sleep(seconds: float) -> None: ...

    assert asyncio.run(run_with_retry(send, IDS, sleep=no_sleep)) == "0x10"
