"""Retry policy and error classification (RCV-005, M12 §8.2).

Seam for the executor (#61): wrap each pre-broadcast step in ``run_with_retry``. It hands the
callable the *same* frozen ``OperationIds`` on every attempt (BR-061), applies the §8.2 backoff
and returns either the result or a ``Stop`` whose ``review`` the executor persists through
``treasurypilot_api.recovery.review_queue.create_for_outcome`` (the worker cannot import the api).
Anything after broadcast is never retried: the tracker/Unknown path owns it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

import aiohttp

from treasurypilot_core.policy import PolicyReasonCode
from treasurypilot_worker.chain.rpc import TRANSPORT_ERRORS, RpcResponseError, RpcUnavailable

MAX_ATTEMPTS: Final = 6
BASE_DELAY_SECONDS: Final = 2.0

# Values of treasurypilot_api.recovery.review_queue.ReviewType (checked in the tests).
ReviewKind = Literal["POLICY_BLOCK", "AI_REJECTED", "INFRA", "UNCERTAIN_TX", "DISCREPANCY"]


class Remedy(StrEnum):
    NONE = "NONE"
    RESYNC_NONCE = "RESYNC_NONCE"  # signer resyncs the nonce; same payload
    BUMP_FEE = "BUMP_FEE"  # re-price per fee policy; same payload and ids


@dataclass(frozen=True, slots=True)
class ReviewIntent:
    kind: ReviewKind
    primary_code: str
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Classification:
    """``review`` is None exactly when the error is retryable."""

    remedy: Remedy = Remedy.NONE
    review: ReviewIntent | None = None

    @property
    def retryable(self) -> bool:
        return self.review is None


@dataclass(frozen=True, slots=True)
class OperationIds:
    """Durable identity of one step; frozen so a retry cannot mint new ids."""

    request_id: str
    step_id: str
    operation_id: str
    idempotency_key: str


class BroadcastSent(Exception):
    """Raised by ``send`` (``raise BroadcastSent from err``) once the tx may have reached the network."""


@dataclass(frozen=True, slots=True)
class Stop:
    review: ReviewIntent
    attempts: int


_TERMINAL_CODES: Final[dict[PolicyReasonCode, ReviewKind]] = {
    PolicyReasonCode.PAYLOAD_MISMATCH: "AI_REJECTED",
    PolicyReasonCode.ATTESTATION_INVALID: "POLICY_BLOCK",
    PolicyReasonCode.ATTESTATION_EXPIRED: "POLICY_BLOCK",
    PolicyReasonCode.SIMULATION_REVERTED: "POLICY_BLOCK",
}
_RETRYABLE = Classification()
_RESYNC = Classification(Remedy.RESYNC_NONCE)
_BUMP = Classification(Remedy.BUMP_FEE)
_NOT_RETRIED = Classification(review=ReviewIntent("UNCERTAIN_TX", "TX_UNKNOWN"))
_INSUFFICIENT_GAS = Classification(review=ReviewIntent("INFRA", "INSUFFICIENT_GAS"))
_UNCLASSIFIED = Classification(review=ReviewIntent("INFRA", "UNCLASSIFIED_ERROR"))


def classify(error: BaseException | PolicyReasonCode, *, broadcast: bool = False) -> Classification:
    """Map an error to retry-or-stop; unknown errors stop (fail closed).

    After broadcast every outcome is UNCERTAIN_TX: the tx may be on chain, so no INFRA retry.
    """

    if broadcast:
        return _NOT_RETRIED
    if isinstance(error, PolicyReasonCode):
        kind = _TERMINAL_CODES.get(error)
        return Classification(review=ReviewIntent(kind, error.value)) if kind else _UNCLASSIFIED
    return _classify_error(error)


def _classify_error(error: BaseException) -> Classification:
    if isinstance(error, RpcResponseError):
        message = str(error).lower()
        if "nonce too low" in message:
            return _RESYNC
        if "underpriced" in message:
            return _BUMP
        if "insufficient funds" in message:
            return _INSUFFICIENT_GAS
        if "revert" in message:
            return classify(PolicyReasonCode.SIMULATION_REVERTED)
        return _UNCLASSIFIED
    if isinstance(error, aiohttp.ClientResponseError):
        return _RETRYABLE if error.status >= 500 else _UNCLASSIFIED
    if isinstance(error, (RpcUnavailable, *TRANSPORT_ERRORS)):
        return _RETRYABLE
    return _UNCLASSIFIED


def backoff_seconds(attempt: int) -> float:
    """Delay after failed attempt ``attempt`` (1-based): 2 s x 2^n, i.e. 2, 4, 8, ..."""

    return float(BASE_DELAY_SECONDS * 2 ** (attempt - 1))


async def run_with_retry[T](
    send: Callable[[OperationIds, int, Remedy], Awaitable[T]],
    ids: OperationIds,
    *,
    max_attempts: int = MAX_ATTEMPTS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T | Stop:
    """Call ``send(ids, attempt, remedy)`` until it succeeds or the policy says stop.

    ``remedy`` is what the previous failure asked for (nonce resync, fee bump). ``send`` raises
    ``BroadcastSent`` once the tx may be on the network; that stops the loop (never re-send).
    """

    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    remedy = Remedy.NONE
    for attempt in range(1, max_attempts + 1):
        try:
            return await send(ids, attempt, remedy)
        except BroadcastSent as error:
            return Stop(classify(error, broadcast=True).review, attempt)  # type: ignore[arg-type]
        except Exception as error:  # classified below; unknown errors stop, never propagate
            outcome = classify(error)
        if outcome.review is not None:
            return Stop(outcome.review, attempt)
        remedy = outcome.remedy
        if attempt < max_attempts:
            await sleep(backoff_seconds(attempt))
    return Stop(ReviewIntent("INFRA", "RETRY_EXHAUSTED"), max_attempts)
