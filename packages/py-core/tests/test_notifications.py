import pytest

from treasurypilot_core.notifications import (
    NotificationCategory,
    NotificationChannel,
    canonical_chat_webhook_url,
    category_for_event,
    is_known_event_type,
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
        ("MandateExpiring", NotificationCategory.OPERATIONS),
        ("MandateExpired", NotificationCategory.OPERATIONS),
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


@pytest.mark.parametrize(
    ("event_type", "known"),
    [
        ("ApprovalNeeded", True),
        ("PaymentDone", True),
        ("UnknownOperation", True),
        ("LowGas", True),
        ("MandateExpiring", True),
        ("MandateExpired", True),
        ("NeedsReview:Finance", True),
        ("NeedsReview:Nobody", False),
        ("NewSecurityEvent", False),
        ("", False),
    ],
)
def test_known_event_types(event_type: str, known: bool) -> None:
    assert is_known_event_type(event_type) is known


def test_chat_channels_follow_their_own_preference_toggle() -> None:
    assert not preference_allows(
        "ApprovalNeeded", NotificationChannel.SLACK, channels={"slack": False}, categories={}
    )
    assert preference_allows(
        "ApprovalNeeded", NotificationChannel.LARK, channels={"slack": False}, categories={}
    )


@pytest.mark.parametrize(
    ("kind", "raw", "canonical"),
    [
        (
            "SLACK",
            "HTTPS://Hooks.Slack.com:443/services/T/B/x?",
            "https://hooks.slack.com/services/T/B/x",
        ),
        (
            "LARK",
            "https://open.feishu.cn/open-apis/bot/v2/hook/abc",
            "https://open.feishu.cn/open-apis/bot/v2/hook/abc",
        ),
        (
            "WECOM",
            "https://QYAPI.weixin.qq.com/cgi-bin/webhook/send?key=k",
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k",
        ),
    ],
)
def test_chat_webhook_url_is_canonicalised(kind: str, raw: str, canonical: str) -> None:
    assert canonical_chat_webhook_url(kind, raw) == canonical


@pytest.mark.parametrize(
    ("kind", "raw"),
    [
        ("SLACK", "http://hooks.slack.com/services/T/B/x"),
        ("SLACK", "https://hooks.slack.com:444/services/T/B/x"),
        ("SLACK", "https://user@hooks.slack.com/services/T/B/x"),
        ("SLACK", "https://hooks.slack.com/services/T/B/x#frag"),
        ("SLACK", "https://evil.example/services/T/B/x"),
        ("SLACK", "https://hooks.slack.com/other"),
        ("SLACK", "https://hooks.slack.com/services/" + "a" * 2100),
        ("LARK", "https://hooks.slack.com/services/T/B/x"),
        ("WECOM", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send/extra"),
        ("TELEGRAM", "https://hooks.slack.com/services/T/B/x"),
    ],
)
def test_chat_webhook_url_rejects_other_destinations(kind: str, raw: str) -> None:
    with pytest.raises(ValueError):
        canonical_chat_webhook_url(kind, raw)
