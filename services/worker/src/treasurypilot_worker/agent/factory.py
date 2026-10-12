"""Wiring of the production adapter for worker-ai."""

import logging
import os
from functools import lru_cache

import anthropic

from treasurypilot_worker.agent.adapter import AiAdapter
from treasurypilot_worker.agent.anthropic_provider import AnthropicProvider
from treasurypilot_worker.agent.budget import InMemoryBudgetLedger
from treasurypilot_worker.agent.config import AiConfig, ProviderConfig, load_ai_config
from treasurypilot_worker.agent.failover import FailoverProvider
from treasurypilot_worker.config import Settings, get_settings

logger = logging.getLogger(__name__)


def build_ai_adapter(settings: Settings) -> AiAdapter:
    config = load_ai_config(settings.ai_config_path)
    # In-memory until the ai_budgets table exists; spend resets when the worker restarts.
    return AiAdapter(
        provider=FailoverProvider(build_providers(config)),
        config=config,
        ledger=InMemoryBudgetLedger(),
    )


def build_providers(config: AiConfig) -> list[AnthropicProvider]:
    """Providers in failover order; one whose credentials are missing is skipped."""

    providers = []
    for entry in config.providers:
        try:
            client = _client(entry)
        except (anthropic.AnthropicError, ValueError) as error:
            # A missing secondary must not take the primary down with it (local dev, CI).
            logger.warning("AI provider %s not configured, skipped: %s", entry.name, error)
            continue
        providers.append(
            AnthropicProvider(client, name=entry.name, model_prefix=entry.model_prefix)
        )
    if not providers:
        raise RuntimeError("no AI provider in the AI config could be configured")
    return providers


def _client(entry: ProviderConfig) -> anthropic.Anthropic | anthropic.AnthropicBedrockMantle:
    # Missing keys must skip the provider here: the SDK would raise TypeError on every call,
    # which is not an AiUnavailable and so would never fail over.
    if entry.name == "anthropic":
        return anthropic.Anthropic(api_key=_required_env("ANTHROPIC_API_KEY"))
    # Bedrock API-key auth only: SigV4 would need botocore, which the worker does not install.
    # The client raises AnthropicError itself when AWS_REGION is unset.
    return anthropic.AnthropicBedrockMantle(api_key=_required_env("AWS_BEARER_TOKEN_BEDROCK"))


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} is not set")
    return value


@lru_cache
def get_ai_adapter() -> AiAdapter:
    """One adapter per worker process, so the budget ledger is shared by its tasks."""

    return build_ai_adapter(get_settings())
