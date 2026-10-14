from __future__ import annotations

import hmac
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
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
    Session,
    User,
    UserStatus,
)

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
_USER_NAME_FILTER = re.compile(r'^\s*userName\s+eq\s+"([^"\\]{1,320})"\s*$', re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ScimUserRecord:
    id: uuid.UUID
    user_name: str
    display_name: str | None
    active: bool
    created_at: datetime
    last_modified: datetime


class ScimIdentityRepository(Protocol):
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


class SqlAlchemyScimIdentityRepository:
    """Tenant-scoped SCIM reads and membership deprovisioning."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

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


def _authorized(request: Request) -> uuid.UUID | JSONResponse:
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
        return _error(
            401,
            "A valid SCIM bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if getattr(request.app.state, "scim_repository", None) is None:
        return _error(503, "SCIM storage is not configured.")
    return cast(uuid.UUID, organization_id)


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


@router.get("/Users")
async def list_users(
    request: Request,
    filter: str | None = None,
    start_index_value: str = Query(default="1", alias="startIndex"),
    count_value: str = Query(default="100", alias="count"),
) -> JSONResponse:
    organization_id = _authorized(request)
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
    try:
        start_index = int(start_index_value)
        count = int(count_value)
    except ValueError:
        return _error(400, "startIndex and count must be integers.", scim_type="invalidValue")
    if start_index < 1 or not 0 <= count <= 100:
        return _error(
            400,
            "startIndex must be positive and count must be between 0 and 100.",
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
    organization_id = _authorized(request)
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
        if active_value is not False:
            return False
    return True


@router.patch("/Users/{user_id}")
async def patch_user(user_id: str, request: Request) -> JSONResponse:
    organization_id = _authorized(request)
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
