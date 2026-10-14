from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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
    organization_scope_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
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
    # Last successful second-factor check on this session; sensitive routes need it fresh.
    step_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
        CheckConstraint(
            "platform_status IN ('active', 'suspended')", name="ck_organizations_platform_status"
        ),
        CheckConstraint("version > 0", name="ck_organizations_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(300))
    country: Mapped[str | None] = mapped_column(String(2))
    display_tz: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    platform_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
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
<@ ARRAY[
    'OrgAdmin', 'Owner', 'Approver', 'Operator', 'Finance', 'Guardian', 'Auditor',
    'PlatformAdmin'
]::text[]
"""

_ASSIGNABLE_WORK_ROLES_SQL = """
<@ ARRAY['Operator', 'Finance', 'Auditor']::text[]
"""


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_memberships_org_user"),
        CheckConstraint(
            "cardinality(roles) > 0 OR status = 'suspended'",
            name="ck_memberships_roles_not_empty",
        ),
        CheckConstraint("array_position(roles, NULL) IS NULL", name="ck_memberships_roles_no_null"),
        CheckConstraint("roles " + _VALID_ROLES_SQL, name="ck_memberships_roles_valid"),
        CheckConstraint(
            "array_position(manual_roles, NULL) IS NULL",
            name="ck_memberships_manual_roles_no_null",
        ),
        CheckConstraint(
            "manual_roles " + _VALID_ROLES_SQL,
            name="ck_memberships_manual_roles_valid",
        ),
        CheckConstraint(
            "array_position(oidc_roles, NULL) IS NULL",
            name="ck_memberships_oidc_roles_no_null",
        ),
        CheckConstraint(
            "oidc_roles " + _ASSIGNABLE_WORK_ROLES_SQL,
            name="ck_memberships_oidc_roles_valid",
        ),
        CheckConstraint(
            "array_position(scim_roles, NULL) IS NULL",
            name="ck_memberships_scim_roles_no_null",
        ),
        CheckConstraint(
            "scim_roles " + _ASSIGNABLE_WORK_ROLES_SQL,
            name="ck_memberships_scim_roles_valid",
        ),
        CheckConstraint("status IN ('active', 'suspended')", name="ck_memberships_status"),
        CheckConstraint(
            "NOT owner_is_onchain OR owner_checked_at IS NOT NULL",
            name="ck_memberships_owner_check_time",
        ),
        CheckConstraint("version > 0", name="ck_memberships_version"),
        UniqueConstraint("id", "org_id", name="uq_memberships_id_org"),
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
    manual_roles: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    oidc_roles: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    scim_roles: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    role_sources_initialized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
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


class ScimGroup(Base):
    __tablename__ = "scim_groups"
    __table_args__ = (
        UniqueConstraint("org_id", "display_name", name="uq_scim_groups_org_display_name"),
        UniqueConstraint("id", "org_id", name="uq_scim_groups_id_org"),
        CheckConstraint(
            "length(display_name) BETWEEN 1 AND 100", name="ck_scim_groups_display_name_length"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ScimGroupMember(Base):
    __tablename__ = "scim_group_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id", "org_id"],
            ["scim_groups.id", "scim_groups.org_id"],
            ondelete="CASCADE",
            name="fk_scim_group_members_group_org",
        ),
        ForeignKeyConstraint(
            ["org_id", "user_id"],
            ["memberships.org_id", "memberships.user_id"],
            ondelete="CASCADE",
            name="fk_scim_group_members_membership_org_user",
        ),
        Index("ix_scim_group_members_org_user", "org_id", "user_id"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


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


class OIDCIdentity(Base):
    __tablename__ = "oidc_identities"
    __table_args__ = (
        UniqueConstraint("user_id", "issuer", name="uq_oidc_identities_user_issuer"),
        CheckConstraint(
            "length(subject) BETWEEN 1 AND 255", name="ck_oidc_identity_subject_length"
        ),
    )

    issuer: Mapped[str] = mapped_column(String(500), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MfaFactor(Base):
    __tablename__ = "mfa_factors"
    __table_args__ = (
        CheckConstraint("kind IN ('totp', 'webauthn')", name="ck_mfa_factors_kind"),
        CheckConstraint(
            "(kind = 'totp' AND secret IS NOT NULL AND credential_id IS NULL)"
            " OR (kind = 'webauthn' AND secret IS NULL AND credential_id IS NOT NULL"
            " AND public_key IS NOT NULL)",
            name="ck_mfa_factors_material",
        ),
        Index("ix_mfa_factors_user_id", "user_id"),
        Index(
            "uq_mfa_factors_credential_id",
            "credential_id",
            unique=True,
            postgresql_where=text("credential_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    # TOTP shared secret as a field-encryption envelope; never stored in clear.
    secret: Mapped[str | None] = mapped_column(Text())
    credential_id: Mapped[bytes | None] = mapped_column(LargeBinary())
    # Raw P-256 point, x || y (64 bytes).
    public_key: Mapped[bytes | None] = mapped_column(LargeBinary(64))
    sign_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Highest accepted TOTP time step: a code can be used once.
    last_counter: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MfaRecoveryCode(Base):
    __tablename__ = "mfa_recovery_codes"
    __table_args__ = (
        CheckConstraint("octet_length(code_hash) = 32", name="ck_mfa_recovery_codes_hash_length"),
        Index("ix_mfa_recovery_codes_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
