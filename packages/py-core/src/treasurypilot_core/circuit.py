"""Circuit-breaker rule defaults and the tighten-only bounds (RCV-006, BR-065, M12 §8.4).

Every rule PAUSEs (the outflow rule ALERTs and PAUSEs above its percentage). There is no
enable flag on purpose: an Owner can only move a threshold towards "trips sooner".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

COOLDOWN_SECONDS: Final = 30 * 60


class CircuitRule(StrEnum):
    REJECTIONS = "REJECTIONS"  # reverts or simulation reverts: threshold count in window
    AI_PLAN_REJECTED = "AI_PLAN_REJECTED"
    COVERAGE_DROP = "COVERAGE_DROP"
    DISCREPANCY = "DISCREPANCY"
    UNEXPECTED_OUTFLOW = "UNEXPECTED_OUTFLOW"  # threshold = percent of wallet balance


@dataclass(frozen=True, slots=True)
class RuleSpec:
    threshold: int
    window_seconds: int
    tunable: bool = False
    # Tightening bounds: the threshold may only go down to 1, the window only up.
    max_window_seconds: int = 86_400


SPECS: Final[dict[CircuitRule, RuleSpec]] = {
    CircuitRule.REJECTIONS: RuleSpec(3, 600, tunable=True),
    CircuitRule.AI_PLAN_REJECTED: RuleSpec(1, 600),
    CircuitRule.COVERAGE_DROP: RuleSpec(1, 0),
    CircuitRule.DISCREPANCY: RuleSpec(1, 0),
    CircuitRule.UNEXPECTED_OUTFLOW: RuleSpec(20, 0, tunable=True),
}


def validate_tightening(rule: CircuitRule, threshold: int, window_seconds: int) -> None:
    spec = SPECS[rule]
    if not spec.tunable:
        raise ValueError(f"{rule.value} cannot be changed in M1")
    if not 1 <= threshold <= spec.threshold:
        raise ValueError(f"threshold must be between 1 and {spec.threshold} (tighten only)")
    if rule is CircuitRule.REJECTIONS:
        if not spec.window_seconds <= window_seconds <= spec.max_window_seconds:
            raise ValueError(
                f"windowSeconds must be between {spec.window_seconds} and "
                f"{spec.max_window_seconds} (tighten only)"
            )
    elif window_seconds != spec.window_seconds:
        raise ValueError(f"{rule.value} has no window")
