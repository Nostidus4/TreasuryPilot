"""Shared notification categories and preference enforcement."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from collections.abc import Mapping
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit


class NotificationCategory(StrEnum):
    MANDATORY = "mandatory"
    APPROVALS = "approvals"
    PAYMENTS = "payments"
    OPERATIONS = "operations"


class NotificationChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    TELEGRAM = "telegram"
    SLACK = "slack"
    LARK = "lark"
    WECOM = "wecom"


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
_APPROVAL_EVENT_TYPES = frozenset(
    {
        "ApprovalNeeded",
        "HighFlagRaised",
        "ExceptionNeeded",
        "GovernanceSignatureNeeded",
        "FeeAcceptanceNeeded",
    }
)
_PAYMENT_EVENT_TYPES = frozenset({"PaymentDone"})
_OPERATION_EVENT_TYPES = frozenset(
    {
        "LowGas",
        "MandateExpiring",
        "OperationConfirmed",
        "OperationUpdated",
        "PlanUpdated",
        "PlanCompleted",
    }
)


def is_known_event_type(event_type: str) -> bool:
    """True for event types the platform emits, including ``NeedsReview:<role>``."""

    role = event_type.partition(":")[2] if event_type.startswith("NeedsReview:") else None
    return (
        event_type in MANDATORY_EVENT_TYPES
        or event_type in _APPROVAL_EVENT_TYPES
        or event_type in _PAYMENT_EVENT_TYPES
        or event_type in _OPERATION_EVENT_TYPES
        or role in _REVIEW_ROLES
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
    if event_type in _APPROVAL_EVENT_TYPES:
        return NotificationCategory.APPROVALS
    if event_type in _PAYMENT_EVENT_TYPES:
        return NotificationCategory.PAYMENTS
    if event_type in _OPERATION_EVENT_TYPES:
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


_WEBHOOK_MAX_LENGTH = 2048


def canonical_chat_webhook_url(kind: str, value: str) -> str:
    """Validate a Slack/Lark/WeCom incoming-webhook URL and return its canonical form.

    Only each provider's official HTTPS endpoint is accepted (SSRF guard). The canonical form
    (lowercase scheme and host, no default port, no empty query or fragment) is what gets
    hashed, stored and sent, so spelling variants cannot register the same webhook twice.
    Raises ``ValueError`` for anything else; ``kind`` is SLACK, LARK or WECOM.
    """

    if len(value) > _WEBHOOK_MAX_LENGTH:
        raise ValueError("invalid webhook URL")
    parsed = urlsplit(value)
    host = (parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError("invalid webhook URL")
    path = parsed.path
    if kind == "SLACK":
        valid = host == "hooks.slack.com" and path.startswith("/services/")
    elif kind == "LARK":
        valid = host in {"open.larksuite.com", "open.feishu.cn"} and path.startswith(
            "/open-apis/bot/v2/hook/"
        )
    elif kind == "WECOM":
        valid = host == "qyapi.weixin.qq.com" and path == "/cgi-bin/webhook/send"
    else:
        valid = False
    if not valid:
        raise ValueError("invalid webhook URL")
    return urlunsplit(("https", host, path, parsed.query, ""))


MIN_UNSUBSCRIBE_SECRET_BYTES = 32


def unsubscribe_signature(user_id: uuid.UUID, secret: str | bytes) -> str:
    """HMAC for the email unsubscribe link, shared by the signing worker and the API."""

    key = secret.encode() if isinstance(secret, str) else secret
    if len(key) < MIN_UNSUBSCRIBE_SECRET_BYTES:
        raise ValueError("notification email signing secret must contain at least 32 bytes")
    return hmac.new(key, f"notification-unsubscribe:{user_id}".encode(), hashlib.sha256).hexdigest()
