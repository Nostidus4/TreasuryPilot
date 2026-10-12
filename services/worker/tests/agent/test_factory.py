from pathlib import Path

import pytest

from treasurypilot_worker.agent import AiTask
from treasurypilot_worker.agent.factory import build_ai_adapter
from treasurypilot_worker.config import Settings

CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "ai.yaml"


def test_config_path_comes_from_tp_ai_config_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_AI_CONFIG_PATH", str(CONFIG_PATH))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    adapter = build_ai_adapter(Settings())

    assert adapter.config.tasks[AiTask.PLAN].model == "claude-opus-5-5"
