"""Notification recipient and presentation rules from M13 §5."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NotificationPolicy:
    roles: tuple[str, ...]
    severity: str
    title: str
    body: str
    include_creator: bool = False
    specific_user_ids_key: str | None = None


ROUTING_TABLE: dict[str, NotificationPolicy] = {
    "ApprovalNeeded": NotificationPolicy(
        ("Approver",), "ACTION", "Approval required", "A payment request is waiting for approval."
    ),
    "HighFlagRaised": NotificationPolicy(
        ("Approver", "Operator"),
        "ACTION",
        "Request needs attention",
        "A high-severity request flag was raised.",
    ),
    "ExceptionNeeded": NotificationPolicy(
        ("Owner",),
        "ACTION",
        "Owner action required",
        "A treasury exception is waiting for an owner.",
    ),
    "GovernanceSignatureNeeded": NotificationPolicy(
        (),
        "ACTION",
        "Signature required",
        "A Safe transaction is waiting for an owner signature.",
        specific_user_ids_key="ownerUserIds",
    ),
    "FeeAcceptanceNeeded": NotificationPolicy(
        ("Finance", "Operator", "Owner"),
        "ACTION",
        "Fee acceptance required",
        "A treasury fee proposal needs acceptance.",
    ),
    "PaymentDone": NotificationPolicy(
        ("Operator", "Finance"), "INFO", "Payment complete", "A payment request was paid.", True
    ),
    "UnknownOperation": NotificationPolicy(
        ("Operator", "Owner"),
        "CRITICAL",
        "Unknown operation",
        "An unrecognized treasury operation needs review.",
    ),
    "PauseRequested": NotificationPolicy(
        ("Owner", "Guardian", "Operator"),
        "CRITICAL",
        "Pause requested",
        "A treasury pause was requested.",
    ),
    "PauseEffective": NotificationPolicy(
        ("Owner", "Guardian", "Operator"),
        "CRITICAL",
        "Treasury paused",
        "A treasury pause is now effective.",
    ),
    "Resumed": NotificationPolicy(
        ("Owner", "Guardian", "Operator"), "CRITICAL", "Treasury resumed", "A treasury was resumed."
    ),
    "CircuitBreakerTripped": NotificationPolicy(
        ("Owner", "Guardian"),
        "CRITICAL",
        "Circuit breaker tripped",
        "A treasury circuit breaker needs attention.",
    ),
    "UnexpectedOutflow": NotificationPolicy(
        ("Owner", "Finance"),
        "CRITICAL",
        "Unexpected outflow",
        "An unplanned treasury outflow was detected.",
    ),
    "CoverageChanged": NotificationPolicy(
        ("Owner", "OrgAdmin"),
        "CRITICAL",
        "Coverage changed",
        "Treasury coverage is no longer complete.",
    ),
    "LowGas": NotificationPolicy(
        ("Operator", "OrgAdmin"),
        "ACTION",
        "Low gas balance",
        "A treasury wallet needs gas funding.",
    ),
    "MandateExpiring": NotificationPolicy(
        ("Owner",), "ACTION", "Mandate expiring", "A treasury mandate is nearing expiry."
    ),
    "Discrepancy": NotificationPolicy(
        ("Finance", "Owner"),
        "CRITICAL",
        "Reconciliation discrepancy",
        "A treasury discrepancy needs review.",
    ),
}

_REVIEW_ROLES = frozenset(
    {"OrgAdmin", "Owner", "Approver", "Operator", "Finance", "Guardian", "Auditor"}
)
_FALLBACK_POLICY = NotificationPolicy(
    ("Operator", "Owner"),
    "CRITICAL",
    "Unrecognized treasury event",
    "An unrecognized treasury event needs review.",
)


def policy_for_event(event_type: str) -> NotificationPolicy:
    """Resolve a policy; review events carry their routed role in the event type."""

    if event_type.startswith("NeedsReview:"):
        role = event_type.partition(":")[2]
        if role in _REVIEW_ROLES:
            return NotificationPolicy(
                (role,), "ACTION", "Review required", "A treasury review item needs your attention."
            )
        return _FALLBACK_POLICY
    return ROUTING_TABLE.get(event_type, _FALLBACK_POLICY)
