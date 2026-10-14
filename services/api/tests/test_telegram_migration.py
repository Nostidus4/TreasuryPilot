from __future__ import annotations

import io
from pathlib import Path

from alembic import command
from alembic.config import Config

API_ROOT = Path(__file__).parents[1]


def test_telegram_upgrade_and_downgrade_compile_offline() -> None:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://offline/offline")
    output = io.StringIO()
    config.output_buffer = output

    command.upgrade(config, "head", sql=True)
    command.downgrade(config, "head:base", sql=True)

    sql = output.getvalue()
    assert "CREATE TABLE notification_channels" in sql
    assert "CREATE TABLE telegram_link_codes" in sql
    assert "CREATE TABLE telegram_deliveries" in sql
    assert "uq_notification_channels_target" in sql
    assert "uq_telegram_deliveries_pair" in sql
    assert "DROP TABLE telegram_deliveries" in sql
    assert "DROP TABLE notification_channels" in sql
