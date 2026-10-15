import pytest

from treasurypilot_core.circuit import CircuitRule, validate_tightening


@pytest.mark.parametrize(
    ("rule", "threshold", "window"),
    [
        (CircuitRule.REJECTIONS, 2, 1800),
        (CircuitRule.REJECTIONS, 3, 600),
        (CircuitRule.UNEXPECTED_OUTFLOW, 5, 0),
    ],
)
def test_tightening_is_accepted(rule: CircuitRule, threshold: int, window: int) -> None:
    validate_tightening(rule, threshold, window)


@pytest.mark.parametrize(
    ("rule", "threshold", "window"),
    [
        (CircuitRule.REJECTIONS, 4, 600),  # looser count
        (CircuitRule.REJECTIONS, 3, 300),  # shorter window = looser
        (CircuitRule.REJECTIONS, 0, 600),
        (CircuitRule.UNEXPECTED_OUTFLOW, 21, 0),
        (CircuitRule.UNEXPECTED_OUTFLOW, 10, 60),
        (CircuitRule.DISCREPANCY, 1, 0),  # PAUSE rules cannot be changed or disabled
        (CircuitRule.AI_PLAN_REJECTED, 1, 600),
    ],
)
def test_loosening_or_fixed_rules_are_refused(
    rule: CircuitRule, threshold: int, window: int
) -> None:
    with pytest.raises(ValueError):
        validate_tightening(rule, threshold, window)
