import pytest

from treasurypilot_core.notifications import (
    NotificationCategory,
    NotificationChannel,
    category_for_event,
    preference_allows,
)


@pytest.mark.parametrize(
    "event_type",
    [
        "UnknownOperation",
        "PauseRequested",
        "CircuitBreakerTripped",
        "UnexpectedOutflow",
        "CoverageChanged",
        "Discrepancy",
        "NewSecurityEvent",
        "NeedsReview:UnknownRole",
    ],
)
def test_mandatory_categories_cannot_be_muted(event_type: str) -> None:
    assert category_for_event(event_type) is NotificationCategory.MANDATORY
    assert preference_allows(
        event_type,
        NotificationChannel.IN_APP,
        channels={"in_app": False},
        categories={"mandatory": False},
    )


@pytest.mark.parametrize(
    ("event_type", "category"),
    [
        ("ApprovalNeeded", NotificationCategory.APPROVALS),
        ("NeedsReview:Finance", NotificationCategory.APPROVALS),
        ("PaymentDone", NotificationCategory.PAYMENTS),
        ("OperationConfirmed", NotificationCategory.OPERATIONS),
        ("LowGas", NotificationCategory.OPERATIONS),
        ("NeedsReview:Finance", NotificationCategory.APPROVALS),
    ],
)
def test_regular_events_obey_channel_and_category_preferences(
    event_type: str, category: NotificationCategory
) -> None:
    assert category_for_event(event_type) is category
    assert not preference_allows(
        event_type,
        NotificationChannel.IN_APP,
        channels={"in_app": False},
        categories={},
    )
    assert not preference_allows(
        event_type,
        NotificationChannel.IN_APP,
        channels={},
        categories={category.value: False},
    )
