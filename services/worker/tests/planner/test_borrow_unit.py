"""The borrow estimate helper (ENG-014, TRS-009) without a database."""

from __future__ import annotations

from treasurypilot_core.domain import Snapshot
from treasurypilot_core.money import BaseUnits
from treasurypilot_worker.planner.borrow import BORROW_HORIZON_DAYS, estimate_borrow


def _snapshot(**update: object) -> Snapshot:
    from treasurypilot_worker.planner.inputs import engine_snapshot

    data = {
        "balances": {"0xaa": "100"},
        "buffers": {"0xaa": "0"},
        "targets": {"0xaa": "0"},
        "module": {"used_today": {"PAY": "0", "REFILL": "0", "SUPPLY": "0"}},
        "aave": {
            "a_token_balance": "0",
            "available_liquidity": "0",
            "reserve": {
                "liquidity_rate": str(4 * 10**25),
                "variable_borrow_rate": str(6 * 10**25),
            },
        },
    }
    return engine_snapshot(data, "0xaa", [], day=20_000).model_copy(update=update)


def test_the_estimate_repays_after_the_horizon_with_integer_costs() -> None:
    proposal, due_day = estimate_borrow(_snapshot(), BaseUnits(1_000_000))
    assert due_day == 20_000 + BORROW_HORIZON_DAYS
    assert int(proposal.amount) == 1_000_000
    # 1_000_000 x 6 % x 7 / 365 and x 4 % x 7 / 365, rounded down.
    assert int(proposal.cost_to_repayment) == 1_150
    assert int(proposal.withdraw_cost) == 767
    assert proposal.health_factor_after is None  # no debt position in the snapshot
