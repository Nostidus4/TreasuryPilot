from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from treasurypilot_api.notifications.preferences import (
    _preference_access,
    router,
)
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
    assert default.json()["channels"] == {"in_app": True, "email": True, "telegram": True}
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
