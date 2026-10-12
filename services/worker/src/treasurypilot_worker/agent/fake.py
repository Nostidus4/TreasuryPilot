"""Scripted provider and clock for tests of the adapter and of every AI task built on it."""

from collections import deque
from collections.abc import Callable, Iterable

from treasurypilot_worker.agent.errors import AiError
from treasurypilot_worker.agent.types import (
    ProviderRequest,
    ProviderResponse,
    StopReason,
    ToolCall,
    Usage,
)

_DEFAULT_USAGE = Usage(10, 10)

FakeStep = ProviderResponse | AiError | Callable[[ProviderRequest, float], ProviderResponse]


class FakeProvider:
    """Replays scripted steps in order and records every request with its timeout."""

    def __init__(self, steps: Iterable[FakeStep]) -> None:
        self._steps = deque(steps)
        self.calls: list[tuple[ProviderRequest, float]] = []

    def complete(self, request: ProviderRequest, *, timeout_s: float) -> ProviderResponse:
        self.calls.append((request, timeout_s))
        if not self._steps:
            raise AssertionError("FakeProvider has no scripted response left")
        step = self._steps.popleft()
        if isinstance(step, AiError):
            raise step
        if isinstance(step, ProviderResponse):
            return step
        return step(request, timeout_s)


def fake_text(text: str, usage: Usage = _DEFAULT_USAGE) -> ProviderResponse:
    return ProviderResponse(
        stop_reason=StopReason.END_TURN,
        text=text,
        usage=usage,
    )


def fake_tool_use(*calls: ToolCall, usage: Usage = _DEFAULT_USAGE) -> ProviderResponse:
    return ProviderResponse(
        stop_reason=StopReason.TOOL_USE,
        tool_calls=calls,
        usage=usage,
    )


class FakeClock:
    """Monotonic clock that only moves when a test, `sleep` or a fake provider advances it."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
