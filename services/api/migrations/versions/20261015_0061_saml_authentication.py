"""Add organization-scoped SAML identity links and one-time login state.

Revision ID: 20261015_0061
Revises: 20261015_0060
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0061"
down_revision: str | None = "20261015_0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scim_users",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_membership", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "initial_activation_pending", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "deactivated_membership", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE", name="fk_scim_users_org"
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "user_id"],
            ["memberships.org_id", "memberships.user_id"],
            ondelete="CASCADE",
            name="fk_scim_users_membership_org_user",
        ),
        sa.PrimaryKeyConstraint("org_id", "user_id", name="pk_scim_users"),
        sa.UniqueConstraint("org_id", "external_id", name="uq_scim_users_org_external_id"),
        sa.CheckConstraint(
            "external_id IS NULL OR length(external_id) BETWEEN 1 AND 100",
            name="ck_scim_users_external_id_length",
        ),
        sa.CheckConstraint(
            "display_name IS NULL OR length(display_name) BETWEEN 1 AND 200",
            name="ck_scim_users_display_name_length",
        ),
    )
    op.create_index("ix_scim_users_org_active", "scim_users", ["org_id", "active"])

    op.create_table(
        "saml_identities",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issuer", sa.String(length=500), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "linked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(issuer) BETWEEN 1 AND 500", name="ck_saml_identity_issuer_length"
        ),
        sa.CheckConstraint(
            "length(subject) BETWEEN 1 AND 255", name="ck_saml_identity_subject_length"
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE", name="fk_saml_identity_org"
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "user_id"],
            ["memberships.org_id", "memberships.user_id"],
            ondelete="CASCADE",
            name="fk_saml_identity_membership_org_user",
        ),
        sa.PrimaryKeyConstraint("org_id", "issuer", "subject", name="pk_saml_identities"),
        sa.UniqueConstraint(
            "org_id", "issuer", "user_id", name="uq_saml_identities_org_issuer_user"
        ),
    )
    op.create_index("ix_saml_identities_user_id", "saml_identities", ["user_id"])

    op.create_table(
        "saml_login_requests",
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relay_state_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("browser_nonce_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(request_id) BETWEEN 1 AND 255", name="ck_saml_request_id_length"
        ),
        sa.CheckConstraint("octet_length(relay_state_hash) = 32", name="ck_saml_relay_hash_length"),
        sa.CheckConstraint(
            "octet_length(browser_nonce_hash) = 32", name="ck_saml_browser_nonce_hash_length"
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_saml_login_request_expiry"),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="ck_saml_request_consumed_at",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE", name="fk_saml_request_org"
        ),
        sa.PrimaryKeyConstraint("request_id", name="pk_saml_login_requests"),
        sa.UniqueConstraint("relay_state_hash", name="uq_saml_login_request_relay_hash"),
    )
    op.create_index("ix_saml_login_requests_expiry", "saml_login_requests", ["expires_at"])

    op.create_table(
        "saml_replay_ids",
        sa.Column("identifier", sa.String(length=520), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(identifier) BETWEEN 1 AND 520", name="ck_saml_replay_id_length"),
        sa.CheckConstraint("expires_at > created_at", name="ck_saml_replay_expiry"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE", name="fk_saml_replay_org"
        ),
        sa.PrimaryKeyConstraint("identifier", name="pk_saml_replay_ids"),
    )
    op.create_index("ix_saml_replay_ids_expiry", "saml_replay_ids", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_scim_users_org_active", table_name="scim_users")
    op.drop_table("scim_users")
    op.drop_index("ix_saml_replay_ids_expiry", table_name="saml_replay_ids")
    op.drop_table("saml_replay_ids")
    op.drop_index("ix_saml_login_requests_expiry", table_name="saml_login_requests")
    op.drop_table("saml_login_requests")
    op.drop_index("ix_saml_identities_user_id", table_name="saml_identities")
    op.drop_table("saml_identities")
