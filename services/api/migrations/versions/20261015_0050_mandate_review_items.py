"""Allow read-back discrepancies to be reviewed against a mandate version.

Revision ID: 20261015_0050
Revises: 20261015_0049
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0050"
down_revision: str | None = "20261015_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "review_items", "request_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True
    )
    op.alter_column("review_items", "request_version", existing_type=sa.Integer(), nullable=True)
    op.add_column(
        "review_items",
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_review_items_evidence_object",
        "review_items",
        "jsonb_typeof(evidence) = 'object'",
    )
    op.add_column(
        "review_items",
        sa.Column("mandate_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_review_items_mandate_version_org",
        "review_items",
        "mandate_versions",
        ["mandate_version_id", "org_id"],
        ["id", "org_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_review_items_subject",
        "review_items",
        "(request_id IS NOT NULL AND request_version IS NOT NULL "
        "AND mandate_version_id IS NULL) OR "
        "(request_id IS NULL AND request_version IS NULL "
        "AND mandate_version_id IS NOT NULL AND type = 'DISCREPANCY')",
    )
    op.create_index(
        "uq_review_items_open_mandate_type",
        "review_items",
        ["mandate_version_id", "type"],
        unique=True,
        postgresql_where=sa.text("status = 'Open' AND mandate_version_id IS NOT NULL"),
    )


def downgrade() -> None:
    has_mandate_items = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM review_items WHERE mandate_version_id IS NOT NULL)"
            )
        )
        .scalar_one()
    )
    if has_mandate_items:
        raise RuntimeError(
            "Cannot downgrade mandate review support while mandate-linked review items exist; "
            "archive or remove them first."
        )

    op.drop_index("uq_review_items_open_mandate_type", table_name="review_items")
    op.drop_constraint("ck_review_items_subject", "review_items", type_="check")
    op.drop_constraint("fk_review_items_mandate_version_org", "review_items", type_="foreignkey")
    op.drop_column("review_items", "mandate_version_id")
    op.drop_constraint("ck_review_items_evidence_object", "review_items", type_="check")
    op.drop_column("review_items", "evidence")
    op.alter_column("review_items", "request_version", existing_type=sa.Integer(), nullable=False)
    op.alter_column(
        "review_items", "request_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False
    )
