"""Claim and send pending notification emails from PostgreSQL."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from collections import defaultdict
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.notifications import (
    MIN_UNSUBSCRIBE_SECRET_BYTES,
    NotificationCategory,
    NotificationChannel,
    category_for_event,
    preference_allows,
)
from treasurypilot_worker.config import Settings
from treasurypilot_worker.notify.email import (
    EmailNotification,
    PermanentEmailError,
    render_notification_email,
    send_resend_email,
    unsubscribe_url,
)
from treasurypilot_worker.notify.publisher import _json_object

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
USERS_PER_PAGE = 50
# Immediate runs must end before the next 60 s tick (task expires=55); the daily run has no
# competing schedule. A run stops starting new users after its budget; the rest wait.
RUN_BUDGET_SECONDS = {"immediate": 40.0, "daily": 1500.0}
_NIL_UUID = uuid.UUID(int=0)

# Plain read of unsent, visible (deliver_at honours quiet hours), un-leased rows, whole users
# at a time so a digest is never split across pages. Eligibility is decided in email_route.
_PENDING = """
WITH pending AS (
    SELECT n.id, n.user_id, u.email, (u.status = 'active') AS active, n.title, n.body, n.link,
           n.severity, n.type AS event_type, n.deliver_at,
           COALESCE(p.delivery_mode, 'immediate') AS delivery_mode,
           COALESCE(np.channels, '{}'::jsonb) AS channels,
           COALESCE(np.categories, '{}'::jsonb) AS categories
    FROM notifications AS n
    JOIN users AS u ON u.id = n.user_id
    LEFT JOIN notification_email_preferences AS p ON p.user_id = n.user_id
    LEFT JOIN notification_preferences AS np ON np.user_id = n.user_id
    WHERE n.email_sent_at IS NULL
      AND n.deliver_at <= now()
      AND n.email_attempts < $3
      AND (n.email_next_attempt_at IS NULL OR n.email_next_attempt_at <= now())
      AND (n.email_claimed_at IS NULL OR n.email_claimed_at < now() - interval '10 minutes')
)
SELECT * FROM pending
WHERE user_id IN (
    SELECT DISTINCT user_id FROM pending WHERE user_id > $1 ORDER BY user_id LIMIT $2
)
ORDER BY user_id, deliver_at, id
"""
# The guard makes the claim race-safe: only one worker gets each row for a lease period.
_CLAIM = """
UPDATE notifications SET email_claimed_at = now()
WHERE id = ANY($1::uuid[]) AND email_sent_at IS NULL
  AND (email_claimed_at IS NULL OR email_claimed_at < now() - interval '10 minutes')
RETURNING id
"""
_MARK_SENT = """
UPDATE notifications SET email_sent_at = now(), email_claimed_at = NULL
WHERE id = ANY($1::uuid[]) AND email_sent_at IS NULL
"""
# Transient failures back off 1, 2, 4, 8 ... minutes; permanent ones exhaust the attempts.
_FAILED = """
UPDATE notifications
SET email_claimed_at = NULL,
    email_next_attempt_at = now() + make_interval(mins => LEAST(power(2, email_attempts)::int, 60)),
    email_attempts = CASE WHEN $2::boolean THEN $3::int ELSE email_attempts + 1 END
WHERE id = ANY($1::uuid[]) AND email_sent_at IS NULL
"""


def email_route(
    *,
    delivery_mode: str,
    severity: str,
    event_type: str,
    active: bool,
    channels: dict[str, bool],
    categories: dict[str, bool],
) -> str | None:
    """The one eligibility decision: ``immediate``, ``daily``, or None (consume, never send).

    Mandatory events (CRITICAL, or a mandatory category) bypass the cadence including ``off``.
    """
    if not active or not preference_allows(
        event_type, NotificationChannel.EMAIL, channels=channels, categories=categories
    ):
        return None
    if (
        severity == "CRITICAL"
        or category_for_event(event_type) is NotificationCategory.MANDATORY
        or delivery_mode == "immediate"
    ):
        return "immediate"
    return "daily" if delivery_mode == "daily" else None


def _validate(settings: Settings, cadence: str) -> tuple[str, str, str]:
    if cadence not in {"immediate", "daily"}:
        raise ValueError("cadence must be immediate or daily")
    api_key = settings.resend_api_key.get_secret_value() if settings.resend_api_key else ""
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for notification email delivery")
    if not api_key or not settings.resend_from_email:
        raise RuntimeError(
            "TP_RESEND_API_KEY and TP_RESEND_FROM_EMAIL are required for notification email delivery"
        )
    secret = settings.session_secret.get_secret_value() if settings.session_secret else ""
    if len(secret.encode()) < MIN_UNSUBSCRIBE_SECRET_BYTES:
        raise RuntimeError("TP_SESSION_SECRET must contain at least 32 bytes")
    if settings.environment.casefold() != "local":
        if not settings.app_base_url.startswith("https://"):
            raise RuntimeError("TP_APP_BASE_URL must use HTTPS outside the local environment")
        if not settings.public_api_base_url.startswith("https://"):
            raise RuntimeError(
                "TP_PUBLIC_API_BASE_URL must use HTTPS outside the local environment"
            )
    return api_key, settings.resend_from_email, secret


def _notification(row: asyncpg.Record) -> EmailNotification:
    return EmailNotification(
        title=row["title"], body=row["body"], link=row["link"], severity=row["severity"]
    )


async def _execute(pool: Any, query: str, *args: object) -> None:
    async with pool.acquire() as connection:
        await connection.execute(query, *args)


async def _deliver_user(
    pool: Any,
    user_rows: list[asyncpg.Record],
    *,
    cadence: str,
    settings: Settings,
    api_key: str,
    from_email: str,
    secret: str,
) -> dict[str, int]:
    routes = [
        email_route(
            delivery_mode=row["delivery_mode"],
            severity=row["severity"],
            event_type=row["event_type"],
            active=row["active"],
            channels=_json_object(row["channels"]),
            categories=_json_object(row["categories"]),
        )
        for row in user_rows
    ]
    result = {"claimed": 0, "sent": 0, "skipped": 0, "failed": 0}
    # Suppressed by preference or account state: terminal for email, so consume them.
    consumed = [row["id"] for row, route in zip(user_rows, routes, strict=True) if route is None]
    if consumed:
        await _execute(pool, _MARK_SENT, consumed)
        result["skipped"] = len(consumed)
    mine = [row for row, route in zip(user_rows, routes, strict=True) if route == cadence]
    if not mine:
        return result
    async with pool.acquire() as connection:
        won = {record["id"] for record in await connection.fetch(_CLAIM, [r["id"] for r in mine])}
    mine = [row for row in mine if row["id"] in won]
    if not mine:
        return result
    result["claimed"] = len(mine)

    # A digest is one message per user; immediate delivery is one per event.
    batches = [mine] if cadence == "daily" else [[row] for row in mine]
    unsubscribe = unsubscribe_url(
        api_base_url=settings.public_api_base_url, user_id=mine[0]["user_id"], secret=secret
    )
    for batch in batches:
        ids = [row["id"] for row in batch]
        key = "notification-email/" + (
            str(ids[0])
            if len(ids) == 1
            else hashlib.sha256(",".join(sorted(map(str, ids))).encode()).hexdigest()
        )
        try:
            message = render_notification_email(
                tuple(_notification(row) for row in batch),
                app_base_url=settings.app_base_url,
                digest=cadence == "daily",
            )
            await asyncio.to_thread(
                send_resend_email,
                api_key=api_key,
                from_email=from_email,
                recipient=batch[0]["email"],
                message=message,
                unsubscribe_url_value=unsubscribe,
                idempotency_key=key,
            )
        except Exception as error:
            result["failed"] += len(batch)
            logger.exception(
                "notification_email_delivery_failed", extra={"user_id": str(batch[0]["user_id"])}
            )
            permanent = isinstance(error, (PermanentEmailError, ValueError))
            try:
                await _execute(pool, _FAILED, ids, permanent, MAX_ATTEMPTS)
            except Exception:
                logger.exception("notification_email_record_failure_failed")  # lease will expire
            continue
        result["sent"] += len(batch)
        try:
            await _execute(pool, _MARK_SENT, ids)
        except Exception:
            # The lease expires and the retry reuses the Idempotency-Key, so Resend dedupes it.
            logger.exception("notification_email_mark_sent_failed")
    return result


async def deliver_pending_emails(
    pool: asyncpg.Pool,
    *,
    settings: Settings,
    cadence: str,
    budget_seconds: float | None = None,
) -> dict[str, int]:
    """Send due messages; mandatory events bypass user cadence and unsubscribe."""
    api_key, from_email, secret = _validate(settings, cadence)
    deadline = time.monotonic() + (budget_seconds or RUN_BUDGET_SECONDS[cadence])
    totals = {"claimed": 0, "sent": 0, "skipped": 0, "failed": 0}
    cursor = _NIL_UUID
    while time.monotonic() < deadline:
        async with pool.acquire() as connection:
            rows = list(await connection.fetch(_PENDING, cursor, USERS_PER_PAGE, MAX_ATTEMPTS))
        if not rows:
            break
        cursor = rows[-1]["user_id"]
        by_user: dict[uuid.UUID, list[asyncpg.Record]] = defaultdict(list)
        for row in rows:
            by_user[row["user_id"]].append(row)
        for user_rows in by_user.values():
            if time.monotonic() >= deadline:
                return totals
            outcome = await _deliver_user(
                pool,
                user_rows,
                cadence=cadence,
                settings=settings,
                api_key=api_key,
                from_email=from_email,
                secret=secret,
            )
            for name, count in outcome.items():
                totals[name] += count
    return totals
