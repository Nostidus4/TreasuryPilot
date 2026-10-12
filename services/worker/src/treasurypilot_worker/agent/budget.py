"""Per-organisation monthly AI spend, in integer USD micros."""

from collections import defaultdict
from typing import Protocol

from treasurypilot_worker.agent.config import ModelPrice, PriceTier
from treasurypilot_worker.agent.types import Usage

_TOKENS_PER_PRICE_UNIT = 1_000_000


class BudgetLedger(Protocol):
    def spent(self, org_id: str, month: str) -> int:
        """USD micros spent by `org_id` in `month` (YYYY-MM)."""
        ...

    def record(self, org_id: str, month: str, cost_usd_micros: int) -> None: ...


class InMemoryBudgetLedger:
    """Process-local ledger for tests and local runs; resets when the worker restarts."""

    def __init__(self) -> None:
        self._spent: defaultdict[tuple[str, str], int] = defaultdict(int)

    def spent(self, org_id: str, month: str) -> int:
        return self._spent[(org_id, month)]

    def record(self, org_id: str, month: str, cost_usd_micros: int) -> None:
        self._spent[(org_id, month)] += cost_usd_micros


def cost_usd_micros(price: ModelPrice, usage: Usage) -> int:
    """Cost of one request, rounded up to the next micro."""

    prompt_tokens = usage.input_tokens + usage.cache_write_tokens + usage.cache_read_tokens
    tier: PriceTier = price
    if price.long_prompt is not None and prompt_tokens > price.long_prompt.threshold_tokens:
        tier = price.long_prompt
    scaled = (
        usage.input_tokens * tier.input
        + usage.output_tokens * tier.output
        + usage.cache_write_tokens * tier.cache_write
        + usage.cache_read_tokens * tier.cache_read
    )
    return -(-scaled // _TOKENS_PER_PRICE_UNIT)
