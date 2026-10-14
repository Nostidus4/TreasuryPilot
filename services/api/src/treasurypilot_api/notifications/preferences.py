"""Authenticated read/write API for a user's notification preferences."""

from __future__ import annotations

import uuid
from datetime import time
from typing import Protocol, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request
from pydantic import Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.api import ApiModel, _authenticated
from treasurypilot_api.identity.auth import AuthFailure, SessionAccess
from treasurypilot_api.notifications.models import NotificationPreference
from treasurypilot_core.notifications import NotificationCategory, NotificationChannel

_DEFAULT_CHANNELS: dict[NotificationChannel, bool] = {
    channel: True for channel in NotificationChannel
}
_DEFAULT_CATEGORIES: dict[NotificationCategory, bool] = {
    category: True for category in NotificationCategory
}


class NotificationPreferencesView(ApiModel):
    channels: dict[NotificationChannel, bool]
    categories: dict[NotificationCategory, bool]
    quiet_hours_start: time | None
    quiet_hours_end: time | None
    timezone: str

    @classmethod
    def defaults(cls) -> NotificationPreferencesView:
        return cls(
            channels=_DEFAULT_CHANNELS,
            categories=_DEFAULT_CATEGORIES,
            quiet_hours_start=None,
            quiet_hours_end=None,
            timezone="UTC",
        )

    @classmethod
    def from_row(cls, row: NotificationPreference) -> NotificationPreferencesView:
        return cls(
            channels={
                **_DEFAULT_CHANNELS,
                **{NotificationChannel(key): value for key, value in row.channels.items()},
            },
            categories={
                **_DEFAULT_CATEGORIES,
                **{NotificationCategory(key): value for key, value in row.categories.items()},
            },
            quiet_hours_start=row.quiet_hours_start,
            quiet_hours_end=row.quiet_hours_end,
            timezone=row.timezone,
        )


class UpdateNotificationPreferences(ApiModel):
    channels: dict[NotificationChannel, bool] = Field(default_factory=lambda: _DEFAULT_CHANNELS)
    categories: dict[NotificationCategory, bool] = Field(
        default_factory=lambda: _DEFAULT_CATEGORIES
    )
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_valid(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def preferences_are_valid(self) -> UpdateNotificationPreferences:
        if (self.quiet_hours_start is None) != (self.quiet_hours_end is None):
            raise ValueError("quiet_hours_start and quiet_hours_end must be set together")
        if self.quiet_hours_start == self.quiet_hours_end and self.quiet_hours_start is not None:
            raise ValueError("quiet hours must have a non-zero duration")
        if self.categories.get(NotificationCategory.MANDATORY, True) is False:
            raise ValueError("mandatory notification category cannot be muted")
        return self


class NotificationPreferencesRepository(Protocol):
    async def get(self, *, user_id: uuid.UUID) -> NotificationPreference | None: ...

    async def put(
        self, *, user_id: uuid.UUID, preferences: UpdateNotificationPreferences
    ) -> NotificationPreference: ...


class SqlAlchemyNotificationPreferencesRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, *, user_id: uuid.UUID) -> NotificationPreference | None:
        async with self._sessions() as session:
            return await session.get(NotificationPreference, user_id)

    async def put(
        self, *, user_id: uuid.UUID, preferences: UpdateNotificationPreferences
    ) -> NotificationPreference:
        async with self._sessions() as session, session.begin():
            row = await session.get(NotificationPreference, user_id)
            if row is None:
                row = NotificationPreference(user_id=user_id)
                session.add(row)
            row.channels = {
                NotificationChannel(key).value: value for key, value in preferences.channels.items()
            }
            row.categories = {
                NotificationCategory(key).value: value
                for key, value in preferences.categories.items()
            }
            row.quiet_hours_start = preferences.quiet_hours_start
            row.quiet_hours_end = preferences.quiet_hours_end
            row.timezone = preferences.timezone
            await session.flush()
            await session.refresh(row)
            return row


def _repository(request: Request) -> NotificationPreferencesRepository:
    repository = getattr(request.app.state, "notification_preferences_repository", None)
    if repository is None:
        raise AuthFailure(
            status=503,
            code="NOTIFICATIONS_UNAVAILABLE",
            title="Notifications unavailable",
            detail="Notification preference storage is not configured.",
        )
    return cast(NotificationPreferencesRepository, repository)


async def _preference_access(request: Request) -> SessionAccess:
    return await _authenticated(
        request, require_csrf=request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
    )


router = APIRouter(prefix="/v1/me/notification-preferences", tags=["notifications"])


@router.get("", response_model=NotificationPreferencesView)
async def get_notification_preferences(
    request: Request,
    access: SessionAccess = Depends(_preference_access),  # noqa: B008
) -> NotificationPreferencesView:
    row = await _repository(request).get(user_id=access.user.id)
    return (
        NotificationPreferencesView.from_row(row) if row else NotificationPreferencesView.defaults()
    )


@router.put("", response_model=NotificationPreferencesView)
async def put_notification_preferences(
    preferences: UpdateNotificationPreferences,
    request: Request,
    access: SessionAccess = Depends(_preference_access),  # noqa: B008
) -> NotificationPreferencesView:
    row = await _repository(request).put(user_id=access.user.id, preferences=preferences)
    return NotificationPreferencesView.from_row(row)
