from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.models import AuditActorType
from treasurypilot_api.audit.writer import AuditActor, AuditEntity
from treasurypilot_api.audit.writer import write as write_audit
from treasurypilot_api.identity.auth import normalize_email
from treasurypilot_api.identity.memberships import (
    LastAdministrator,
    LastOwner,
    _guard_last_roles,
)
from treasurypilot_api.identity.models import (
    Membership,
    MembershipStatus,
    OIDCIdentity,
    Organization,
    ScimGroup,
    ScimGroupMember,
    Session,
    User,
    UserStatus,
)
from treasurypilot_api.identity.role_grants import (
    initialize_legacy_role_sources,
    recompute_membership_roles,
)
from treasurypilot_core.ids import uuid7

logger = logging.getLogger(__name__)

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
_USER_NAME_FILTER = re.compile(r'^\s*userName\s+eq\s+"([^"\\]{1,320})"\s*$', re.IGNORECASE)
_INTEGER = re.compile(r"[0-9]{1,10}")  # ASCII digits only: no signs, spaces or underscores
_MAX_INDEX = 2**31 - 1
_AUTH_FAILURE_LIMIT = 10
_AUTH_FAILURE_WINDOW = timedelta(minutes=1)
_GROUP_NAME_FILTER = re.compile(r'^\s*displayName\s+eq\s+"([^"\\]{1,100})"\s*$', re.IGNORECASE)
_GROUP_MEMBER_FILTER = re.compile(
    r'^members\s*\[\s*value\s+eq\s+"([0-9a-fA-F-]{36})"\s*\]$', re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class ScimUserRecord:
    id: uuid.UUID
    user_name: str
    display_name: str | None
    active: bool
    created_at: datetime
    last_modified: datetime


@dataclass(frozen=True, slots=True)
class ScimGroupRecord:
    id: uuid.UUID
    display_name: str
    member_ids: tuple[uuid.UUID, ...]
    created_at: datetime
    last_modified: datetime


class ScimGroupConflict(Exception):
    """The configured SCIM group already exists."""


class ScimGroupInvalidMember(Exception):
    """A referenced user is not an active member of the configured organization."""


class ScimGroupNotAllowed(Exception):
    """The group name is not in the configured SCIM allowlist."""


class ScimIdentityRepository(Protocol):
    async def organization_exists(self, organization_id: uuid.UUID) -> bool: ...

    async def list_users(
        self,
        *,
        organization_id: uuid.UUID,
        user_name: str | None,
        start_index: int,
        count: int,
    ) -> tuple[int, tuple[ScimUserRecord, ...]]: ...

    async def get_user(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> ScimUserRecord | None: ...

    async def deactivate_user(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID, now: datetime
    ) -> ScimUserRecord | None: ...

    async def list_groups(
        self,
        *,
        organization_id: uuid.UUID,
        display_name: str | None,
        start_index: int,
        count: int,
    ) -> tuple[int, tuple[ScimGroupRecord, ...]]: ...

    async def get_group(
        self, *, organization_id: uuid.UUID, group_id: uuid.UUID
    ) -> ScimGroupRecord | None: ...

    async def create_group(
        self,
        *,
        organization_id: uuid.UUID,
        display_name: str,
        member_ids: tuple[uuid.UUID, ...],
        role_map: Mapping[str, Sequence[str]],
        now: datetime,
    ) -> ScimGroupRecord: ...

    async def patch_group_members(
        self,
        *,
        organization_id: uuid.UUID,
        group_id: uuid.UUID,
        add_member_ids: tuple[uuid.UUID, ...],
        remove_member_ids: tuple[uuid.UUID, ...] | None,
        role_map: Mapping[str, Sequence[str]],
        now: datetime,
    ) -> ScimGroupRecord | None: ...

    async def delete_group(
        self,
        *,
        organization_id: uuid.UUID,
        group_id: uuid.UUID,
        role_map: Mapping[str, Sequence[str]],
        now: datetime,
    ) -> bool: ...

    async def reconcile_group_roles(
        self,
        *,
        organization_id: uuid.UUID | None,
        role_map: Mapping[str, Sequence[str]],
        now: datetime,
    ) -> None: ...


class SqlAlchemyScimIdentityRepository:
    """Tenant-scoped SCIM reads and membership deprovisioning."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        oidc_organization_id: uuid.UUID | None = None,
    ) -> None:
        self._sessions = sessions
        self._oidc_organization_id = oidc_organization_id

    async def organization_exists(self, organization_id: uuid.UUID) -> bool:
        async with self._sessions() as session:
            return bool(
                await session.scalar(select(exists().where(Organization.id == organization_id)))
            )

    async def list_users(
        self,
        *,
        organization_id: uuid.UUID,
        user_name: str | None,
        start_index: int,
        count: int,
    ) -> tuple[int, tuple[ScimUserRecord, ...]]:
        filters = [Membership.org_id == organization_id]
        if user_name is not None:
            filters.append(User.email == user_name)
        async with self._sessions() as session:
            total = int(
                await session.scalar(
                    select(func.count())
                    .select_from(Membership)
                    .join(User, User.id == Membership.user_id)
                    .where(*filters)
                )
                or 0
            )
            rows = (
                await session.execute(
                    select(Membership, User)
                    .join(User, User.id == Membership.user_id)
                    .where(*filters)
                    .order_by(User.email, User.id)
                    .offset(start_index - 1)
                    .limit(count)
                )
            ).all()
            return total, tuple(_record(membership, user) for membership, user in rows)

    async def get_user(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> ScimUserRecord | None:
        async with self._sessions() as session:
            row = await session.execute(
                select(Membership, User)
                .join(User, User.id == Membership.user_id)
                .where(Membership.org_id == organization_id, User.id == user_id)
            )
            found = row.one_or_none()
            return _record(*found) if found is not None else None

    async def deactivate_user(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID, now: datetime
    ) -> ScimUserRecord | None:
        async with self._sessions() as session, session.begin():
            memberships = list(
                (
                    await session.scalars(
                        select(Membership)
                        .where(Membership.org_id == organization_id)
                        .order_by(Membership.user_id)
                        .with_for_update()
                    )
                ).all()
            )
            membership = next((item for item in memberships if item.user_id == user_id), None)
            if membership is None:
                return None

            was_active = membership.status == MembershipStatus.ACTIVE
            if was_active:
                _guard_last_roles(memberships, membership, set())
                membership.status = MembershipStatus.SUSPENDED
                await session.flush()

            # Scoped OIDC sessions must stop working immediately. Unscoped sessions may
            # still serve other organizations; RBAC checks the suspended membership on
            # every request to this organization.
            await session.execute(
                update(Session)
                .where(
                    Session.user_id == user_id,
                    Session.organization_scope_id == organization_id,
                    Session.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )

            user = await session.scalar(select(User).where(User.id == user_id))
            if user is None:  # The membership foreign key makes this unreachable.
                raise RuntimeError("SCIM membership user is missing")
            if was_active:
                await write_audit(
                    session,
                    org_id=organization_id,
                    actor=AuditActor(AuditActorType.SYSTEM, "scim"),
                    action="identity.scim.deprovisioned",
                    entity=AuditEntity("membership", membership.id),
                    data={"status": MembershipStatus.SUSPENDED},
                )
            await session.refresh(membership)
            return _record(membership, user)

    async def list_groups(
        self,
        *,
        organization_id: uuid.UUID,
        display_name: str | None,
        start_index: int,
        count: int,
    ) -> tuple[int, tuple[ScimGroupRecord, ...]]:
        filters = [ScimGroup.org_id == organization_id]
        if display_name is not None:
            filters.append(ScimGroup.display_name == display_name)
        async with self._sessions() as session:
            total = int(
                await session.scalar(select(func.count()).select_from(ScimGroup).where(*filters))
                or 0
            )
            groups = (
                await session.scalars(
                    select(ScimGroup)
                    .where(*filters)
                    .order_by(ScimGroup.display_name, ScimGroup.id)
                    .offset(start_index - 1)
                    .limit(count)
                )
            ).all()
            members: dict[uuid.UUID, list[uuid.UUID]] = {}
            if groups:
                rows = await session.execute(
                    select(ScimGroupMember.group_id, ScimGroupMember.user_id).where(
                        ScimGroupMember.org_id == organization_id,
                        ScimGroupMember.group_id.in_([group.id for group in groups]),
                    )
                )
                for group_id, user_id in rows:
                    members.setdefault(group_id, []).append(user_id)
            return total, tuple(_group_record(group, members.get(group.id, ())) for group in groups)

    async def get_group(
        self, *, organization_id: uuid.UUID, group_id: uuid.UUID
    ) -> ScimGroupRecord | None:
        async with self._sessions() as session:
            group = await session.scalar(
                select(ScimGroup).where(
                    ScimGroup.org_id == organization_id, ScimGroup.id == group_id
                )
            )
            return None if group is None else await self._load_group_record(session, group)

    async def create_group(
        self,
        *,
        organization_id: uuid.UUID,
        display_name: str,
        member_ids: tuple[uuid.UUID, ...],
        role_map: Mapping[str, Sequence[str]],
        now: datetime,
    ) -> ScimGroupRecord:
        if display_name not in role_map:
            raise ScimGroupNotAllowed
        try:
            async with self._sessions() as session, session.begin():
                group = ScimGroup(
                    id=uuid7(),
                    org_id=organization_id,
                    display_name=display_name,
                    created_at=now,
                    updated_at=now,
                )
                session.add(group)
                await session.flush()
                added = await self._add_group_members(
                    session, group, organization_id, member_ids, now
                )
                await self._recompute_group_roles(session, organization_id, added, role_map, now)
                await write_audit(
                    session,
                    org_id=organization_id,
                    actor=AuditActor(AuditActorType.SYSTEM, "scim"),
                    action="identity.scim.group.created",
                    entity=AuditEntity("scim_group", group.id),
                    data={"displayName": display_name, "memberCount": len(added)},
                )
                await session.flush()
                return await self._load_group_record(session, group)
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint == "uq_scim_groups_org_display_name":
                raise ScimGroupConflict from None
            raise

    async def patch_group_members(
        self,
        *,
        organization_id: uuid.UUID,
        group_id: uuid.UUID,
        add_member_ids: tuple[uuid.UUID, ...],
        remove_member_ids: tuple[uuid.UUID, ...] | None,
        role_map: Mapping[str, Sequence[str]],
        now: datetime,
    ) -> ScimGroupRecord | None:
        async with self._sessions() as session, session.begin():
            group = await session.scalar(
                select(ScimGroup)
                .where(ScimGroup.org_id == organization_id, ScimGroup.id == group_id)
                .with_for_update()
            )
            if group is None:
                return None
            if group.display_name not in role_map:
                raise ScimGroupNotAllowed

            before = set(
                (
                    await session.scalars(
                        select(ScimGroupMember.user_id).where(
                            ScimGroupMember.org_id == organization_id,
                            ScimGroupMember.group_id == group_id,
                        )
                    )
                ).all()
            )
            # Net result is (before - remove) | add, so a user both removed and added stays.
            remove_ids = (
                before if remove_member_ids is None else before & set(remove_member_ids)
            ) - set(add_member_ids)
            if remove_ids:
                await session.execute(
                    delete(ScimGroupMember).where(
                        ScimGroupMember.org_id == organization_id,
                        ScimGroupMember.group_id == group_id,
                        ScimGroupMember.user_id.in_(remove_ids),
                    )
                )
            added = await self._add_group_members(
                session, group, organization_id, add_member_ids, now
            )
            removed = remove_ids
            changed = added | removed
            group.updated_at = now
            if changed:
                await self._recompute_group_roles(session, organization_id, changed, role_map, now)
                for user_id in sorted(added | removed, key=str):
                    action = (
                        "identity.scim.group.member_added"
                        if user_id in added
                        else "identity.scim.group.member_removed"
                    )
                    await write_audit(
                        session,
                        org_id=organization_id,
                        actor=AuditActor(AuditActorType.SYSTEM, "scim"),
                        action=action,
                        entity=AuditEntity("scim_group", group.id),
                        data={"userId": str(user_id)},
                    )
            await session.flush()
            return await self._load_group_record(session, group)

    async def delete_group(
        self,
        *,
        organization_id: uuid.UUID,
        group_id: uuid.UUID,
        role_map: Mapping[str, Sequence[str]],
        now: datetime,
    ) -> bool:
        async with self._sessions() as session, session.begin():
            group = await session.scalar(
                select(ScimGroup)
                .where(ScimGroup.org_id == organization_id, ScimGroup.id == group_id)
                .with_for_update()
            )
            if group is None:
                return False
            if group.display_name not in role_map:
                raise ScimGroupNotAllowed
            member_ids = set(
                (
                    await session.scalars(
                        select(ScimGroupMember.user_id).where(
                            ScimGroupMember.org_id == organization_id,
                            ScimGroupMember.group_id == group_id,
                        )
                    )
                ).all()
            )
            group_id_value = group.id
            display_name = group.display_name
            await session.delete(group)
            await session.flush()
            await self._recompute_group_roles(session, organization_id, member_ids, role_map, now)
            await write_audit(
                session,
                org_id=organization_id,
                actor=AuditActor(AuditActorType.SYSTEM, "scim"),
                action="identity.scim.group.deleted",
                entity=AuditEntity("scim_group", group_id_value),
                data={"displayName": display_name, "memberCount": len(member_ids)},
            )
            return True

    async def reconcile_group_roles(
        self,
        *,
        organization_id: uuid.UUID | None,
        role_map: Mapping[str, Sequence[str]],
        now: datetime,
    ) -> None:
        """Apply the current SCIM allowlist at startup and discard stale assignments.

        With SCIM disabled (no organization), every organization that still holds SCIM
        groups or roles is reconciled against an empty allowlist, clearing them.
        """
        async with self._sessions() as session, session.begin():
            if organization_id is not None:
                organization_ids = {organization_id}
            else:
                organization_ids = set(
                    (
                        await session.scalars(
                            select(ScimGroup.org_id).union(
                                select(Membership.org_id).where(
                                    func.cardinality(Membership.scim_roles) > 0
                                )
                            )
                        )
                    ).all()
                )
            for scoped_organization_id in sorted(organization_ids, key=str):
                await self._reconcile_organization(
                    session,
                    scoped_organization_id,
                    role_map,
                    now,
                )

    async def _reconcile_organization(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        role_map: Mapping[str, Sequence[str]],
        now: datetime,
    ) -> None:
        groups = list(
            (
                await session.scalars(
                    select(ScimGroup)
                    .where(ScimGroup.org_id == organization_id)
                    .order_by(ScimGroup.id)
                    .with_for_update()
                )
            ).all()
        )
        member_rows = (
            await session.execute(
                select(ScimGroupMember.group_id, ScimGroupMember.user_id).where(
                    ScimGroupMember.org_id == organization_id
                )
            )
        ).all()
        members: dict[uuid.UUID, set[uuid.UUID]] = {}
        for group_id, user_id in member_rows:
            members.setdefault(group_id, set()).add(user_id)
        # A widened or narrowed mapping changes roles for members of every remaining group too.
        affected: set[uuid.UUID] = set()
        for group in groups:
            member_ids = members.get(group.id, set())
            affected.update(member_ids)
            if group.display_name in role_map:
                continue
            await write_audit(
                session,
                org_id=organization_id,
                actor=AuditActor(AuditActorType.SYSTEM, "scim"),
                action="identity.scim.group.configuration_removed",
                entity=AuditEntity("scim_group", group.id),
                data={"displayName": group.display_name, "memberCount": len(member_ids)},
            )
            await session.delete(group)
        affected.update(
            (
                await session.scalars(
                    select(Membership.user_id).where(
                        Membership.org_id == organization_id,
                        func.cardinality(Membership.scim_roles) > 0,
                    )
                )
            ).all()
        )
        await self._recompute_group_roles(session, organization_id, affected, role_map, now)

    @staticmethod
    async def _load_group_record(session: AsyncSession, group: ScimGroup) -> ScimGroupRecord:
        member_ids = (
            await session.scalars(
                select(ScimGroupMember.user_id).where(
                    ScimGroupMember.org_id == group.org_id,
                    ScimGroupMember.group_id == group.id,
                )
            )
        ).all()
        return _group_record(group, member_ids)

    @staticmethod
    async def _add_group_members(
        session: AsyncSession,
        group: ScimGroup,
        organization_id: uuid.UUID,
        member_ids: tuple[uuid.UUID, ...],
        now: datetime,
    ) -> set[uuid.UUID]:
        requested = set(member_ids)
        if not requested:
            return set()
        memberships = (
            await session.scalars(
                select(Membership)
                .join(User, User.id == Membership.user_id)
                .where(
                    Membership.org_id == organization_id,
                    Membership.user_id.in_(requested),
                    Membership.status == MembershipStatus.ACTIVE,
                    User.status == UserStatus.ACTIVE,
                )
                .order_by(Membership.user_id)
                .with_for_update(of=Membership)
            )
        ).all()
        if {membership.user_id for membership in memberships} != requested:
            raise ScimGroupInvalidMember
        existing = set(
            (
                await session.scalars(
                    select(ScimGroupMember.user_id).where(
                        ScimGroupMember.org_id == organization_id,
                        ScimGroupMember.group_id == group.id,
                        ScimGroupMember.user_id.in_(requested),
                    )
                )
            ).all()
        )
        added = requested - existing
        for user_id in added:
            session.add(
                ScimGroupMember(
                    org_id=organization_id,
                    group_id=group.id,
                    user_id=user_id,
                    created_at=now,
                )
            )
        return added

    async def _recompute_group_roles(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        user_ids: set[uuid.UUID],
        role_map: Mapping[str, Sequence[str]],
        now: datetime,
    ) -> None:
        if not user_ids:
            return
        memberships = (
            await session.scalars(
                select(Membership)
                .where(
                    Membership.org_id == organization_id,
                    Membership.user_id.in_(user_ids),
                )
                .order_by(Membership.user_id)
                .with_for_update()
            )
        ).all()
        group_rows = (
            await session.execute(
                select(ScimGroupMember.user_id, ScimGroup.display_name)
                .join(ScimGroup, ScimGroup.id == ScimGroupMember.group_id)
                .where(
                    ScimGroupMember.org_id == organization_id,
                    ScimGroupMember.user_id.in_(user_ids),
                )
            )
        ).all()
        roles_by_user: dict[uuid.UUID, set[str]] = {}
        for user_id, display_name in group_rows:
            roles_by_user.setdefault(user_id, set()).update(role_map.get(display_name, ()))
        oidc_user_ids: set[uuid.UUID] = set()
        if organization_id == self._oidc_organization_id:
            oidc_user_ids = set(
                (
                    await session.scalars(
                        select(OIDCIdentity.user_id).where(OIDCIdentity.user_id.in_(user_ids))
                    )
                ).all()
            )
        for membership in memberships:
            old_roles = set(membership.roles)
            old_status = membership.status
            initialize_legacy_role_sources(
                membership, oidc_identity_linked=membership.user_id in oidc_user_ids
            )
            membership.scim_roles = sorted(roles_by_user.get(membership.user_id, set()))
            new_roles = set(recompute_membership_roles(membership))
            if new_roles != old_roles or membership.status != old_status:
                removed_roles = old_roles - new_roles
                if removed_roles or membership.status != old_status:
                    await session.execute(
                        update(Session)
                        .where(
                            Session.user_id == membership.user_id,
                            Session.organization_scope_id == organization_id,
                            Session.revoked_at.is_(None),
                        )
                        .values(revoked_at=now)
                    )
                await write_audit(
                    session,
                    org_id=organization_id,
                    actor=AuditActor(AuditActorType.SYSTEM, "scim"),
                    action="identity.scim.group_roles.changed",
                    entity=AuditEntity("membership", membership.id),
                    data={
                        "previousRoles": sorted(old_roles),
                        "roles": sorted(new_roles),
                        "status": membership.status,
                    },
                )


def _group_record(group: ScimGroup, member_ids: Sequence[uuid.UUID]) -> ScimGroupRecord:
    return ScimGroupRecord(
        id=group.id,
        display_name=group.display_name,
        member_ids=tuple(sorted(member_ids, key=str)),
        created_at=group.created_at,
        last_modified=group.updated_at,
    )


def _record(membership: Membership, user: User) -> ScimUserRecord:
    return ScimUserRecord(
        id=user.id,
        user_name=str(user.email),
        display_name=user.display_name,
        active=(membership.status == MembershipStatus.ACTIVE and user.status == UserStatus.ACTIVE),
        created_at=user.created_at,
        last_modified=max(user.updated_at, membership.updated_at),
    )


router = APIRouter(prefix="/scim/v2", tags=["scim"])


def _response(
    content: dict[str, object], *, status: int = 200, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/scim+json",
        headers=headers,
        content=content,
    )


def _error(
    status: int,
    detail: str,
    *,
    scim_type: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, object] = {
        "schemas": [SCIM_ERROR_SCHEMA],
        "status": str(status),
        "detail": detail,
    }
    if scim_type is not None:
        body["scimType"] = scim_type
    return _response(body, status=status, headers=headers)


async def _authorized(request: Request) -> uuid.UUID | JSONResponse:
    settings = request.app.state.settings
    if not settings.scim_configured:
        return _error(404, "SCIM is not configured.")
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    token_setting = settings.scim_bearer_token
    organization_id = settings.scim_organization_id
    if token_setting is None or organization_id is None:
        return _error(404, "SCIM is not configured.")
    expected = token_setting.get_secret_value()
    if (
        not separator
        or scheme.casefold() != "bearer"
        or not token
        or not hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))
    ):
        return await _authentication_failed(request)
    repository = getattr(request.app.state, "scim_repository", None)
    if repository is None:
        return _error(503, "SCIM storage is not configured.")
    if not await repository.organization_exists(organization_id):
        logger.warning("TP_SCIM_ORGANIZATION_ID %s matches no organization", organization_id)
        return _error(503, "The configured SCIM organization does not exist.")
    return cast(uuid.UUID, organization_id)


async def _authentication_failed(request: Request) -> JSONResponse:
    host = request.client.host if request.client is not None else "unknown"
    # The token is never logged; the limiter key hashes the IP so the store holds none.
    logger.warning("Rejected SCIM request with an invalid bearer token from %s", host)
    limiter = getattr(request.app.state, "api_key_rate_limiter", None)
    if limiter is not None:
        digest = hashlib.sha256(host.encode()).hexdigest()
        try:
            result = await limiter.hit(
                f"scim-auth-failure:{digest}",
                limit=_AUTH_FAILURE_LIMIT,
                window=_AUTH_FAILURE_WINDOW,
            )
        except Exception:  # Already rejected; a limiter outage must not turn 401 into 500.
            logger.exception("SCIM authentication-failure rate limiter is unavailable")
        else:
            if not result.allowed:
                return _error(
                    429,
                    "Too many failed SCIM authentication attempts.",
                    headers={"Retry-After": str(result.retry_after)},
                )
    return _error(
        401,
        "A valid SCIM bearer token is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _resource(record: ScimUserRecord, request: Request) -> dict[str, object]:
    resource: dict[str, object] = {
        "schemas": [SCIM_USER_SCHEMA],
        "id": str(record.id),
        "userName": record.user_name,
        "displayName": record.display_name,
        "emails": [{"value": record.user_name, "type": "work", "primary": True}],
        "active": record.active,
        "meta": {
            "resourceType": "User",
            "created": record.created_at.isoformat(),
            "lastModified": record.last_modified.isoformat(),
            "location": f"{str(request.base_url).rstrip('/')}/scim/v2/Users/{record.id}",
        },
    }
    if record.display_name:
        resource["name"] = {"formatted": record.display_name}
    return resource


def _repo(request: Request) -> ScimIdentityRepository:
    return cast(ScimIdentityRepository, request.app.state.scim_repository)


async def _group_role_map(request: Request) -> Mapping[str, list[str]] | JSONResponse:
    organization_id = await _authorized(request)
    if isinstance(organization_id, JSONResponse):
        return organization_id
    try:
        role_map = json.loads(request.app.state.settings.scim_group_role_map)
    except (TypeError, ValueError):  # Settings validates this at startup.
        return _error(503, "SCIM group configuration is unavailable.")
    if not role_map:
        return _error(404, "SCIM Groups are not configured.")
    return cast(Mapping[str, list[str]], role_map)


def _group_resource(record: ScimGroupRecord, request: Request) -> dict[str, object]:
    base_url = str(request.base_url).rstrip("/")
    return {
        "schemas": [SCIM_GROUP_SCHEMA],
        "id": str(record.id),
        "displayName": record.display_name,
        "members": [
            {
                "value": str(member_id),
                "$ref": f"{base_url}/scim/v2/Users/{member_id}",
                "type": "User",
            }
            for member_id in record.member_ids
        ],
        "meta": {
            "resourceType": "Group",
            "created": record.created_at.isoformat(),
            "lastModified": record.last_modified.isoformat(),
            "location": f"{base_url}/scim/v2/Groups/{record.id}",
        },
    }


def _parse_group_member(value: object) -> uuid.UUID | None:
    if not isinstance(value, dict) or set(value) - {"value", "$ref", "display", "type"}:
        return None
    member_type = value.get("type")
    if member_type is not None and (
        not isinstance(member_type, str) or member_type.casefold() != "user"
    ):
        return None
    member_id = value.get("value")
    if not isinstance(member_id, str):
        return None
    try:
        return uuid.UUID(member_id)
    except ValueError:
        return None


def _parse_group_members(value: object) -> tuple[uuid.UUID, ...] | None:
    if not isinstance(value, list) or len(value) > 1000:
        return None
    member_ids: list[uuid.UUID] = []
    for item in value:
        member_id = _parse_group_member(item)
        if member_id is None:
            return None
        member_ids.append(member_id)
    return tuple(dict.fromkeys(member_ids))


def _list_response(
    records: tuple[ScimGroupRecord, ...], request: Request, *, total: int, start_index: int
) -> JSONResponse:
    return _response(
        {
            "schemas": [SCIM_LIST_SCHEMA],
            "totalResults": total,
            "startIndex": start_index,
            "itemsPerPage": len(records),
            "Resources": [_group_resource(record, request) for record in records],
        }
    )


@router.get("/Users")
async def list_users(
    request: Request,
    filter: str | None = None,
    start_index_value: str = Query(default="1", alias="startIndex"),
    count_value: str = Query(default="100", alias="count"),
) -> JSONResponse:
    organization_id = await _authorized(request)
    if isinstance(organization_id, JSONResponse):
        return organization_id
    user_name: str | None = None
    if filter is not None:
        match = _USER_NAME_FILTER.fullmatch(filter)
        if match is None:
            return _error(
                400, 'Only userName eq "email" filters are supported.', scim_type="invalidFilter"
            )
        user_name = normalize_email(match.group(1))
    if not (_INTEGER.fullmatch(start_index_value) and _INTEGER.fullmatch(count_value)):
        return _error(400, "startIndex and count must be integers.", scim_type="invalidValue")
    start_index, count = int(start_index_value), int(count_value)
    if not 1 <= start_index <= _MAX_INDEX or count > 100:
        return _error(
            400,
            "startIndex must be between 1 and 2147483647 and count between 0 and 100.",
            scim_type="invalidValue",
        )
    total, records = await _repo(request).list_users(
        organization_id=organization_id,
        user_name=user_name,
        start_index=start_index,
        count=count,
    )
    return _response(
        {
            "schemas": [SCIM_LIST_SCHEMA],
            "totalResults": total,
            "startIndex": start_index,
            "itemsPerPage": len(records),
            "Resources": [_resource(record, request) for record in records],
        }
    )


@router.get("/Users/{user_id}")
async def get_user(user_id: str, request: Request) -> JSONResponse:
    organization_id = await _authorized(request)
    if isinstance(organization_id, JSONResponse):
        return organization_id
    try:
        parsed_user_id = uuid.UUID(user_id)
    except ValueError:
        return _error(404, "SCIM user not found.")
    record = await _repo(request).get_user(organization_id=organization_id, user_id=parsed_user_id)
    if record is None:
        return _error(404, "SCIM user not found.")
    return _response(_resource(record, request))


@router.get("/Groups")
async def list_groups(
    request: Request,
    filter: str | None = None,
    start_index_value: str = Query(default="1", alias="startIndex"),
    count_value: str = Query(default="100", alias="count"),
) -> JSONResponse:
    role_map = await _group_role_map(request)
    if isinstance(role_map, JSONResponse):
        return role_map
    organization_id = cast(uuid.UUID, request.app.state.settings.scim_organization_id)
    display_name: str | None = None
    if filter is not None:
        match = _GROUP_NAME_FILTER.fullmatch(filter)
        if match is None:
            return _error(
                400, 'Only displayName eq "name" filters are supported.', scim_type="invalidFilter"
            )
        display_name = match.group(1)
        if display_name not in role_map:
            return _list_response((), request, total=0, start_index=1)
    if not (_INTEGER.fullmatch(start_index_value) and _INTEGER.fullmatch(count_value)):
        return _error(400, "startIndex and count must be integers.", scim_type="invalidValue")
    start_index, count = int(start_index_value), int(count_value)
    if not 1 <= start_index <= _MAX_INDEX or count > 100:
        return _error(
            400,
            "startIndex must be between 1 and 2147483647 and count between 0 and 100.",
            scim_type="invalidValue",
        )
    total, records = await _repo(request).list_groups(
        organization_id=organization_id,
        display_name=display_name,
        start_index=start_index,
        count=count,
    )
    return _list_response(records, request, total=total, start_index=start_index)


@router.get("/Groups/{group_id}")
async def get_group(group_id: str, request: Request) -> JSONResponse:
    role_map = await _group_role_map(request)
    if isinstance(role_map, JSONResponse):
        return role_map
    try:
        parsed_group_id = uuid.UUID(group_id)
    except ValueError:
        return _error(404, "SCIM group not found.")
    record = await _repo(request).get_group(
        organization_id=cast(uuid.UUID, request.app.state.settings.scim_organization_id),
        group_id=parsed_group_id,
    )
    if record is None or record.display_name not in role_map:
        return _error(404, "SCIM group not found.")
    return _response(_group_resource(record, request))


@router.post("/Groups")
async def create_group(request: Request) -> JSONResponse:
    role_map = await _group_role_map(request)
    if isinstance(role_map, JSONResponse):
        return role_map
    try:
        body = await request.json()
    except ValueError:
        return _error(400, "Request body must be valid JSON.", scim_type="invalidSyntax")
    if (
        not isinstance(body, dict)
        or set(body) - {"schemas", "displayName", "members", "externalId"}
        or body.get("schemas") != [SCIM_GROUP_SCHEMA]
        or not isinstance(body.get("displayName"), str)
        or not body["displayName"].strip()
        or len(body["displayName"]) > 100
    ):
        return _error(400, "A SCIM Group requires a displayName.", scim_type="invalidValue")
    display_name = body["displayName"]
    if display_name not in role_map:
        return _error(
            400, "Only configured SCIM group names are accepted.", scim_type="invalidValue"
        )
    if "externalId" in body and (
        not isinstance(body["externalId"], str) or len(body["externalId"]) > 100
    ):
        return _error(400, "externalId must be a string of at most 100 characters.")
    member_ids = _parse_group_members(body.get("members", []))
    if member_ids is None:
        return _error(400, "Group members must reference existing users.", scim_type="invalidValue")
    try:
        record = await _repo(request).create_group(
            organization_id=cast(uuid.UUID, request.app.state.settings.scim_organization_id),
            display_name=display_name,
            member_ids=member_ids,
            role_map=role_map,
            now=datetime.now(UTC),
        )
    except ScimGroupConflict:
        return _error(409, "SCIM group already exists.", scim_type="uniqueness")
    except ScimGroupInvalidMember:
        return _error(
            400,
            "Group members must be active users in this organization.",
            scim_type="invalidValue",
        )
    except ScimGroupNotAllowed:
        return _error(
            400, "Only configured SCIM group names are accepted.", scim_type="invalidValue"
        )
    return _response(
        _group_resource(record, request),
        status=201,
        headers={"Location": f"{str(request.base_url).rstrip('/')}/scim/v2/Groups/{record.id}"},
    )


@dataclass(frozen=True, slots=True)
class _GroupPatch:
    add_ids: tuple[uuid.UUID, ...]
    remove_ids: tuple[uuid.UUID, ...] | None  # None removes every current member
    display_name: str | None


def _group_patch_members(body: object) -> _GroupPatch | None:
    if not isinstance(body, dict) or body.get("schemas") != [SCIM_PATCH_SCHEMA]:
        return None
    operations = body.get("Operations")
    if not isinstance(operations, list) or not operations or len(operations) > 10:
        return None
    add_ids: set[uuid.UUID] = set()
    remove_ids: set[uuid.UUID] = set()
    remove_all = False
    display_name: str | None = None
    members_paths = {"members", f"{SCIM_GROUP_SCHEMA}:members".casefold()}
    name_paths = {"displayname", f"{SCIM_GROUP_SCHEMA}:displayname".casefold()}
    for operation in operations:
        if not isinstance(operation, dict) or set(operation) - {"op", "path", "value"}:
            return None
        action = operation.get("op")
        path = operation.get("path")
        if not isinstance(action, str) or not isinstance(path, str):
            return None
        action = action.casefold()
        if action not in {"add", "remove", "replace"}:
            return None
        member_filter = _GROUP_MEMBER_FILTER.fullmatch(path)
        normalized_path = path.casefold()
        member_ids: tuple[uuid.UUID, ...] | None
        if member_filter is not None:
            if action != "remove" or "value" in operation:
                return None
            try:
                member_ids = (uuid.UUID(member_filter.group(1)),)
            except ValueError:
                return None
        elif normalized_path in name_paths:
            value = operation.get("value")
            if action != "replace" or not isinstance(value, str) or not value.strip():
                return None
            display_name = value
            continue
        elif normalized_path in members_paths:
            if action == "remove" and "value" not in operation:
                remove_all = True
                add_ids.clear()
                remove_ids.clear()
                continue
            raw = operation.get("value")
            member_ids = _parse_group_members(raw if isinstance(raw, list) else [raw])
            if member_ids is None or (action == "add" and not member_ids):
                return None
            if action == "replace":
                # Entra and Okta replace the full member list: drop everyone, then add these.
                remove_all = True
                remove_ids.clear()
                add_ids = set(member_ids)
                continue
        else:
            return None
        if action == "add":
            add_ids.update(member_ids)
            remove_ids.difference_update(member_ids)
        elif remove_all:
            add_ids.difference_update(member_ids)
        else:
            remove_ids.update(member_ids)
            add_ids.difference_update(member_ids)
    return _GroupPatch(
        tuple(sorted(add_ids, key=str)),
        None if remove_all else tuple(sorted(remove_ids, key=str)),
        display_name,
    )


@router.patch("/Groups/{group_id}")
async def patch_group(group_id: str, request: Request) -> JSONResponse:
    role_map = await _group_role_map(request)
    if isinstance(role_map, JSONResponse):
        return role_map
    try:
        parsed_group_id = uuid.UUID(group_id)
    except ValueError:
        return _error(404, "SCIM group not found.")
    try:
        body = await request.json()
    except ValueError:
        return _error(400, "Request body must be valid JSON.", scim_type="invalidSyntax")
    patch_members = _group_patch_members(body)
    if patch_members is None:
        return _error(
            400,
            "Only SCIM PatchOp add/remove/replace operations on members are supported.",
            scim_type="invalidSyntax",
        )
    if patch_members.display_name is not None:
        if patch_members.display_name not in role_map:
            return _error(
                400, "Only configured SCIM group names are accepted.", scim_type="invalidValue"
            )
        current = await _repo(request).get_group(
            organization_id=cast(uuid.UUID, request.app.state.settings.scim_organization_id),
            group_id=parsed_group_id,
        )
        if current is None or current.display_name not in role_map:
            return _error(404, "SCIM group not found.")
        if current.display_name != patch_members.display_name:
            return _error(409, "SCIM groups cannot be renamed.", scim_type="mutability")
    try:
        record = await _repo(request).patch_group_members(
            organization_id=cast(uuid.UUID, request.app.state.settings.scim_organization_id),
            group_id=parsed_group_id,
            add_member_ids=patch_members.add_ids,
            remove_member_ids=patch_members.remove_ids,
            role_map=role_map,
            now=datetime.now(UTC),
        )
    except ScimGroupInvalidMember:
        return _error(
            400,
            "Group members must be active users in this organization.",
            scim_type="invalidValue",
        )
    except ScimGroupNotAllowed:
        return _error(404, "SCIM group not found.")
    if record is None:
        return _error(404, "SCIM group not found.")
    return _response(_group_resource(record, request))


@router.delete("/Groups/{group_id}")
async def delete_group(group_id: str, request: Request) -> Response:
    role_map = await _group_role_map(request)
    if isinstance(role_map, JSONResponse):
        return role_map
    try:
        parsed_group_id = uuid.UUID(group_id)
    except ValueError:
        return _error(404, "SCIM group not found.")
    try:
        deleted = await _repo(request).delete_group(
            organization_id=cast(uuid.UUID, request.app.state.settings.scim_organization_id),
            group_id=parsed_group_id,
            role_map=role_map,
            now=datetime.now(UTC),
        )
    except ScimGroupNotAllowed:
        return _error(404, "SCIM group not found.")
    return Response(status_code=204) if deleted else _error(404, "SCIM group not found.")


def _is_deactivation_patch(body: object) -> bool:
    if not isinstance(body, dict) or body.get("schemas") != [SCIM_PATCH_SCHEMA]:
        return False
    operations = body.get("Operations")
    if not isinstance(operations, list) or not operations or len(operations) > 10:
        return False
    for operation in operations:
        if not isinstance(operation, dict) or set(operation) - {"op", "path", "value"}:
            return False
        if not isinstance(operation.get("op"), str) or operation["op"].casefold() != "replace":
            return False
        path = operation.get("path")
        value = operation.get("value")
        if path is None:
            if not isinstance(value, dict) or len(value) != 1:
                return False
            attribute, active_value = next(iter(value.items()))
            if not isinstance(attribute, str) or attribute.casefold() != "active":
                return False
        else:
            if not isinstance(path, str) or path.casefold() not in {
                "active",
                f"{SCIM_USER_SCHEMA}:active".casefold(),
            }:
                return False
            active_value = value
        # Entra ID sends booleans as strings ("False").
        if not (
            active_value is False
            or (isinstance(active_value, str) and active_value.strip().casefold() == "false")
        ):
            return False
    return True


@router.patch("/Users/{user_id}")
async def patch_user(user_id: str, request: Request) -> JSONResponse:
    organization_id = await _authorized(request)
    if isinstance(organization_id, JSONResponse):
        return organization_id
    try:
        parsed_user_id = uuid.UUID(user_id)
    except ValueError:
        return _error(404, "SCIM user not found.")
    try:
        body = await request.json()
    except ValueError:
        return _error(400, "Request body must be valid JSON.", scim_type="invalidSyntax")
    if not _is_deactivation_patch(body):
        return _error(
            400,
            "Only SCIM PatchOp replace active=false is supported.",
            scim_type="invalidSyntax",
        )
    try:
        record = await _repo(request).deactivate_user(
            organization_id=organization_id,
            user_id=parsed_user_id,
            now=datetime.now(UTC),
        )
    except LastAdministrator:
        return _error(
            409, "The organization's last OrgAdmin cannot be deprovisioned.", scim_type="mutability"
        )
    except LastOwner:
        return _error(
            409, "The organization's last Owner cannot be deprovisioned.", scim_type="mutability"
        )
    if record is None:
        return _error(404, "SCIM user not found.")
    return _response(_resource(record, request))
