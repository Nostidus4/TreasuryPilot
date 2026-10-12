from pathlib import Path

import anthropic
import pytest

from treasurypilot_worker.agent import AiConfig, AiTask
from treasurypilot_worker.agent.factory import build_ai_adapter, build_providers
from treasurypilot_worker.config import Settings

CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "ai.yaml"


def test_config_path_comes_from_tp_ai_config_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_AI_CONFIG_PATH", str(CONFIG_PATH))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    adapter = build_ai_adapter(Settings())

    assert adapter.config.tasks[AiTask.PLAN].model == "claude-opus-5-5"


def test_bedrock_secondary_is_skipped_without_its_api_key(
    monkeypatch: pytest.MonkeyPatch, repo_config: AiConfig
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    assert len(build_providers(repo_config)) == 1


def test_primary_without_its_api_key_leaves_bedrock_serving(
    monkeypatch: pytest.MonkeyPatch, repo_config: AiConfig
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-bedrock-key")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    (only,) = build_providers(repo_config)

    assert isinstance(only._client, anthropic.AnthropicBedrockMantle)


def test_bedrock_secondary_follows_the_primary_when_configured(
    monkeypatch: pytest.MonkeyPatch, repo_config: AiConfig
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-bedrock-key")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    primary, secondary = build_providers(repo_config)

    assert isinstance(secondary._client, anthropic.AnthropicBedrockMantle)
    assert secondary._model_prefix == "anthropic."
    assert isinstance(primary._client, anthropic.Anthropic)
