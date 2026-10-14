"""In-app notification inbox and the org-scoped SSE stream (M13, ADR-010)."""

from __future__ import annotations

import hmac
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Protocol, cast

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import Field
from sqlalchemy import func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.events.models import DomainEvent
from treasurypilot_api.identity.api import ApiModel, _authenticated
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import User
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.notifications.models import (
    EmailDeliveryMode,
    Notification,
    NotificationEmailPreference,
)
from treasurypilot_api.notifications.stream import (
    EVENT_STREAM_TYPES,
    StreamBatch,
    StreamCursor,
    StreamedEvent,
    StreamedNotification,
    StreamOptions,
    event_stream,
    parse_cursor,
)
from treasurypilot_core.notifications import unsubscribe_signature

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_NIL_UUID = uuid.UUID(int=0)
# Payload keys safe to forward on the stream. Everything else (for example the
# maker-checker ``excludeUserIds`` or ``creatorId``) stays server-side.
_STREAM_ID_KEYS = ("requestId", "planId", "operationId", "reviewItemId")


class NotificationView(ApiModel):
    id: uuid.UUID
    event_id: uuid.UUID
    type: str
    title: str
    body: str
    link: str
    severity: str
    created_at: datetime
    read_at: datetime | None

    @classmethod
    def from_row(cls, row: Notification) -> NotificationView:
        return cls(
            id=row.id,
            event_id=row.event_id,
            type=row.event_type,
            title=row.title,
            body=row.body,
            link=row.link,
            severity=row.severity,
            created_at=row.created_at,
            read_at=row.read_at,
        )


class NotificationList(ApiModel):
    items: list[NotificationView]
    unread_count: int


class MarkReadRequest(ApiModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class MarkReadResponse(ApiModel):
    updated: int


class EmailPreferenceRequest(ApiModel):
    delivery_mode: EmailDeliveryMode


class EmailPreferenceView(ApiModel):
    delivery_mode: EmailDeliveryMode


class NotificationRepository(Protocol):
    async def list_notifications(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID, unread: bool, limit: int
    ) -> tuple[tuple[Notification, ...], int]: ...

    async def mark_read(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID, ids: list[uuid.UUID]
    ) -> int: ...

    async def initial_cursor(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> StreamCursor: ...

    async def stream_batch(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        cursor: StreamCursor,
        limit: int,
    ) -> StreamBatch: ...


class SqlAlchemyNotificationRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list_notifications(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID, unread: bool, limit: int
    ) -> tuple[tuple[Notification, ...], int]:
        scope = (Notification.org_id == organization_id, Notification.user_id == user_id)
        async with self._sessions() as session:
            statement = select(Notification).where(*scope, Notification.deliver_at <= func.now())
            if unread:
                statement = statement.where(Notification.read_at.is_(None))
            rows = await session.scalars(
                statement.order_by(Notification.deliver_at.desc(), Notification.id.desc()).limit(
                    limit
                )
            )
            unread_count = await session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    *scope,
                    Notification.read_at.is_(None),
                    Notification.deliver_at <= func.now(),
                )
            )
            return tuple(rows), int(unread_count or 0)

    async def mark_read(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID, ids: list[uuid.UUID]
    ) -> int:
        # Ids that are not the caller's own in this org simply match nothing, so
        # the response never reveals whether someone else's notification exists.
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(Notification)
                .where(
                    Notification.id.in_(ids),
                    Notification.org_id == organization_id,
                    Notification.user_id == user_id,
                    # Deferred (quiet hours) rows are unseen, so they cannot be read yet.
                    Notification.deliver_at <= func.now(),
                )
                # Idempotent: an already-read row keeps its first read time.
                .values(read_at=func.coalesce(Notification.read_at, func.now()))
                .returning(Notification.id)
            )
            return len(result.all())

    async def initial_cursor(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> StreamCursor:
        """Start a fresh connection at "now": history comes from GET /notifications."""
        async with self._sessions() as session:
            last_event = await session.scalar(
                select(DomainEvent.id)
                .where(DomainEvent.org_id == organization_id)
                .order_by(DomainEvent.id.desc())
                .limit(1)
            )
            last_notification = (
                await session.execute(
                    select(Notification.deliver_at, Notification.id)
                    .where(
                        Notification.org_id == organization_id,
                        Notification.user_id == user_id,
                        Notification.deliver_at <= func.now(),
                    )
                    .order_by(Notification.deliver_at.desc(), Notification.id.desc())
                    .limit(1)
                )
            ).first()
        return StreamCursor(
            event_id=last_event or _NIL_UUID,
            notification_at=last_notification[0] if last_notification else _EPOCH,
            notification_id=last_notification[1] if last_notification else _NIL_UUID,
        )

    async def stream_batch(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        cursor: StreamCursor,
        limit: int,
    ) -> StreamBatch:
        async with self._sessions() as session:
            events = (
                await session.scalars(
                    select(DomainEvent)
                    .where(
                        DomainEvent.org_id == organization_id,
                        DomainEvent.id > cursor.event_id,
                        DomainEvent.entity_type.in_(tuple(EVENT_STREAM_TYPES)),
                    )
                    .order_by(DomainEvent.id)
                    .limit(limit)
                )
            ).all()
            notifications = (
                await session.scalars(
                    select(Notification)
                    .where(
                        Notification.org_id == organization_id,
                        Notification.user_id == user_id,
                        Notification.deliver_at <= func.now(),
                        tuple_(Notification.deliver_at, Notification.id)
                        > tuple_(cursor.notification_at, cursor.notification_id),
                    )
                    .order_by(Notification.deliver_at, Notification.id)
                    .limit(limit)
                )
            ).all()
        return StreamBatch(
            events=tuple(
                StreamedEvent(
                    id=event.id,
                    event_type=event.event_type,
                    entity_type=event.entity_type,
                    entity_id=event.entity_id,
                    treasury_id=event.treasury_id,
                    created_at=event.created_at,
                    ids={
                        key: str(event.payload[key])
                        for key in _STREAM_ID_KEYS
                        if isinstance(event.payload.get(key), str)
                    },
                )
                for event in events
            ),
            notifications=tuple(
                StreamedNotification(
                    id=row.id,
                    event_id=row.event_id,
                    created_at=row.deliver_at,  # cursor position: see Notification.deliver_at
                    severity=row.severity,
                )
                for row in notifications
            ),
        )


def _repository(request: Request) -> NotificationRepository:
    repository = getattr(request.app.state, "notification_repository", None)
    if repository is None:
        raise AuthFailure(
            status=503,
            code="NOTIFICATIONS_UNAVAILABLE",
            title="Notifications unavailable",
            detail="Notification storage is not configured.",
        )
    return cast(NotificationRepository, repository)


def stream_options(request: Request) -> StreamOptions:
    return cast(
        StreamOptions, getattr(request.app.state, "stream_options", None) or StreamOptions()
    )


router = APIRouter(prefix="/v1/orgs/{organization_id}", tags=["notifications"])
email_router = APIRouter(prefix="/v1/me/notifications", tags=["notifications"])


@router.get(
    "/notifications",
    response_model=NotificationList,
    openapi_extra={"x-organization-scoped": True},
)
async def list_notifications(
    request: Request,
    unread: bool = False,
    limit: int = Query(default=50, ge=1, le=100),  # noqa: B008
    member: MemberAccess = Depends(require_member),  # noqa: B008
) -> NotificationList:
    rows, unread_count = await _repository(request).list_notifications(
        organization_id=member.organization_id,
        user_id=member.user_id,
        unread=unread,
        limit=limit,
    )
    return NotificationList(
        items=[NotificationView.from_row(row) for row in rows], unread_count=unread_count
    )


@router.post(
    "/notifications/read",
    response_model=MarkReadResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def mark_notifications_read(
    payload: MarkReadRequest,
    request: Request,
    member: MemberAccess = Depends(require_member),  # noqa: B008
) -> MarkReadResponse:
    updated = await _repository(request).mark_read(
        organization_id=member.organization_id,
        user_id=member.user_id,
        ids=list(dict.fromkeys(payload.ids)),
    )
    return MarkReadResponse(updated=updated)


@router.post(
    "/notifications/{notification_id}/read",
    response_model=MarkReadResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def mark_notification_read(
    notification_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(require_member),  # noqa: B008
) -> MarkReadResponse:
    """Mark one notification read; idempotent for the owner, 404 for anyone else."""
    updated = await _repository(request).mark_read(
        organization_id=member.organization_id,
        user_id=member.user_id,
        ids=[notification_id],
    )
    if updated == 0:
        raise AuthFailure(
            status=404,
            code="NOTIFICATION_NOT_FOUND",
            title="Notification not found",
            detail="The notification does not exist or belongs to another user.",
        )
    return MarkReadResponse(updated=updated)


@router.get(
    "/events",
    response_class=StreamingResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def stream_events(
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),  # noqa: B008
    member: MemberAccess = Depends(require_member),  # noqa: B008
    options: StreamOptions = Depends(stream_options),  # noqa: B008
) -> StreamingResponse:
    """Server-sent events for this organization; resume with ``Last-Event-ID``."""
    repository = _repository(request)
    cursor = parse_cursor(last_event_id)
    resumed = cursor is not None
    if cursor is None:
        cursor = await repository.initial_cursor(
            organization_id=member.organization_id, user_id=member.user_id
        )

    async def frames() -> AsyncIterator[str]:
        async for frame in event_stream(
            repository,
            organization_id=member.organization_id,
            user_id=member.user_id,
            cursor=cursor,
            options=options,
            is_disconnected=request.is_disconnected,
            resumed=resumed,
        ):
            yield frame

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _email_sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    sessions = getattr(request.app.state, "request_sessions", None)
    if sessions is None:
        raise AuthFailure(
            status=503,
            code="NOTIFICATIONS_UNAVAILABLE",
            title="Notifications unavailable",
            detail="Email preferences are not configured.",
        )
    return cast(async_sessionmaker[AsyncSession], sessions)


@email_router.get("/email", response_model=EmailPreferenceView)
async def get_email_preference(request: Request) -> EmailPreferenceView:
    access = await _authenticated(request)
    async with _email_sessions(request)() as session:
        row = await session.get(NotificationEmailPreference, access.user.id)
    return EmailPreferenceView(
        delivery_mode=EmailDeliveryMode(row.delivery_mode) if row else EmailDeliveryMode.IMMEDIATE
    )


@email_router.put("/email", response_model=EmailPreferenceView)
async def set_email_preference(
    payload: EmailPreferenceRequest, request: Request
) -> EmailPreferenceView:
    access = await _authenticated(request, require_csrf=True)
    async with _email_sessions(request)() as session, session.begin():
        row = await session.get(NotificationEmailPreference, access.user.id)
        if row is None:
            session.add(
                NotificationEmailPreference(
                    user_id=access.user.id, delivery_mode=payload.delivery_mode.value
                )
            )
        else:
            row.delivery_mode = payload.delivery_mode.value
            row.updated_at = datetime.now(UTC)
    return EmailPreferenceView(delivery_mode=payload.delivery_mode)


def _invalid_unsubscribe_token() -> AuthFailure:
    return AuthFailure(
        status=400,
        code="INVALID_UNSUBSCRIBE_TOKEN",
        title="Invalid unsubscribe link",
        detail="This unsubscribe link is invalid.",
    )


@email_router.post("/email/unsubscribe", status_code=204, response_class=Response)
async def unsubscribe_email(request: Request, user_id: uuid.UUID, signature: str) -> Response:
    """Token-authenticated unsubscribe. CRITICAL/security mail remains mandatory."""
    secret = getattr(request.app.state.settings, "session_secret", None)
    try:
        # No local-development fallback: a known default secret would make links forgeable.
        expected = unsubscribe_signature(
            user_id, secret.get_secret_value() if secret is not None else ""
        )
    except ValueError:
        raise AuthFailure(
            status=503,
            code="NOTIFICATIONS_UNAVAILABLE",
            title="Notifications unavailable",
            detail="Unsubscribe links are not configured.",
        ) from None
    # Compare bytes: compare_digest raises TypeError on non-ASCII str.
    if not hmac.compare_digest(signature.encode(), expected.encode()):
        raise _invalid_unsubscribe_token()
    async with _email_sessions(request)() as session, session.begin():
        if await session.get(User, user_id) is None:
            return Response(status_code=204)
        row = await session.get(NotificationEmailPreference, user_id)
        if row is None:
            session.add(NotificationEmailPreference(user_id=user_id, delivery_mode="off"))
        else:
            row.delivery_mode = EmailDeliveryMode.OFF.value
            row.updated_at = datetime.now(UTC)
    return Response(status_code=204)
