"""Telegram delivery of ACTION/CRITICAL notifications (M13 §7-§8).

Content is minimal by default: a generic title and a deep link. Amount and vendor name
are looked up, scoped to the notification's organization, only for channels whose owner
opted in. Telegram is notify-only: messages are plain text with no buttons, and the
deep link lands on the app login where permissions and signatures apply.

Rate limit (M13-D7): at most one message per channel per 10 s. Notifications that pile
up inside the window are merged into one digest line sent when the window reopens.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.notifications import NotificationChannel, preference_allows
from treasurypilot_core.privacy import DecryptionError, FieldCipher
from treasurypilot_worker.notify.publisher import _json_object
from treasurypilot_worker.notify.telegram import (
    TelegramBotBlocked,
    TelegramClient,
    TelegramError,
    TelegramTransientError,
)

logger = logging.getLogger(__name__)

TARGET_CONTEXT = "notification_channels.target"
MIN_INTERVAL = timedelta(seconds=10)
MAX_ATTEMPTS = 3
RETRY_BACKOFF = (timedelta(seconds=5), timedelta(seconds=20))
BACKLOG_WINDOW = timedelta(hours=1)
CHANNELS_PER_RUN = 50
ENQUEUE_BATCH = 500
# A run stops starting new channels after this long; sends are sequential and each can take
# up to the client timeout, and the next scheduled run must not pile up behind this one.
RUN_BUDGET_SECONDS = 20.0
_PREFIX = "[TreasuryPilot]"
_VENDOR_LIMIT = 60

# Notifications that are due (deliver_at has passed, so quiet hours are honoured) and have no
# delivery row yet. Preferences are applied in Python with the shared preference_allows.
_DUE = """
SELECT n.id AS notification_id, n.type, c.id AS channel_id, p.channels, p.categories
FROM notifications AS n
JOIN notification_channels AS c
  ON c.user_id = n.user_id AND c.kind = 'TELEGRAM' AND c.active
LEFT JOIN notification_preferences AS p ON p.user_id = n.user_id
WHERE n.severity IN ('ACTION', 'CRITICAL')
  AND n.created_at >= c.verified_at
  AND n.deliver_at <= $1 AND n.deliver_at > $1::timestamptz - $2::interval
  AND NOT EXISTS (
    SELECT 1 FROM telegram_deliveries AS d
    WHERE d.notification_id = n.id AND d.channel_id = c.id
  )
ORDER BY n.deliver_at
LIMIT $3
"""

# Opted-out pairs are recorded as FAILED so they are not selected again.
_ENQUEUE = """
INSERT INTO telegram_deliveries (id, notification_id, channel_id, status, last_error, next_attempt_at)
SELECT gen_random_uuid(), d.notification_id, d.channel_id, d.status, d.last_error, $1
FROM unnest($2::uuid[], $3::uuid[], $4::text[], $5::text[])
  AS d(notification_id, channel_id, status, last_error)
ON CONFLICT (notification_id, channel_id) DO NOTHING
"""

# Only channels that can send now (active, outside the rate-limit window), oldest first, so a
# backlog on rate-limited channels cannot crowd out ready ones.
_CANDIDATE_CHANNELS = """
SELECT d.channel_id
FROM telegram_deliveries AS d
JOIN notification_channels AS c ON c.id = d.channel_id AND c.active
WHERE d.status = 'PENDING' AND d.next_attempt_at <= $1
  AND (c.last_sent_at IS NULL OR c.last_sent_at <= $1::timestamptz - $3::interval)
GROUP BY d.channel_id
ORDER BY MIN(d.next_attempt_at), d.channel_id
LIMIT $2
"""

_LOCK_CHANNEL = """
SELECT id, user_id, target, show_amounts, last_sent_at
FROM notification_channels
WHERE id = $1 AND active
  AND (last_sent_at IS NULL OR last_sent_at <= $2::timestamptz - $3::interval)
FOR UPDATE SKIP LOCKED
"""

# Amount, asset and vendor are selected only when the channel opted in (the CASE guards
# keep them out of the result otherwise) and only from the notification's own organization.
_PENDING = """
SELECT d.id AS delivery_id, d.attempts, n.title, n.link,
       CASE WHEN $2 THEN pr.amount END AS amount,
       CASE WHEN $2 THEN a.symbol END AS symbol,
       CASE WHEN $2 THEN a.decimals END AS decimals,
       CASE WHEN $2 THEN v.name END AS vendor
FROM telegram_deliveries AS d
JOIN notifications AS n ON n.id = d.notification_id AND n.user_id = $3
JOIN notification_channels AS c ON c.id = d.channel_id AND c.user_id = n.user_id
  AND n.created_at >= c.verified_at
LEFT JOIN domain_events AS e
  ON e.id = n.event_id AND e.org_id = n.org_id AND e.entity_type = 'payment_request'
LEFT JOIN payment_requests AS pr ON pr.id = e.entity_id AND pr.org_id = n.org_id
LEFT JOIN assets AS a ON a.id = pr.asset_id
LEFT JOIN vendors AS v ON v.id = pr.vendor_id AND v.org_id = pr.org_id
WHERE d.channel_id = $1 AND d.status = 'PENDING' AND d.next_attempt_at <= $4
ORDER BY n.created_at, n.id
"""

_EXPIRE_UNVERIFIED = """
UPDATE telegram_deliveries AS d
SET status = 'FAILED', last_error = 'channel_reverified'
FROM notifications AS n, notification_channels AS c
WHERE d.channel_id = $1 AND d.status = 'PENDING'
  AND n.id = d.notification_id AND c.id = d.channel_id
  AND n.created_at < c.verified_at
"""

_MARK_SENT = """
UPDATE telegram_deliveries
SET status = 'SENT', sent_at = $2, attempts = attempts + 1, last_error = NULL
WHERE id = ANY($1::uuid[])
"""

# Written in the claim transaction (before the HTTP call) so concurrent workers skip the channel
# while the message is in flight.
_MARK_CHANNEL_SENT = "UPDATE notification_channels SET last_sent_at = $2 WHERE id = $1"

_MARK_RETRY = """
UPDATE telegram_deliveries
SET attempts = attempts + 1,
    last_error = $3,
    status = CASE WHEN attempts + 1 >= $4 THEN 'FAILED' ELSE 'PENDING' END,
    next_attempt_at = $2::timestamptz + CASE WHEN attempts = 0 THEN $5::interval ELSE $6::interval END
WHERE id = ANY($1::uuid[])
"""

_DEACTIVATE = "UPDATE notification_channels SET active = false WHERE id = $1"

_FAIL_PENDING = """
UPDATE telegram_deliveries SET status = 'FAILED', last_error = $2
WHERE channel_id = $1 AND status = 'PENDING'
"""


@dataclass(frozen=True, slots=True)
class PendingMessage:
    delivery_id: uuid.UUID
    title: str
    link: str
    amount: int | None = None
    symbol: str | None = None
    decimals: int | None = None
    vendor: str | None = None


def format_amount(amount: int, decimals: int, symbol: str) -> str:
    """Render integer base units without floats, e.g. 1_500_000 @ 6 -> ``1.5 USDC``."""

    whole, fraction = divmod(amount, 10**decimals)
    text = str(whole)
    if decimals and fraction:
        text += "." + str(fraction).rjust(decimals, "0").rstrip("0")
    return f"{text} {symbol}"


def _clean(value: str, limit: int = _VENDOR_LIMIT) -> str:
    return " ".join(value.split())[:limit]


def build_text(messages: list[PendingMessage], base_url: str) -> str:
    """One notification becomes one line; several merge into a digest line."""

    root = base_url.rstrip("/")
    if len(messages) > 1:
        return f"{_PREFIX} {len(messages)} new notifications · open: {root}/notifications"
    message = messages[0]
    detail = ""
    if message.amount is not None and message.decimals is not None and message.symbol:
        detail = f" · {format_amount(message.amount, message.decimals, message.symbol)}"
        if message.vendor:
            detail += f" to {_clean(message.vendor)}"
    return f"{_PREFIX} {message.title}{detail} · open: {root}{message.link}"


def _pending_message(row: asyncpg.Record) -> PendingMessage:
    amount = row["amount"]
    return PendingMessage(
        delivery_id=row["delivery_id"],
        title=row["title"],
        link=row["link"],
        amount=int(amount) if amount is not None else None,
        symbol=row["symbol"],
        decimals=row["decimals"],
        vendor=row["vendor"],
    )


@dataclass(frozen=True, slots=True)
class _Claim:
    chat_id: str
    text: str
    delivery_ids: list[uuid.UUID]
    previous_sent_at: datetime | None


async def _claim_channel(
    connection: asyncpg.Connection,
    channel_id: uuid.UUID,
    *,
    cipher: FieldCipher,
    base_url: str,
    now: datetime,
) -> _Claim | None:
    """Short transaction: lock the channel, read its pending messages, start the rate window.

    The lock is released at commit, before any network call. Stamping ``last_sent_at`` is
    what keeps other workers off the channel while the message is in flight.
    """

    async with connection.transaction():
        channel = await connection.fetchrow(_LOCK_CHANNEL, channel_id, now, MIN_INTERVAL)
        if channel is None:
            return None  # rate-limited, inactive, or another worker holds it
        await connection.execute(_EXPIRE_UNVERIFIED, channel_id)
        rows = await connection.fetch(
            _PENDING, channel_id, channel["show_amounts"], channel["user_id"], now
        )
        if not rows:
            return None
        try:
            chat_id = cipher.decrypt_text(channel["target"], context=TARGET_CONTEXT)
        except DecryptionError:
            logger.error("telegram_target_undecryptable", extra={"channel_id": str(channel_id)})
            await connection.execute(_FAIL_PENDING, channel_id, "target_undecryptable")
            return None
        await connection.execute(_MARK_CHANNEL_SENT, channel_id, now)
        return _Claim(
            chat_id=chat_id,
            text=build_text([_pending_message(row) for row in rows], base_url),
            delivery_ids=[row["delivery_id"] for row in rows],
            previous_sent_at=channel["last_sent_at"],
        )


async def _deliver_channel(
    connection: asyncpg.Connection,
    channel_id: uuid.UUID,
    *,
    client: TelegramClient,
    cipher: FieldCipher,
    base_url: str,
    now: datetime,
) -> bool:
    claim = await _claim_channel(connection, channel_id, cipher=cipher, base_url=base_url, now=now)
    if claim is None:
        return False
    try:
        await client.send_message(claim.chat_id, claim.text)
    except TelegramBotBlocked:
        async with connection.transaction():
            await connection.execute(_DEACTIVATE, channel_id)
            await connection.execute(_FAIL_PENDING, channel_id, "bot_blocked")
        logger.warning("telegram_channel_deactivated", extra={"channel_id": str(channel_id)})
        return False
    except Exception as error:
        # A permanent rejection exhausts the attempts at once; transient and unexpected
        # errors back off, so one bad row cannot be retried forever.
        permanent = isinstance(error, TelegramError) and not isinstance(
            error, TelegramTransientError
        )
        async with connection.transaction():
            # A failed attempt is not a message: give the window back so the retry is
            # paced by the backoff alone.
            await connection.execute(_MARK_CHANNEL_SENT, channel_id, claim.previous_sent_at)
            await connection.execute(
                _MARK_RETRY,
                claim.delivery_ids,
                now,
                type(error).__name__,
                0 if permanent else MAX_ATTEMPTS,
                RETRY_BACKOFF[0],
                RETRY_BACKOFF[1],
            )
        logger.warning(
            "telegram_send_failed",
            extra={"channel_id": str(channel_id), "error": type(error).__name__},
        )
        return False
    async with connection.transaction():
        await connection.execute(_MARK_SENT, claim.delivery_ids, now)
    return True


async def _enqueue_due(connection: asyncpg.Connection, now: datetime) -> None:
    due = await connection.fetch(_DUE, now, BACKLOG_WINDOW, ENQUEUE_BATCH)
    if not due:
        return
    notification_ids, channel_ids, statuses, errors = [], [], [], []
    for row in due:
        allowed = preference_allows(
            row["type"],
            NotificationChannel.TELEGRAM,
            channels=_json_object(row["channels"]),
            categories=_json_object(row["categories"]),
        )
        notification_ids.append(row["notification_id"])
        channel_ids.append(row["channel_id"])
        statuses.append("PENDING" if allowed else "FAILED")
        errors.append(None if allowed else "preference_opt_out")
    await connection.execute(_ENQUEUE, now, notification_ids, channel_ids, statuses, errors)


async def deliver_pending(
    pool: asyncpg.Pool,
    *,
    client: TelegramClient,
    cipher: FieldCipher,
    base_url: str,
    now: datetime | None = None,
    budget_seconds: float = RUN_BUDGET_SECONDS,
) -> int:
    """Queue new notifications for linked channels and send what the rate limit allows.

    Returns the number of Telegram messages sent. Safe to run concurrently: a channel is
    claimed in a short transaction (``FOR UPDATE SKIP LOCKED`` plus a rate-window stamp),
    the HTTP call happens with no transaction or lock held, and the outcome is recorded in
    a second short transaction. Deliveries are unique per (notification, channel). A crash
    between claim and record leaves the deliveries PENDING, so they are retried.
    """

    clock: Callable[[], datetime] = (lambda: now) if now else (lambda: datetime.now(UTC))
    deadline = time.monotonic() + budget_seconds
    async with pool.acquire() as connection:
        await _enqueue_due(connection, clock())
        candidates: list[Any] = await connection.fetch(
            _CANDIDATE_CHANNELS, clock(), CHANNELS_PER_RUN, MIN_INTERVAL
        )
        sent = 0
        for candidate in candidates:
            if time.monotonic() >= deadline:
                break
            try:
                delivered = await _deliver_channel(
                    connection,
                    candidate["channel_id"],
                    client=client,
                    cipher=cipher,
                    base_url=base_url,
                    now=clock(),
                )
            except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError):
                raise  # the connection is gone: let the task rebuild the pool
            except Exception:
                # One bad channel must not abort the run for the others.
                logger.exception(
                    "telegram_channel_failed", extra={"channel_id": str(candidate["channel_id"])}
                )
                continue
            if delivered:
                sent += 1
    return sent
