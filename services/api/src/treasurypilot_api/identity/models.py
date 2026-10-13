from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base
from treasurypilot_core.ids import uuid7


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class OrganizationRole(StrEnum):
    ORG_ADMIN = "OrgAdmin"
    OWNER = "Owner"
    APPROVER = "Approver"
    OPERATOR = "Operator"
    FINANCE = "Finance"
    GUARDIAN = "Guardian"
    AUDITOR = "Auditor"
    PLATFORM_ADMIN = "PlatformAdmin"


# Roles that sign with a linked wallet; they are inactive until one is linked (FR-012).
SIGNER_ROLES = frozenset(
    {OrganizationRole.OWNER.value, OrganizationRole.APPROVER.value, OrganizationRole.GUARDIAN.value}
)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(email::text) BETWEEN 3 AND 320", name="ck_users_email_length"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
        CheckConstraint("version > 0", name="ck_users_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=UserStatus.ACTIVE, server_default=UserStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_sessions_expiry"),
        CheckConstraint("last_seen_at >= created_at", name="ck_sessions_last_seen"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="ck_sessions_revoked_at"
        ),
        CheckConstraint("octet_length(ip_hash) = 32", name="ck_sessions_ip_hash_length"),
        CheckConstraint("octet_length(ua_hash) = 32", name="ck_sessions_ua_hash_length"),
        CheckConstraint("octet_length(token_hash) = 32", name="ck_sessions_token_hash_length"),
        Index("ix_sessions_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ip_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    ua_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MagicLink(Base):
    __tablename__ = "magic_links"
    __table_args__ = (
        CheckConstraint(
            "length(email::text) BETWEEN 3 AND 320", name="ck_magic_links_email_length"
        ),
        CheckConstraint("octet_length(token_hash) = 32", name="ck_magic_links_token_hash_length"),
        CheckConstraint("expires_at > created_at", name="ck_magic_links_expiry"),
        CheckConstraint("used_at IS NULL OR used_at >= created_at", name="ck_magic_links_used_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WalletLink(Base):
    __tablename__ = "wallet_links"
    __table_args__ = (
        CheckConstraint("octet_length(address) = 20", name="ck_wallet_links_address_length"),
        CheckConstraint("chain_family = 'evm'", name="ck_wallet_links_chain_family"),
        CheckConstraint(
            "unlinked_at IS NULL OR unlinked_at >= linked_at", name="ck_wallet_links_unlinked_at"
        ),
        Index("ix_wallet_links_user_id", "user_id"),
        Index(
            "uq_wallet_links_active_address",
            "address",
            unique=True,
            postgresql_where=text("unlinked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    chain_family: Mapped[str] = mapped_column(
        String(16), nullable=False, default="evm", server_default="evm"
    )
    is_contract: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    unlinked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SiweNonce(Base):
    __tablename__ = "siwe_nonces"
    __table_args__ = (
        CheckConstraint("length(nonce) BETWEEN 8 AND 128", name="ck_siwe_nonces_length"),
        CheckConstraint("expires_at > created_at", name="ck_siwe_nonces_expiry"),
        CheckConstraint("used_at IS NULL OR used_at >= created_at", name="ck_siwe_nonces_used_at"),
        Index("ix_siwe_nonces_user_id", "user_id"),
    )

    nonce: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="ck_organizations_name"),
        CheckConstraint(
            "country IS NULL OR country ~ '^[A-Z]{2}$'", name="ck_organizations_country"
        ),
        CheckConstraint("length(btrim(display_tz)) > 0", name="ck_organizations_display_tz"),
        CheckConstraint("version > 0", name="ck_organizations_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(300))
    country: Mapped[str | None] = mapped_column(String(2))
    display_tz: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    solo_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    auto_match: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": version}


_VALID_ROLES_SQL = """
roles <@ ARRAY[
    'OrgAdmin', 'Owner', 'Approver', 'Operator', 'Finance', 'Guardian', 'Auditor',
    'PlatformAdmin'
]::text[]
"""


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_memberships_org_user"),
        CheckConstraint("cardinality(roles) > 0", name="ck_memberships_roles_not_empty"),
        CheckConstraint("array_position(roles, NULL) IS NULL", name="ck_memberships_roles_no_null"),
        CheckConstraint(_VALID_ROLES_SQL, name="ck_memberships_roles_valid"),
        CheckConstraint("status IN ('active', 'suspended')", name="ck_memberships_status"),
        CheckConstraint(
            "NOT owner_is_onchain OR owner_checked_at IS NOT NULL",
            name="ck_memberships_owner_check_time",
        ),
        CheckConstraint("version > 0", name="ck_memberships_version"),
        Index("ix_memberships_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    roles: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MembershipStatus.ACTIVE,
        server_default=MembershipStatus.ACTIVE,
    )
    owner_is_onchain: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    owner_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class Invite(Base):
    __tablename__ = "invites"
    __table_args__ = (
        CheckConstraint("length(email::text) BETWEEN 3 AND 320", name="ck_invites_email_length"),
        CheckConstraint("octet_length(token_hash) = 32", name="ck_invites_token_hash_length"),
        CheckConstraint("cardinality(roles) > 0", name="ck_invites_roles_not_empty"),
        CheckConstraint("array_position(roles, NULL) IS NULL", name="ck_invites_roles_no_null"),
        CheckConstraint(_VALID_ROLES_SQL, name="ck_invites_roles_valid"),
        CheckConstraint("expires_at > created_at", name="ck_invites_expiry"),
        CheckConstraint(
            "accepted_at IS NULL OR accepted_at >= created_at", name="ck_invites_accepted_at"
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="ck_invites_revoked_at"
        ),
        CheckConstraint(
            "NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="ck_invites_terminal_state",
        ),
        UniqueConstraint("token_hash", name="uq_invites_token_hash"),
        Index("ix_invites_org_id_email", "org_id", "email"),
        Index(
            "uq_invites_pending_org_id_email",
            "org_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    roles: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
