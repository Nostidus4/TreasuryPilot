from __future__ import annotations

import io
from pathlib import Path

from alembic import command
from alembic.config import Config

API_ROOT = Path(__file__).parents[1]


def test_notifications_upgrade_and_downgrade_compile_offline() -> None:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://offline/offline")
    output = io.StringIO()
    config.output_buffer = output

    command.upgrade(config, "head", sql=True)
    command.downgrade(config, "head:base", sql=True)

    sql = output.getvalue()
    assert "CREATE TABLE domain_events" in sql
    assert "CREATE TABLE notifications" in sql
    assert "uq_notifications_user_event" in sql
    assert "fk_notifications_event_org" in sql
    assert "ix_domain_events_pending" in sql
    assert "DROP TABLE notifications" in sql
    assert "DROP TABLE domain_events" in sql
