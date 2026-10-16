"""Pin organizations to a data region and tag stored documents with it (CMP-L04)

Revision ID: 20261016_0090
Revises: 20261016_0088
Create Date: 2026-10-16 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261016_0090"
down_revision: str | None = "20261016_0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "org_data_regions",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("region", sa.String(length=32), nullable=False),
        sa.Column("pinned_by", sa.String(length=200), nullable=False),
        sa.Column(
            "pinned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id"),
        sa.CheckConstraint("region ~ '^[a-z][a-z0-9-]{1,31}$'", name="ck_org_data_regions_region"),
    )
    op.execute(
        """
        CREATE FUNCTION org_data_regions_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                -- Allow the cascade from deleting the organization itself.
                IF EXISTS (SELECT 1 FROM organizations WHERE id = OLD.org_id) THEN
                    RAISE EXCEPTION 'org_data_regions rows cannot be deleted';
                END IF;
                RETURN OLD;
            END IF;
            IF NEW.region IS DISTINCT FROM OLD.region OR NEW.org_id IS DISTINCT FROM OLD.org_id THEN
                RAISE EXCEPTION 'a data region pin cannot be changed';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER org_data_regions_immutable
        BEFORE UPDATE OR DELETE ON org_data_regions
        FOR EACH ROW EXECUTE FUNCTION org_data_regions_immutable()
        """
    )
    # NULL = stored in the default (unpinned) object storage, before region pinning existed.
    op.add_column("documents", sa.Column("storage_region", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "storage_region")
    op.execute("DROP TRIGGER org_data_regions_immutable ON org_data_regions")
    op.execute("DROP FUNCTION org_data_regions_immutable()")
    op.drop_table("org_data_regions")
