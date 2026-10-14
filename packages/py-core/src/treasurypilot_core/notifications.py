"""Shared notification categories and preference enforcement."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum


class NotificationCategory(StrEnum):
    MANDATORY = "mandatory"
    APPROVALS = "approvals"
    PAYMENTS = "payments"
    OPERATIONS = "operations"


class NotificationChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    TELEGRAM = "telegram"


MANDATORY_EVENT_TYPES = frozenset(
    {
        "UnknownOperation",
        "PauseRequested",
        "PauseEffective",
        "Resumed",
        "CircuitBreakerTripped",
        "UnexpectedOutflow",
        "CoverageChanged",
        "Discrepancy",
    }
)
_REVIEW_ROLES = frozenset(
    {"OrgAdmin", "Owner", "Approver", "Operator", "Finance", "Guardian", "Auditor"}
)


def category_for_event(event_type: str) -> NotificationCategory:
    """Classify known events; unknown event variants fail safe to mandatory."""

    if event_type in MANDATORY_EVENT_TYPES:
        return NotificationCategory.MANDATORY
    if event_type.startswith("NeedsReview:"):
        role = event_type.partition(":")[2]
        return (
            NotificationCategory.APPROVALS
            if role in _REVIEW_ROLES
            else NotificationCategory.MANDATORY
        )
    if event_type in {
        "ApprovalNeeded",
        "HighFlagRaised",
        "ExceptionNeeded",
        "GovernanceSignatureNeeded",
        "FeeAcceptanceNeeded",
    }:
        return NotificationCategory.APPROVALS
    if event_type == "PaymentDone":
        return NotificationCategory.PAYMENTS
    if event_type in {
        "LowGas",
        "MandateExpiring",
        "OperationConfirmed",
        "PlanUpdated",
        "PlanCompleted",
    }:
        return NotificationCategory.OPERATIONS
    # New event types must be reviewed and categorized before users can suppress them.
    return NotificationCategory.MANDATORY


def preference_allows(
    event_type: str,
    channel: NotificationChannel,
    *,
    channels: Mapping[str, bool],
    categories: Mapping[str, bool],
) -> bool:
    """Apply user settings while always allowing the mandatory category."""

    category = category_for_event(event_type)
    if category is NotificationCategory.MANDATORY:
        return True
    return channels.get(channel.value, True) and categories.get(category.value, True)
