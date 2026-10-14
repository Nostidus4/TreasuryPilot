from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from treasurypilot_api.notifications.models import Notification
from treasurypilot_api.notifications.preferences import (
    NotificationPreferencesView,
    SqlAlchemyNotificationPreferencesRepository,
    UpdateNotificationPreferences,
    _preference_access,
    router,
)
from treasurypilot_api.notifications.routes import SqlAlchemyNotificationRepository
from treasurypilot_core.notifications import NotificationCategory, NotificationChannel

USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000123")


class _Repository:
    def __init__(self) -> None:
        self.row: SimpleNamespace | None = None

    async def get(self, *, user_id: uuid.UUID) -> SimpleNamespace | None:
        assert user_id == USER_ID
        return self.row

    async def put(self, *, user_id: uuid.UUID, preferences) -> SimpleNamespace:
        assert user_id == USER_ID
        self.row = SimpleNamespace(
            channels={
                NotificationChannel(key).value: value for key, value in preferences.channels.items()
            },
            categories={
                NotificationCategory(key).value: value
                for key, value in preferences.categories.items()
            },
            quiet_hours_start=preferences.quiet_hours_start,
            quiet_hours_end=preferences.quiet_hours_end,
            timezone=preferences.timezone,
        )
        return self.row


def _client() -> tuple[TestClient, _Repository]:
    app = FastAPI()
    repository = _Repository()
    app.state.notification_preferences_repository = repository
    app.include_router(router)
    app.dependency_overrides[_preference_access] = lambda: SimpleNamespace(
        user=SimpleNamespace(id=USER_ID)
    )
    return TestClient(app), repository


def test_preferences_default_on_and_can_store_quiet_hours() -> None:
    client, _ = _client()

    default = client.get("/v1/me/notification-preferences")
    assert default.status_code == 200
    assert default.json()["channels"] == {
        "in_app": True,
        "email": True,
        "telegram": True,
        "slack": True,
        "lark": True,
        "wecom": True,
    }
    assert default.json()["quietHoursStart"] is None

    updated = client.put(
        "/v1/me/notification-preferences",
        json={
            "channels": {"in_app": False, "email": True, "telegram": False},
            "categories": {"approvals": False},
            "quietHoursStart": "22:00:00",
            "quietHoursEnd": "07:00:00",
            "timezone": "Asia/Ho_Chi_Minh",
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["channels"]["in_app"] is False
    assert body["categories"]["approvals"] is False
    assert body["quietHoursStart"] == "22:00:00"
    assert body["timezone"] == "Asia/Ho_Chi_Minh"


def test_api_rejects_muting_mandatory_category_and_partial_quiet_hours() -> None:
    client, _ = _client()

    muted_mandatory = client.put(
        "/v1/me/notification-preferences", json={"categories": {"mandatory": False}}
    )
    assert muted_mandatory.status_code == 422

    unpaired_hours = client.put(
        "/v1/me/notification-preferences", json={"quietHoursStart": "22:00:00"}
    )
    assert unpaired_hours.status_code == 422


def test_update_model_uses_aware_category_defaults() -> None:
    client, repository = _client()
    response = client.put("/v1/me/notification-preferences", json={})

    assert response.status_code == 200
    assert repository.row is not None
    assert repository.row.categories["mandatory"] is True
    assert repository.row.channels["in_app"] is True


def test_api_rejects_timezone_aware_quiet_hours() -> None:
    client, _ = _client()

    response = client.put(
        "/v1/me/notification-preferences",
        json={"quietHoursStart": "22:00:00+07:00", "quietHoursEnd": "07:00:00"},
    )

    assert response.status_code == 422


def test_view_ignores_unknown_stored_channel_and_category_keys() -> None:
    row = SimpleNamespace(
        channels={"in_app": False, "sms": True},
        categories={"approvals": False, "legacy": True},
        quiet_hours_start=None,
        quiet_hours_end=None,
        timezone="UTC",
    )

    view = NotificationPreferencesView.from_row(row)  # type: ignore[arg-type]

    assert view.channels[NotificationChannel.IN_APP] is False
    assert view.categories[NotificationCategory.APPROVALS] is False
    assert len(view.channels) == len(NotificationChannel)


class _Session:
    def __init__(self, row: Any) -> None:
        self.row = row

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def begin(self) -> _Session:
        return self

    async def get(self, *_: object) -> Any:
        return self.row

    async def flush(self) -> None:
        return None

    async def refresh(self, *_: object) -> None:
        return None


def test_put_leaves_omitted_fields_unchanged() -> None:
    row = SimpleNamespace(
        channels={"in_app": False},
        categories={"approvals": False},
        quiet_hours_start="22:00",
        quiet_hours_end="07:00",
        timezone="Asia/Ho_Chi_Minh",
    )
    repository = SqlAlchemyNotificationPreferencesRepository(lambda: _Session(row))  # type: ignore[arg-type]

    asyncio.run(
        repository.put(
            user_id=USER_ID,
            preferences=UpdateNotificationPreferences.model_validate({"timezone": "UTC"}),
        )
    )

    assert row.timezone == "UTC"
    assert row.channels == {"in_app": False}
    assert row.categories == {"approvals": False}
    assert row.quiet_hours_start == "22:00"

    asyncio.run(
        repository.put(
            user_id=USER_ID,
            preferences=UpdateNotificationPreferences.model_validate(
                {"quietHoursStart": None, "quietHoursEnd": None}
            ),
        )
    )
    assert row.quiet_hours_start is None and row.quiet_hours_end is None
    assert row.timezone == "UTC"


def test_update_defaults_are_not_shared_between_instances() -> None:
    first = UpdateNotificationPreferences()
    first.channels[NotificationChannel.EMAIL] = False

    assert UpdateNotificationPreferences().channels[NotificationChannel.EMAIL] is True


def test_mark_read_only_touches_delivered_notifications() -> None:
    captured: list[Any] = []

    class _Capture(_Session):
        async def execute(self, statement: Any) -> Any:
            captured.append(statement)
            return SimpleNamespace(all=lambda: [])

    repository = SqlAlchemyNotificationRepository(lambda: _Capture(None))  # type: ignore[arg-type]
    asyncio.run(
        repository.mark_read(organization_id=uuid.uuid4(), user_id=USER_ID, ids=[uuid.uuid4()])
    )

    assert "deliver_at <= now()" in str(captured[0])
    assert Notification.deliver_at.key == "deliver_at"
