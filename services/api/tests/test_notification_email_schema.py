from treasurypilot_api.database import Base
from treasurypilot_api.notifications.models import Notification, NotificationEmailPreference


def test_email_preferences_and_delivery_claims_are_in_api_metadata() -> None:
    preferences = NotificationEmailPreference.__table__
    notifications = Notification.__table__

    assert preferences.primary_key.columns.keys() == ["user_id"]
    assert any(
        "delivery_mode IN ('immediate', 'daily', 'off')" in str(constraint.sqltext)
        for constraint in preferences.constraints
        if hasattr(constraint, "sqltext")
    )
    assert "email_sent_at" in notifications.c
    assert "email_claimed_at" in notifications.c
    assert "notification_email_preferences" in Base.metadata.tables


def test_email_retry_state_and_updated_at_are_mapped() -> None:
    assert "email_attempts" in Notification.__table__.c
    assert "email_next_attempt_at" in Notification.__table__.c
    assert "updated_at" in NotificationEmailPreference.__table__.c
