"""Claim and send pending notification emails from PostgreSQL."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.notifications import (
    NotificationCategory,
    NotificationChannel,
    category_for_event,
    preference_allows,
)
from treasurypilot_worker.config import Settings
from treasurypilot_worker.notify.email import (
    EmailNotification,
    render_notification_email,
    send_resend_email,
    unsubscribe_url,
)

logger = logging.getLogger(__name__)
_LOCAL_SECRET = "treasurypilot-local-development-only-session-secret"

_CLAIM = """
WITH candidates AS (
    SELECT n.id, n.user_id, u.email, n.title, n.body, n.link, n.severity,
           n.type AS event_type, n.created_at,
           COALESCE(p.delivery_mode, 'immediate') AS delivery_mode,
           COALESCE(np.channels, '{"email": true}'::jsonb) AS channels,
           COALESCE(np.categories, '{}'::jsonb) AS categories,
           (u.status = 'active' AND (($1 = 'immediate' AND (n.severity = 'CRITICAL' OR
             COALESCE(p.delivery_mode, 'immediate') = 'immediate') OR
             $1 = 'daily' AND n.severity <> 'CRITICAL' AND
             COALESCE(p.delivery_mode, 'immediate') = 'daily')) AS due
    FROM notifications AS n
    JOIN users AS u ON u.id = n.user_id
    LEFT JOIN notification_email_preferences AS p ON p.user_id = n.user_id
    LEFT JOIN notification_preferences AS np ON np.user_id = n.user_id
    WHERE n.email_sent_at IS NULL
      AND (n.email_claimed_at IS NULL OR n.email_claimed_at < now() - interval '10 minutes')
      AND (($1 = 'immediate' AND (n.severity = 'CRITICAL'
             OR COALESCE(p.delivery_mode, 'immediate') IN ('immediate', 'off')))
           OR ($1 = 'daily' AND n.severity <> 'CRITICAL'
             AND COALESCE(p.delivery_mode, 'immediate') = 'daily'))
    ORDER BY n.created_at, n.id
    LIMIT $2
    FOR UPDATE OF n SKIP LOCKED
), claimed AS (
    UPDATE notifications AS n
       SET email_claimed_at = CASE WHEN c.due THEN now() ELSE NULL END,
           email_sent_at = CASE WHEN c.due THEN NULL ELSE now() END
      FROM candidates AS c
     WHERE n.id = c.id
    RETURNING n.id, n.user_id, c.email, n.title, n.body, n.link, n.severity,
              n.created_at, c.delivery_mode, c.event_type, c.channels, c.categories, c.due
)
SELECT * FROM claimed ORDER BY created_at, id
"""
_MARK_SENT = "UPDATE notifications SET email_sent_at = now(), email_claimed_at = NULL WHERE id = $1"
_RELEASE = (
    "UPDATE notifications SET email_claimed_at = NULL WHERE id = $1 AND email_sent_at IS NULL"
)


def should_send_email(
    *, delivery_mode: str, severity: str, cadence: str, event_type: str | None = None
) -> bool:
    """Mandatory events bypass all cadence settings; other mail follows the selected cadence."""
    if severity == "CRITICAL" or (
        event_type is not None and category_for_event(event_type) is NotificationCategory.MANDATORY
    ):
        return cadence == "immediate"
    return (cadence == "immediate" and delivery_mode == "immediate") or (
        cadence == "daily" and delivery_mode == "daily"
    )


def _notifications(
    rows: list[asyncpg.Record], *, cadence: str
) -> dict[uuid.UUID, list[EmailNotification]]:
    grouped: dict[uuid.UUID, list[EmailNotification]] = defaultdict(list)
    for row in rows:
        if should_send_email(
            delivery_mode=row["delivery_mode"],
            severity=row["severity"],
            cadence=cadence,
            event_type=row["event_type"],
        ):
            if not row["due"] or not preference_allows(
                row["event_type"],
                NotificationChannel.EMAIL,
                channels=row["channels"],
                categories=row["categories"],
            ):
                continue
            grouped[row["user_id"]].append(
                EmailNotification(
                    title=row["title"], body=row["body"], link=row["link"], severity=row["severity"]
                )
            )
    return grouped


async def deliver_pending_emails(
    pool: asyncpg.Pool,
    *,
    settings: Settings,
    cadence: str,
    batch_size: int = 200,
) -> dict[str, int]:
    """Send due messages; CRITICAL events always bypass user cadence/unsubscribe."""
    if cadence not in {"immediate", "daily"}:
        raise ValueError("cadence must be immediate or daily")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for notification email delivery")
    api_key = settings.resend_api_key.get_secret_value() if settings.resend_api_key else ""
    if not api_key or not settings.resend_from_email:
        raise RuntimeError(
            "TP_RESEND_API_KEY and TP_RESEND_FROM_EMAIL are required for notification email delivery"
        )
    if settings.environment.casefold() != "local":
        if (
            not settings.session_secret
            or len(settings.session_secret.get_secret_value().encode()) < 32
        ):
            raise RuntimeError("TP_SESSION_SECRET must contain at least 32 bytes")
        if not settings.app_base_url.startswith("https://"):
            raise RuntimeError("TP_APP_BASE_URL must use HTTPS outside the local environment")
        if not settings.public_api_base_url.startswith("https://"):
            raise RuntimeError(
                "TP_PUBLIC_API_BASE_URL must use HTTPS outside the local environment"
            )
    secret = (
        settings.session_secret.get_secret_value()
        if settings.session_secret and settings.session_secret.get_secret_value()
        else _LOCAL_SECRET
    )

    async with pool.acquire() as connection:
        async with connection.transaction():
            rows = list(await connection.fetch(_CLAIM, cadence, batch_size))
    effective = {
        row["id"]: row["due"]
        and preference_allows(
            row["event_type"],
            NotificationChannel.EMAIL,
            channels=row["channels"],
            categories=row["categories"],
        )
        and should_send_email(
            delivery_mode=row["delivery_mode"],
            severity=row["severity"],
            cadence=cadence,
            event_type=row["event_type"],
        )
        for row in rows
    }
    # Preferences that suppress an otherwise-due message are terminal for email; mark them
    # consumed so they are not retried every ten minutes forever.
    suppressed_ids = [row["id"] for row in rows if row["due"] and not effective[row["id"]]]
    if suppressed_ids:
        async with pool.acquire() as connection:
            async with connection.transaction():
                for notification_id in suppressed_ids:
                    await connection.execute(_MARK_SENT, notification_id)
    grouped = _notifications(rows, cadence=cadence)
    skipped = sum(1 for row in rows if not effective[row["id"]])
    sent = 0
    failed = 0
    by_user: dict[uuid.UUID, list[asyncpg.Record]] = defaultdict(list)
    for row in rows:
        if effective[row["id"]]:
            by_user[row["user_id"]].append(row)

    for user_id, user_rows in by_user.items():
        email = user_rows[0]["email"]
        digest = cadence == "daily"
        messages = (
            grouped[user_id]
            if digest
            else [
                EmailNotification(
                    title=r["title"], body=r["body"], link=r["link"], severity=r["severity"]
                )
                for r in user_rows
            ]
        )
        # A digest is one message per user; immediate delivery is one per event.
        batches = [tuple(messages)] if digest else [(item,) for item in messages]
        for batch_index, batch in enumerate(batches):
            batch_rows = user_rows if digest else [user_rows[batch_index]]
            try:
                message = render_notification_email(
                    batch, app_base_url=settings.app_base_url, digest=digest
                )
                await asyncio.to_thread(
                    send_resend_email,
                    api_key=api_key,
                    from_email=settings.resend_from_email,
                    recipient=email,
                    message=message,
                    unsubscribe_url_value=unsubscribe_url(
                        api_base_url=settings.public_api_base_url, user_id=user_id, secret=secret
                    ),
                )
            except Exception:
                failed += len(batch_rows)
                logger.exception(
                    "notification_email_delivery_failed", extra={"user_id": str(user_id)}
                )
                async with pool.acquire() as connection:
                    for row in batch_rows:
                        await connection.execute(_RELEASE, row["id"])
                continue
            sent += len(batch_rows)
            async with pool.acquire() as connection:
                async with connection.transaction():
                    for row in batch_rows:
                        await connection.execute(_MARK_SENT, row["id"])

    # Inactive accounts have no email target. Release their claims after marking skipped.
    return {"claimed": len(rows), "sent": sent, "skipped": skipped, "failed": failed}
