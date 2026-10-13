"""create append-only ai_calls decision log

Revision ID: 20261013_0006
Revises: 20261013_0005
Create Date: 2026-10-13 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_0006"
down_revision: str | None = "20261013_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ai_purpose = postgresql.ENUM(
    "EXTRACT",
    "TERMS",
    "ANOMALY",
    "PLAN",
    "EXPLAIN",
    "EXCEPTION_DRAFT",
    "COPILOT",
    "EVAL",
    name="ai_purpose",
)
ai_validation_result = postgresql.ENUM(
    "OK", "SCHEMA_ERROR", "POSTCHECK_FAILED", "REJECTED", name="ai_validation_result"
)


def upgrade() -> None:
    bind = op.get_bind()
    ai_purpose.create(bind, checkfirst=False)
    ai_validation_result.create(bind, checkfirst=False)

    op.create_table(
        "ai_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", postgresql.ENUM(name="ai_purpose", create_type=False), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("input_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "validation_result",
            postgresql.ENUM(name="ai_validation_result", create_type=False),
            nullable=True,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd_micros", sa.BigInteger(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("latency_ms >= 0", name="ck_ai_calls_latency_ms"),
        sa.CheckConstraint("input_tokens >= 0", name="ck_ai_calls_input_tokens"),
        sa.CheckConstraint("output_tokens >= 0", name="ck_ai_calls_output_tokens"),
        sa.CheckConstraint("cost_usd_micros >= 0", name="ck_ai_calls_cost_usd_micros"),
        sa.CheckConstraint(
            "validation_result IS NOT NULL OR error IS NOT NULL", name="ck_ai_calls_outcome"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_calls_org_created", "ai_calls", ["org_id", sa.text("created_at DESC")])
    # Append-only (DATA_MODEL.md): the decision history cannot be edited or removed.
    op.execute(
        """
        CREATE FUNCTION ai_calls_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'ai_calls is append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER ai_calls_append_only
        BEFORE UPDATE OR DELETE OR TRUNCATE ON ai_calls
        FOR EACH STATEMENT EXECUTE FUNCTION ai_calls_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER ai_calls_append_only ON ai_calls")
    op.execute("DROP FUNCTION ai_calls_append_only()")
    op.drop_index("ix_ai_calls_org_created", table_name="ai_calls")
    op.drop_table("ai_calls")

    bind = op.get_bind()
    ai_validation_result.drop(bind, checkfirst=False)
    ai_purpose.drop(bind, checkfirst=False)
