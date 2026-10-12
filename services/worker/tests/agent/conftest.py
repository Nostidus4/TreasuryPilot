from datetime import UTC, datetime
from pathlib import Path

import pytest

from treasurypilot_worker.agent import AiConfig, FakeClock, load_ai_config

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def repo_config() -> AiConfig:
    return load_ai_config(REPO_ROOT / "config" / "ai.yaml")


@pytest.fixture
def october() -> datetime:
    return datetime(2026, 10, 11, 9, 30, tzinfo=UTC)
