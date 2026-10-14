"""Typed failures of the LLM adapter. Callers map every one of them to a fallback."""

from treasurypilot_worker.agent.types import Usage


class AiError(Exception):
    """Base class for every adapter failure."""


class AiTimeout(AiError):
    """The task's wall-clock deadline passed before a valid answer arrived."""


class AiUnavailable(AiError):
    """The provider failed (network, rate limit, server error, bad request)."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        failover: bool | None = None,
        usage: Usage | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        # Whether the next provider may take the turn: provider-side failures only, never a
        # request it would reject (or bill) the same way. Defaults to `retryable`.
        self.failover = retryable if failover is None else failover
        # Tokens billed before the failure (a 200 the adapter cannot use); still charged.
        self.usage = usage


class AiSchemaError(AiError):
    """The model output could not be validated against the task schema."""


class AiBudgetExceeded(AiError):
    """The organisation's monthly AI budget is spent."""


class AiToolLimitExceeded(AiError):
    """The model asked for more tool calls than the task allows."""


class AiInputRejected(AiError):
    """An input looked like a secret (FR-804). Only the pattern name and source are kept."""

    def __init__(self, *, pattern: str, source: str) -> None:
        super().__init__(f"input from {source} rejected: matches secret pattern {pattern}")
        self.pattern = pattern
        self.source = source


class PromptTemplateError(ValueError):
    """A prompt template was defined or rendered wrongly. A bug, so not an `AiError`.

    Callers map `AiError` to fallbacks; this one must surface instead.
    """


class ToolError(Exception):
    """A tool refused or could not serve a call. The message goes back to the model.

    It must never carry data the caller may not see (a refusal reads the same for a missing
    row and for another organisation's row).
    """
