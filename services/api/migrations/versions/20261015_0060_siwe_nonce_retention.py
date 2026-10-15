"""Add explicit SIWE nonce retention and hash-only deletion receipts.

Revision ID: 20261015_0060
Revises: 20261015_0059
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_0060"
down_revision: str | None = "20261015_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "auth_retention_policies",
        sa.Column("siwe_nonce_retention_days", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_auth_retention_policies_siwe_nonce_days",
        "auth_retention_policies",
        "siwe_nonce_retention_days IS NULL OR siwe_nonce_retention_days BETWEEN 0 AND 36500",
    )
    # Bound the nonce table by default: closed challenges are swept 30 days after use or
    # expiry unless an operator reconfigures the policy.
    op.execute(
        "INSERT INTO auth_retention_policies (id, siwe_nonce_retention_days) VALUES (1, 30) "
        "ON CONFLICT (id) DO UPDATE SET siwe_nonce_retention_days = 30"
    )
    op.drop_constraint("ck_deletion_receipts_record_type", "deletion_receipts", type_="check")
    op.create_check_constraint(
        "ck_deletion_receipts_record_type",
        "deletion_receipts",
        "record_type IN ('invite', 'session', 'magic_link', 'subject', 'siwe_nonce')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_auth_retention_policies_siwe_nonce_days",
        "auth_retention_policies",
        type_="check",
    )
    op.drop_column("auth_retention_policies", "siwe_nonce_retention_days")
    # Keep the expanded receipt check so a code rollback does not invalidate
    # hash-only receipts already written for SIWE challenges.
