"""Ordered provider failover behind the single `Provider` seam (AGT-017, FR-808)."""

import logging
import time
from collections.abc import Callable, Sequence

from treasurypilot_worker.agent.errors import AiTimeout, AiUnavailable
from treasurypilot_worker.agent.types import Provider, ProviderRequest, ProviderResponse

logger = logging.getLogger(__name__)


class FailoverProvider:
    """Sends each turn to the first provider; on `AiUnavailable` the same turn goes to the next.

    When every provider fails, the last error is raised, marked retryable if any provider's
    failure was, so a broken secondary never stops the adapter retrying a flaky primary.
    All providers share the one timeout the adapter passes in.
    shortcut: a primary that hangs uses the whole deadline and never fails over; add a
    per-provider time share or a circuit breaker if hanging outages show up.
    """

    def __init__(
        self, providers: Sequence[Provider], *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if not providers:
            raise ValueError("FailoverProvider needs at least one provider")
        self._providers = tuple(providers)
        self._clock = clock

    def complete(self, request: ProviderRequest, *, timeout_s: float) -> ProviderResponse:
        deadline = self._clock() + timeout_s
        last = len(self._providers) - 1
        retryable = False
        for index, provider in enumerate(self._providers):
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise AiTimeout("deadline passed before the next provider could be tried")
            try:
                return provider.complete(request, timeout_s=remaining)
            except AiUnavailable as error:
                retryable = retryable or error.retryable
                if index == last:
                    error.retryable = retryable
                    raise
                logger.warning("AI provider %d unavailable, failing over: %s", index, error)
        raise AssertionError("unreachable")
