"""add circuit-breaker rule overrides and trip events

Revision ID: 20261015_0071
Revises: 20261015_0067
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0071"
down_revision: str | None = "20261015_0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RULES = "'REJECTIONS', 'AI_PLAN_REJECTED', 'COVERAGE_DROP', 'DISCREPANCY', 'UNEXPECTED_OUTFLOW'"


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "circuit_rules",
        sa.Column("id", uuid, nullable=False),
        sa.Column("org_id", uuid, nullable=False),
        sa.Column("treasury_id", uuid, nullable=False),
        sa.Column("rule", sa.String(32), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        # Evaluator memory, e.g. the last coverage seen by COVERAGE_DROP.
        sa.Column(
            "state", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("updated_by", uuid, nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"rule IN ({_RULES})", name="ck_circuit_rules_rule"),
        # Tighten-only floors/ceilings; there is deliberately no enabled flag (PAUSE rules stay on).
        sa.CheckConstraint(
            "threshold >= 1 AND (rule NOT IN ('REJECTIONS', 'UNEXPECTED_OUTFLOW') "
            "OR threshold <= CASE rule WHEN 'REJECTIONS' THEN 3 ELSE 20 END)",
            name="ck_circuit_rules_threshold",
        ),
        sa.CheckConstraint(
            "rule <> 'REJECTIONS' OR window_seconds BETWEEN 600 AND 86400",
            name="ck_circuit_rules_window",
        ),
        # Non-tunable rules keep their defaults (keep in sync with py-core circuit.SPECS).
        sa.CheckConstraint(
            "rule IN ('REJECTIONS', 'UNEXPECTED_OUTFLOW') OR (threshold = 1 AND window_seconds = "
            "CASE rule WHEN 'AI_PLAN_REJECTED' THEN 600 ELSE 0 END)",
            name="ck_circuit_rules_fixed",
        ),
        sa.CheckConstraint(
            "rule <> 'UNEXPECTED_OUTFLOW' OR window_seconds = 0", name="ck_circuit_rules_outflow"
        ),
        sa.CheckConstraint("jsonb_typeof(state) = 'object'", name="ck_circuit_rules_state"),
        sa.ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_circuit_rules_treasury_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("treasury_id", "rule", name="uq_circuit_rules_treasury_rule"),
    )
    op.create_table(
        "circuit_events",
        sa.Column("id", uuid, nullable=False),
        sa.Column("org_id", uuid, nullable=False),
        sa.Column("treasury_id", uuid, nullable=False),
        sa.Column("rule", sa.String(32), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        # Idempotency: a signal id, or rule + evaluation bucket for windowed rules.
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"rule IN ({_RULES})", name="ck_circuit_events_rule"),
        sa.CheckConstraint("action IN ('ALERT', 'PAUSE')", name="ck_circuit_events_action"),
        sa.CheckConstraint("jsonb_typeof(details) = 'object'", name="ck_circuit_events_details"),
        sa.ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_circuit_events_treasury_org",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("treasury_id", "dedupe_key", name="uq_circuit_events_dedupe"),
    )
    op.create_index(
        "ix_circuit_events_treasury_rule_at",
        "circuit_events",
        ["treasury_id", "rule", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("circuit_events")
    op.drop_table("circuit_rules")
