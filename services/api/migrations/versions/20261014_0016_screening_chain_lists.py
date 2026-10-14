"""scope screenings by chain and store fixture screening lists

The seeded screening_lists rows are TEST DATA (incl. OFAC sample addresses) and are
inserted in every environment. Production uses UnconfiguredScreeningProvider, so they
are inert, but production must delete them before any real list reader uses this table.

Revision ID: 20261014_0016
Revises: 20261014_0015
Create Date: 2026-10-13 00:00:00

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0016"
down_revision: str | None = "20261014_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# TEST DATA only (compliance §4/§7). The public-list samples are static addresses from
# the OFAC 2026-03-12 SDN-list update; this is not a live or legally sufficient check.
_FIXTURE_ENTRIES = (
    (
        "cb74874f1e06fcf80a306e06e5379a44b488ba2d",
        "TEST DATA — OFAC SDN action 2026-03-12",
        "ofac-sample",
    ),
    (
        "0330070fd38ec3bb94f58fa55d40368271e9e54a",
        "TEST DATA — OFAC SDN action 2026-03-12",
        "ofac-sample",
    ),
    ("000000000000000000000000000000000000dead", "TEST DATA — TreasuryPilot fixture", "team-test"),
)


def upgrade() -> None:
    # A screening answers for one address on one chain from one provider; rows from
    # before this column existed (NULL) are never reused by the cache.
    op.drop_constraint("ck_screenings_ttl", "screenings", type_="check")
    op.alter_column("screenings", "ttl_until", nullable=True)
    op.create_check_constraint(
        "ck_screenings_ttl", "screenings", "ttl_until IS NULL OR ttl_until > checked_at"
    )
    op.add_column("screenings", sa.Column("chain_id", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_screenings_chain_id", "screenings", "chain_id IS NULL OR chain_id > 0"
    )
    op.create_index(
        "ix_screenings_lookup",
        "screenings",
        ["org_id", "address", "chain_id", "provider", sa.text("checked_at DESC")],
    )

    op.create_table(
        "screening_lists",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("source_label", sa.String(length=300), nullable=False),
        sa.Column("list_name", sa.String(length=120), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("octet_length(address) = 20", name="ck_screening_lists_address"),
        sa.CheckConstraint(
            "length(btrim(source_label)) > 0", name="ck_screening_lists_source_label"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address", "list_name", name="uq_screening_lists_address_list"),
    )
    # Plain SQL so offline (--sql) generation can render the byte addresses.
    for address, label, list_name in _FIXTURE_ENTRIES:
        op.execute(
            "INSERT INTO screening_lists (id, address, source_label, list_name) VALUES "
            f"('{uuid.uuid4()}', decode('{address}', 'hex'), '{label}', '{list_name}')"
        )


def downgrade() -> None:
    op.drop_table("screening_lists")
    op.drop_index("ix_screenings_lookup", table_name="screenings")
    op.drop_constraint("ck_screenings_chain_id", "screenings", type_="check")
    op.drop_column("screenings", "chain_id")
    op.drop_constraint("ck_screenings_ttl", "screenings", type_="check")
    op.execute(
        "UPDATE screenings SET ttl_until = checked_at + interval '24 hours' WHERE ttl_until IS NULL"
    )
    op.alter_column("screenings", "ttl_until", nullable=False)
    op.create_check_constraint("ck_screenings_ttl", "screenings", "ttl_until > checked_at")
