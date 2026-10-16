"""The planner's per-step gas budget must cover what the signer will check per step.

The signer refuses a step when ``ceil(estimateGas * 1.2) * maxFeePerGas`` exceeds the plan's fee
cap, and the cap defaults to the plan's own estimate (`plan_fees`). The estimate is a sum over
steps, so every single step must already fit in even a one-step plan's estimate.
"""

from treasurypilot_core.domain.fee_policy import estimate_plan_fee_wei
from treasurypilot_worker.planner.wiring import SIGNER_GAS_MARGIN_PERCENT, STEP_GAS

# Gas of the heaviest step (a REFILL or PAY through executor, module and Safe) measured on Anvil
# is below this; keep it conservative so a contract change shows up here first.
REAL_STEP_GAS = 300_000


def _signer_gas_limit(estimate: int) -> int:
    return max(estimate, (estimate * SIGNER_GAS_MARGIN_PERCENT + 99) // 100)


def test_a_one_step_plan_estimate_covers_the_signers_check_for_a_real_step() -> None:
    max_fee = 2_010_000_000  # about 2 gwei: eth_gasPrice on Anvil times the 2x NORMAL multiplier
    cap = estimate_plan_fee_wei([STEP_GAS], [max_fee])

    assert _signer_gas_limit(REAL_STEP_GAS) * max_fee <= cap


def test_a_two_step_plan_estimate_covers_each_step() -> None:
    max_fee = 2_010_000_000
    cap = estimate_plan_fee_wei([STEP_GAS] * 2, [max_fee] * 2)

    assert _signer_gas_limit(REAL_STEP_GAS) * max_fee <= cap
