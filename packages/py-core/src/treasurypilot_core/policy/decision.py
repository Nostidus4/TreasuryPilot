"""Validator output models (M08 §4.1). `decide` is POL-003."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from treasurypilot_core.domain.models import FrozenModel, NonNegativeInt
from treasurypilot_core.policy.reason_codes import (
    REASON_CODES,
    PolicyReasonCode,
    is_warning,
    precedence,
)

type Outcome = Literal["ALLOW", "NEEDS_APPROVAL", "BLOCK"]
# Lax so codes rehydrated from the database or JSON as plain strings still validate.
type Code = Annotated[PolicyReasonCode, Field(strict=False)]


def aggregate(codes: Iterable[PolicyReasonCode]) -> tuple[Outcome, PolicyReasonCode | None]:
    """M08 §8.2: the decision and primary code implied by failing codes; warnings are ignored."""

    failing = [code for code in codes if not is_warning(code)]
    defaults = {REASON_CODES[code].default for code in failing}
    outcome: Outcome = "BLOCK" if "BLOCK" in defaults else "NEEDS_APPROVAL" if failing else "ALLOW"
    return outcome, min(failing, key=precedence, default=None)


class Check(FrozenModel):
    name: str
    passed: bool
    code: Code | None
    expected: str | None
    observed: str | None
    skipped: bool = False  # not run because a gate failed or its input is absent (M08 §8.1)

    @model_validator(mode="after")
    def validate_skipped(self) -> Check:
        if self.skipped and (self.passed or self.code is not None):
            raise ValueError("a skipped check neither passes nor carries a code")
        return self


class Decision(FrozenModel):
    model_config = ConfigDict(ser_json_bytes="hex", val_json_bytes="hex")

    decision: Outcome
    primary: Code | None
    codes: list[Code]
    warnings: list[Code]
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
        if (self.decision, self.primary) != aggregate(self.codes):
            raise ValueError("decision and primary must follow from codes (M08 §8.2)")
        failed = {c.code for c in self.checks if not c.passed and not c.skipped}
        if failed != {*self.codes, *self.warnings}:
            raise ValueError("codes and warnings must be exactly the codes of failed checks")
        if (self.stage == "PLAN") != (self.step_seq is None):
            raise ValueError("step_seq is required for PRE_STEP and SIMULATION, absent for PLAN")
        return self
