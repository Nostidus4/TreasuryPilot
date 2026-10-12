from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from treasurypilot_worker.agent import AiConfig, AiTask, load_ai_config


def test_repo_config_covers_every_task_with_spec_defaults(repo_config: AiConfig) -> None:
    assert set(repo_config.tasks) == set(AiTask)
    assert repo_config.tasks[AiTask.PLAN].model == "claude-opus-5-5"
    assert repo_config.tasks[AiTask.PLAN].max_tool_calls == 8
    assert repo_config.tasks[AiTask.COPILOT].max_tool_calls == 6
    assert repo_config.tasks[AiTask.EXPLAIN].model == "claude-haiku-5-5"
    assert repo_config.tasks[AiTask.EXTRACT].timeout_s == 60
    assert repo_config.tasks[AiTask.EVAL].model == "claude-sonnet-5-5"
    assert repo_config.monthly_budget_usd_micros == 20_000_000


def _write(tmp_path: Path, data: dict[str, object]) -> Path:
    path = tmp_path / "ai.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def _raw(repo_config: AiConfig) -> dict[str, object]:
    return repo_config.model_dump(mode="json", exclude_none=True)


def test_switching_a_task_model_is_a_config_change_only(
    tmp_path: Path, repo_config: AiConfig
) -> None:
    raw = _raw(repo_config)
    raw["tasks"]["EXPLAIN"]["model"] = "claude-sonnet-5-5"  # type: ignore[index]

    config = load_ai_config(_write(tmp_path, raw))

    assert config.tasks[AiTask.EXPLAIN].model == "claude-sonnet-5-5"


def test_missing_task_is_rejected(tmp_path: Path, repo_config: AiConfig) -> None:
    raw = _raw(repo_config)
    del raw["tasks"]["EVAL"]  # type: ignore[attr-defined]

    with pytest.raises(ValidationError, match="EVAL"):
        load_ai_config(_write(tmp_path, raw))


def test_model_without_price_is_rejected(tmp_path: Path, repo_config: AiConfig) -> None:
    raw = _raw(repo_config)
    raw["tasks"]["PLAN"]["model"] = "claude-unpriced"  # type: ignore[index]

    with pytest.raises(ValidationError, match="claude-unpriced"):
        load_ai_config(_write(tmp_path, raw))


def test_unknown_fields_are_rejected(tmp_path: Path, repo_config: AiConfig) -> None:
    raw = _raw(repo_config)
    raw["tasks"]["PLAN"]["temperature"] = 0.2  # type: ignore[index]

    with pytest.raises(ValidationError, match="temperature"):
        load_ai_config(_write(tmp_path, raw))
