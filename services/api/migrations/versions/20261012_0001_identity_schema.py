"""create identity schema

Revision ID: 20261012_0001
Revises:
Create Date: 2026-10-12 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261012_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VALID_ROLES = """
roles <@ ARRAY[
    'OrgAdmin', 'Owner', 'Approver', 'Operator', 'Finance', 'Guardian', 'Auditor',
    'PlatformAdmin'
]::text[]
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("length(email::text) BETWEEN 3 AND 320", name="ck_users_email_length"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ip_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("ua_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("expires_at > created_at", name="ck_sessions_expiry"),
        sa.CheckConstraint("last_seen_at >= created_at", name="ck_sessions_last_seen"),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="ck_sessions_revoked_at"
        ),
        sa.CheckConstraint("octet_length(ip_hash) = 32", name="ck_sessions_ip_hash_length"),
        sa.CheckConstraint("octet_length(ua_hash) = 32", name="ck_sessions_ua_hash_length"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "magic_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(email::text) BETWEEN 3 AND 320", name="ck_magic_links_email_length"
        ),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32", name="ck_magic_links_token_hash_length"
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_magic_links_expiry"),
        sa.CheckConstraint(
            "used_at IS NULL OR used_at >= created_at", name="ck_magic_links_used_at"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )

    op.create_table(
        "wallet_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("chain_family", sa.String(length=16), server_default="evm", nullable=False),
        sa.Column("is_contract", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "linked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("unlinked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("octet_length(address) = 20", name="ck_wallet_links_address_length"),
        sa.CheckConstraint("chain_family = 'evm'", name="ck_wallet_links_chain_family"),
        sa.CheckConstraint(
            "unlinked_at IS NULL OR unlinked_at >= linked_at",
            name="ck_wallet_links_unlinked_at",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wallet_links_user_id", "wallet_links", ["user_id"])
    op.create_index(
        "uq_wallet_links_active_address",
        "wallet_links",
        ["address"],
        unique=True,
        postgresql_where=sa.text("unlinked_at IS NULL"),
    )

    op.create_table(
        "siwe_nonces",
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(nonce) BETWEEN 8 AND 128", name="ck_siwe_nonces_length"),
        sa.CheckConstraint("expires_at > created_at", name="ck_siwe_nonces_expiry"),
        sa.CheckConstraint(
            "used_at IS NULL OR used_at >= created_at", name="ck_siwe_nonces_used_at"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("nonce"),
    )
    op.create_index("ix_siwe_nonces_user_id", "siwe_nonces", ["user_id"])

    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("legal_name", sa.String(length=300), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("display_tz", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column("solo_mode", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("auto_match", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_organizations_name"),
        sa.CheckConstraint(
            "country IS NULL OR country ~ '^[A-Z]{2}$'", name="ck_organizations_country"
        ),
        sa.CheckConstraint("length(btrim(display_tz)) > 0", name="ck_organizations_display_tz"),
        sa.CheckConstraint("version > 0", name="ck_organizations_version"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("roles", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("cardinality(roles) > 0", name="ck_memberships_roles_not_empty"),
        sa.CheckConstraint(
            "array_position(roles, NULL) IS NULL", name="ck_memberships_roles_no_null"
        ),
        sa.CheckConstraint(VALID_ROLES, name="ck_memberships_roles_valid"),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_memberships_status"),
        sa.CheckConstraint("version > 0", name="ck_memberships_version"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "user_id", name="uq_memberships_org_user"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("roles", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(email::text) BETWEEN 3 AND 320", name="ck_invites_email_length"),
        sa.CheckConstraint("octet_length(token_hash) = 32", name="ck_invites_token_hash_length"),
        sa.CheckConstraint("cardinality(roles) > 0", name="ck_invites_roles_not_empty"),
        sa.CheckConstraint("array_position(roles, NULL) IS NULL", name="ck_invites_roles_no_null"),
        sa.CheckConstraint(VALID_ROLES, name="ck_invites_roles_valid"),
        sa.CheckConstraint("expires_at > created_at", name="ck_invites_expiry"),
        sa.CheckConstraint(
            "accepted_at IS NULL OR accepted_at >= created_at", name="ck_invites_accepted_at"
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="ck_invites_revoked_at"
        ),
        sa.CheckConstraint(
            "NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="ck_invites_terminal_state",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_invites_token_hash"),
    )
    op.create_index("ix_invites_org_id_email", "invites", ["org_id", "email"])


def downgrade() -> None:
    op.drop_index("ix_invites_org_id_email", table_name="invites")
    op.drop_table("invites")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("organizations")
    op.drop_index("ix_siwe_nonces_user_id", table_name="siwe_nonces")
    op.drop_table("siwe_nonces")
    op.drop_index("uq_wallet_links_active_address", table_name="wallet_links")
    op.drop_index("ix_wallet_links_user_id", table_name="wallet_links")
    op.drop_table("wallet_links")
    op.drop_table("magic_links")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS citext")
