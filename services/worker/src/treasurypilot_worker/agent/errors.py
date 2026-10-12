"""Typed failures of the LLM adapter. Callers map every one of them to a fallback."""


class AiError(Exception):
    """Base class for every adapter failure."""


class AiTimeout(AiError):
    """The task's wall-clock deadline passed before a valid answer arrived."""


class AiUnavailable(AiError):
    """The provider failed (network, rate limit, server error, bad request)."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class AiSchemaError(AiError):
    """The model output could not be validated against the task schema."""


class AiBudgetExceeded(AiError):
    """The organisation's monthly AI budget is spent."""


class AiToolLimitExceeded(AiError):
    """The model asked for more tool calls than the task allows."""
