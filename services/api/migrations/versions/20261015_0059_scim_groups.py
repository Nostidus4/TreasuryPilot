"""Add allowlisted SCIM groups and membership role-source grants.

Revision ID: 20261015_0059
Revises: 20261015_0054
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0059"
down_revision: str | None = "20261015_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ASSIGNABLE_ROLES = "ARRAY['Operator', 'Finance', 'Auditor']::text[]"


def upgrade() -> None:
    empty_roles = sa.text("'{}'::text[]")
    op.add_column(
        "memberships",
        sa.Column(
            "manual_roles", postgresql.ARRAY(sa.Text()), server_default=empty_roles, nullable=False
        ),
    )
    op.add_column(
        "memberships",
        sa.Column(
            "oidc_roles", postgresql.ARRAY(sa.Text()), server_default=empty_roles, nullable=False
        ),
    )
    op.add_column(
        "memberships",
        sa.Column(
            "scim_roles", postgresql.ARRAY(sa.Text()), server_default=empty_roles, nullable=False
        ),
    )
    op.add_column(
        "memberships",
        sa.Column(
            "role_sources_initialized", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.execute(
        sa.text(
            "UPDATE memberships SET manual_roles = roles, oidc_roles = ARRAY[]::text[], "
            "scim_roles = ARRAY[]::text[], role_sources_initialized = false"
        )
    )
    op.drop_constraint("ck_memberships_roles_not_empty", "memberships", type_="check")
    op.create_check_constraint(
        "ck_memberships_roles_not_empty",
        "memberships",
        "cardinality(roles) > 0 OR status = 'suspended'",
    )
    op.create_check_constraint(
        "ck_memberships_manual_roles_no_null",
        "memberships",
        "array_position(manual_roles, NULL) IS NULL",
    )
    op.create_check_constraint(
        "ck_memberships_manual_roles_valid",
        "memberships",
        "manual_roles <@ ARRAY['OrgAdmin', 'Owner', 'Approver', 'Operator', 'Finance', "
        "'Guardian', 'Auditor', 'PlatformAdmin']::text[]",
    )
    op.create_check_constraint(
        "ck_memberships_oidc_roles_no_null",
        "memberships",
        "array_position(oidc_roles, NULL) IS NULL",
    )
    op.create_check_constraint(
        "ck_memberships_oidc_roles_valid",
        "memberships",
        f"oidc_roles <@ {_ASSIGNABLE_ROLES}",
    )
    op.create_check_constraint(
        "ck_memberships_scim_roles_no_null",
        "memberships",
        "array_position(scim_roles, NULL) IS NULL",
    )
    op.create_check_constraint(
        "ck_memberships_scim_roles_valid",
        "memberships",
        f"scim_roles <@ {_ASSIGNABLE_ROLES}",
    )
    op.create_unique_constraint("uq_memberships_id_org", "memberships", ["id", "org_id"])

    op.create_table(
        "scim_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "org_id", name="uq_scim_groups_id_org"),
        sa.UniqueConstraint("org_id", "display_name", name="uq_scim_groups_org_display_name"),
        sa.CheckConstraint(
            "length(display_name) BETWEEN 1 AND 100", name="ck_scim_groups_display_name_length"
        ),
    )
    op.create_table(
        "scim_group_members",
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "org_id"],
            ["scim_groups.id", "scim_groups.org_id"],
            ondelete="CASCADE",
            name="fk_scim_group_members_group_org",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "user_id"],
            ["memberships.org_id", "memberships.user_id"],
            ondelete="CASCADE",
            name="fk_scim_group_members_membership_org_user",
        ),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
    )
    op.create_index("ix_scim_group_members_org_user", "scim_group_members", ["org_id", "user_id"])


def downgrade() -> None:
    op.execute(
        """
        DO $scim_groups_downgrade$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM memberships WHERE cardinality(scim_roles) > 0
            ) THEN
                RAISE EXCEPTION 'clear all SCIM role grants before downgrading revision 20261015_0059';
            END IF;
            IF EXISTS (
                SELECT 1 FROM memberships
                WHERE cardinality(roles) = 0 AND status = 'suspended'
            ) THEN
                RAISE EXCEPTION 'restore a role grant before downgrading revision 20261015_0059';
            END IF;
        END;
        $scim_groups_downgrade$
        """
    )
    op.drop_index("ix_scim_group_members_org_user", table_name="scim_group_members")
    op.drop_table("scim_group_members")
    op.drop_table("scim_groups")
    op.drop_constraint("uq_memberships_id_org", "memberships", type_="unique")
    for name in (
        "ck_memberships_scim_roles_valid",
        "ck_memberships_scim_roles_no_null",
        "ck_memberships_oidc_roles_valid",
        "ck_memberships_oidc_roles_no_null",
        "ck_memberships_manual_roles_valid",
        "ck_memberships_manual_roles_no_null",
    ):
        op.drop_constraint(name, "memberships", type_="check")
    op.drop_constraint("ck_memberships_roles_not_empty", "memberships", type_="check")
    op.create_check_constraint(
        "ck_memberships_roles_not_empty", "memberships", "cardinality(roles) > 0"
    )
    op.drop_column("memberships", "scim_roles")
    op.drop_column("memberships", "oidc_roles")
    op.drop_column("memberships", "manual_roles")
    op.drop_column("memberships", "role_sources_initialized")
