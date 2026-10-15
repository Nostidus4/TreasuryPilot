from __future__ import annotations

import io
from pathlib import Path

from alembic import command
from alembic.config import Config

API_ROOT = Path(__file__).parents[1]


def test_fee_policy_runtime_migration_compiles_upgrade_and_downgrade() -> None:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://offline/offline")
    output = io.StringIO()
    config.output_buffer = output

    command.upgrade(config, "head", sql=True)
    command.downgrade(config, "head:base", sql=True)

    sql = output.getvalue()
    assert "avg_plan_fee_7d_wei" in sql
    assert "p90_plan_fee_7d_wei" in sql
    assert "plans_per_day_7d" in sql
    assert "uq_treasury_fee_policies_pending" in sql
    assert "uq_fee_acceptances_plan" in sql
    assert "fee_estimate_wei" in sql
