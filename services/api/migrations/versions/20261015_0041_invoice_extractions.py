"""store AI invoice extractions and track extraction status on upload requests

Revision ID: 20261015_0041
Revises: 20261014_0036
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0041"
down_revision: str | None = "20261014_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = "'Extracting', 'Extracted', 'ManualEntry'"


def upgrade() -> None:
    op.add_column("payment_requests", sa.Column("extraction_status", sa.String(16)))
    op.create_check_constraint(
        "ck_payment_requests_extraction_status",
        "payment_requests",
        f"extraction_status IS NULL OR extraction_status IN ({STATUSES})",
    )
    op.create_table(
        "extractions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ai_call_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fields", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("jsonb_typeof(fields) = 'object'", name="ck_extractions_fields_object"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ai_call_id"], ["ai_calls.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("document_id", name="uq_extractions_document"),
    )


def downgrade() -> None:
    op.drop_table("extractions")
    op.drop_constraint("ck_payment_requests_extraction_status", "payment_requests", type_="check")
    op.drop_column("payment_requests", "extraction_status")
