"""Validator output models (M08 §4.1). Aggregation itself (`decide`, §8.2) is POL-003."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from treasurypilot_core.domain.models import FrozenModel, NonNegativeInt
from treasurypilot_core.policy.reason_codes import ReasonCode, is_warning, precedence


class Check(FrozenModel):
    name: str
    passed: bool
    code: ReasonCode | None
    expected: str | None
    observed: str | None


class Decision(FrozenModel):
    decision: Literal["ALLOW", "NEEDS_APPROVAL", "BLOCK"]
    primary: ReasonCode | None
    codes: list[ReasonCode]
    warnings: list[ReasonCode]
    checks: list[Check]
    stage: Literal["PLAN", "PRE_STEP", "SIMULATION"]
    step_seq: NonNegativeInt | None
    policy_version: Annotated[bytes, Field(min_length=32, max_length=32)]
    snapshot_block: NonNegativeInt

    @model_validator(mode="after")
    def validate_codes(self) -> Decision:
        if any(is_warning(code) for code in self.codes):
            raise ValueError("codes must not contain warning codes")
        if not all(is_warning(code) for code in self.warnings):
            raise ValueError("warnings must contain only warning codes")
        expected = min(self.codes, key=precedence) if self.codes else None
        if self.primary != expected:
            raise ValueError("primary must be the failing code with the highest precedence")
        return self
