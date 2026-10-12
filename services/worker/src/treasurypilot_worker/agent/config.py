"""`config/ai.yaml`: model, timeout and limits per task, prices and the monthly budget."""

from enum import StrEnum
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator


class AiTask(StrEnum):
    EXTRACT = "EXTRACT"
    TERMS = "TERMS"
    ANOMALY = "ANOMALY"
    PLAN = "PLAN"
    EXPLAIN = "EXPLAIN"
    EXCEPTION_DRAFT = "EXCEPTION_DRAFT"
    COPILOT = "COPILOT"
    EVAL = "EVAL"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PriceTier(_Strict):
    """USD micros per million tokens."""

    input: int = Field(ge=0)
    output: int = Field(ge=0)
    cache_write: int = Field(ge=0)
    cache_read: int = Field(ge=0)


class LongPromptTier(PriceTier):
    """Prices used when the prompt (input + cache tokens) exceeds `threshold_tokens`."""

    threshold_tokens: PositiveInt


class ModelPrice(PriceTier):
    long_prompt: LongPromptTier | None = None


class TaskConfig(_Strict):
    model: str
    timeout_s: float = Field(gt=0)
    max_output_tokens: PositiveInt
    max_tool_calls: int = Field(default=0, ge=0)
    tool_result_max_bytes: PositiveInt = 50_000


class AiConfig(_Strict):
    monthly_budget_usd_micros: int = Field(ge=0)
    prices: dict[str, ModelPrice]
    tasks: dict[AiTask, TaskConfig]

    @model_validator(mode="after")
    def _complete(self) -> Self:
        missing = sorted(set(AiTask) - set(self.tasks))
        if missing:
            raise ValueError(f"tasks missing from AI config: {', '.join(missing)}")
        unpriced = sorted({t.model for t in self.tasks.values()} - set(self.prices))
        if unpriced:
            raise ValueError(f"models without a price: {', '.join(unpriced)}")
        return self


def load_ai_config(path: Path) -> AiConfig:
    with path.open() as f:
        raw = yaml.safe_load(f)
    return AiConfig.model_validate(raw)
