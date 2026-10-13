"""Ordered provider failover behind the single `Provider` seam (AGT-017, FR-808)."""

import logging
import time
from collections.abc import Callable, Sequence

from treasurypilot_worker.agent.errors import AiError, AiTimeout, AiUnavailable
from treasurypilot_worker.agent.types import Provider, ProviderRequest, ProviderResponse

logger = logging.getLogger(__name__)


class FailoverProvider:
    """Sends each turn to the first provider; on a provider-side failure the same turn goes on.

    Provider-side means an `AiUnavailable` with `failover` set, or a timeout of any provider
    but the last. Each provider but the last gets `share` of the remaining deadline, so a hung
    primary still leaves the secondary time. A request error (400, a billed but unusable 200)
    is raised as is: the next provider would reject or bill it the same way.
    A provider that failed over is skipped for `cooldown_s`, so a sustained outage costs one
    round-trip per cooldown instead of one per turn. When every provider fails, the last
    error is raised, retryable if any failure was, so a broken secondary never stops the
    adapter retrying a flaky primary.
    """

    def __init__(
        self,
        providers: Sequence[Provider],
        *,
        share: float = 0.5,
        cooldown_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not providers:
            raise ValueError("FailoverProvider needs at least one provider")
        self._providers = tuple(providers)
        self.name = ",".join(provider.name for provider in self._providers)
        self._share = share
        self._cooldown_s = cooldown_s
        self._clock = clock
        # shortcut: per-process breaker state; a fleet-wide breaker would need Redis.
        self._skip_until = [0.0] * len(self._providers)

    def complete(self, request: ProviderRequest, *, timeout_s: float) -> ProviderResponse:
        deadline = self._clock() + timeout_s
        last = len(self._providers) - 1
        retryable = False
        failure: AiError | None = None
        for index, provider in enumerate(self._providers):
            now = self._clock()
            if index < last and now < self._skip_until[index]:
                continue
            remaining = deadline - now
            if remaining <= 0:
                raise AiTimeout(
                    "deadline passed before the next provider could be tried"
                ) from failure
            try:
                return provider.complete(
                    request, timeout_s=remaining if index == last else remaining * self._share
                )
            except AiTimeout as error:
                if index == last:
                    raise
                failure, retryable = error, True
            except AiUnavailable as error:
                if index == last and failure is not None:
                    raise AiUnavailable(
                        str(error), retryable=retryable or error.retryable, usage=error.usage
                    ) from error
                if index == last or not error.failover:
                    raise
                retryable = retryable or error.retryable
                failure = error
            self._skip_until[index] = self._clock() + self._cooldown_s
            logger.warning("AI provider %s unavailable, failing over: %s", provider.name, failure)
        raise AssertionError("unreachable")
