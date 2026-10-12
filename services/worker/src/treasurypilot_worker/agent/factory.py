"""Wiring of the production adapter for worker-ai."""

from functools import lru_cache

from treasurypilot_worker.agent.adapter import AiAdapter
from treasurypilot_worker.agent.anthropic_provider import AnthropicProvider
from treasurypilot_worker.agent.budget import InMemoryBudgetLedger
from treasurypilot_worker.agent.config import load_ai_config
from treasurypilot_worker.config import Settings, get_settings


def build_ai_adapter(settings: Settings) -> AiAdapter:
    # In-memory until the ai_budgets table exists; spend resets when the worker restarts.
    return AiAdapter(
        provider=AnthropicProvider(),
        config=load_ai_config(settings.ai_config_path),
        ledger=InMemoryBudgetLedger(),
    )


@lru_cache
def get_ai_adapter() -> AiAdapter:
    """One adapter per worker process, so the budget ledger is shared by its tasks."""

    return build_ai_adapter(get_settings())
