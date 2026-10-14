"""Delivery of ACTION/CRITICAL notifications to Slack, Lark and WeCom webhooks (NTF-L03).

Same flow, content and limits as the Telegram sender, on ``chat_deliveries``: notifications
are queued when due (``deliver_at``, so quiet hours hold) and allowed by the user's
preferences; a channel is claimed in a short transaction (row lock plus rate-window stamp),
the webhook is called with no transaction or lock held, and the outcome is recorded in a
second short transaction. A crash in between leaves the deliveries PENDING for retry.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.notifications import NotificationChannel, preference_allows
from treasurypilot_core.privacy import DecryptionError, FieldCipher
from treasurypilot_worker.notify import telegram_sender as telegram
from treasurypilot_worker.notify.chat_adapters import (
    ChatPermanentError,
    ChatPlatform,
    ChatWebhookClient,
)
from treasurypilot_worker.notify.publisher import _json_object

logger = logging.getLogger(__name__)


def _chat(sql: str) -> str:
    """Reuse the Telegram statements that differ only by delivery table."""

    return sql.replace("telegram_deliveries", "chat_deliveries")


_DUE = """
SELECT n.id AS notification_id, n.type, c.id AS channel_id, c.kind, p.channels, p.categories
FROM notifications AS n
JOIN notification_channels AS c
  ON c.user_id = n.user_id AND c.kind IN ('SLACK', 'LARK', 'WECOM') AND c.active
LEFT JOIN notification_preferences AS p ON p.user_id = n.user_id
WHERE n.severity IN ('ACTION', 'CRITICAL')
  AND n.created_at >= c.verified_at
  AND n.deliver_at <= $1 AND n.deliver_at > $1::timestamptz - $2::interval
  AND NOT EXISTS (
    SELECT 1 FROM chat_deliveries AS d
    WHERE d.notification_id = n.id AND d.channel_id = c.id
  )
ORDER BY n.deliver_at
LIMIT $3
"""
_LOCK_CHANNEL = """
SELECT id, user_id, kind, target, show_amounts, last_sent_at
FROM notification_channels
WHERE id = $1 AND kind IN ('SLACK', 'LARK', 'WECOM') AND active
  AND (last_sent_at IS NULL OR last_sent_at <= $2::timestamptz - $3::interval)
FOR UPDATE SKIP LOCKED
"""
_ENQUEUE = _chat(telegram._ENQUEUE)
_CANDIDATE_CHANNELS = _chat(telegram._CANDIDATE_CHANNELS)
_PENDING = _chat(telegram._PENDING)
_EXPIRE_UNVERIFIED = _chat(telegram._EXPIRE_UNVERIFIED)
_MARK_SENT = _chat(telegram._MARK_SENT)
_MARK_RETRY = _chat(telegram._MARK_RETRY)
_FAIL_PENDING = _chat(telegram._FAIL_PENDING)
_MARK_CHANNEL_SENT = telegram._MARK_CHANNEL_SENT


@dataclass(frozen=True, slots=True)
class _Claim:
    platform: ChatPlatform
    webhook_url: str
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
    """Short transaction: lock the channel, read its pending messages, start the rate window."""

    async with connection.transaction():
        channel = await connection.fetchrow(_LOCK_CHANNEL, channel_id, now, telegram.MIN_INTERVAL)
        if channel is None:
            return None  # rate-limited, inactive, or another worker holds it
        await connection.execute(_EXPIRE_UNVERIFIED, channel_id)
        rows = await connection.fetch(
            _PENDING, channel_id, channel["show_amounts"], channel["user_id"], now
        )
        if not rows:
            return None
        try:
            webhook_url = cipher.decrypt_text(channel["target"], context=telegram.TARGET_CONTEXT)
        except DecryptionError:
            logger.error("chat_target_undecryptable", extra={"channel_id": str(channel_id)})
            await connection.execute(_FAIL_PENDING, channel_id, "target_undecryptable")
            return None
        await connection.execute(_MARK_CHANNEL_SENT, channel_id, now)
        return _Claim(
            platform=ChatPlatform(channel["kind"]),
            webhook_url=webhook_url,
            text=telegram.build_text([telegram._pending_message(row) for row in rows], base_url),
            delivery_ids=[row["delivery_id"] for row in rows],
            previous_sent_at=channel["last_sent_at"],
        )


async def _deliver_channel(
    connection: asyncpg.Connection,
    channel_id: uuid.UUID,
    *,
    clients: Mapping[ChatPlatform, ChatWebhookClient],
    cipher: FieldCipher,
    base_url: str,
    now: datetime,
) -> bool:
    claim = await _claim_channel(connection, channel_id, cipher=cipher, base_url=base_url, now=now)
    if claim is None:
        return False
    try:
        await clients[claim.platform].send_message(claim.webhook_url, claim.text)
    except Exception as error:
        # A permanent rejection fails the deliveries at once; transient and unexpected errors
        # back off, so one bad row cannot be retried forever.
        permanent = isinstance(error, ChatPermanentError)
        async with connection.transaction():
            # A failed attempt is not a message: give the window back so the retry is paced
            # by the backoff alone.
            await connection.execute(_MARK_CHANNEL_SENT, channel_id, claim.previous_sent_at)
            await connection.execute(
                _MARK_RETRY,
                claim.delivery_ids,
                now,
                type(error).__name__,
                0 if permanent else telegram.MAX_ATTEMPTS,
                telegram.RETRY_BACKOFF[0],
                telegram.RETRY_BACKOFF[1],
            )
        logger.warning(
            "chat_send_failed",
            extra={
                "channel_id": str(channel_id),
                "kind": claim.platform.value,
                "error": type(error).__name__,
            },
        )
        return False
    async with connection.transaction():
        await connection.execute(_MARK_SENT, claim.delivery_ids, now)
    return True


async def _enqueue_due(connection: asyncpg.Connection, now: datetime) -> None:
    due = await connection.fetch(_DUE, now, telegram.BACKLOG_WINDOW, telegram.ENQUEUE_BATCH)
    if not due:
        return
    notification_ids, channel_ids, statuses, errors = [], [], [], []
    for row in due:
        allowed = preference_allows(
            row["type"],
            NotificationChannel(row["kind"].lower()),
            channels=_json_object(row["channels"]),
            categories=_json_object(row["categories"]),
        )
        notification_ids.append(row["notification_id"])
        channel_ids.append(row["channel_id"])
        statuses.append("PENDING" if allowed else "FAILED")
        errors.append(None if allowed else "preference_opt_out")
    await connection.execute(_ENQUEUE, now, notification_ids, channel_ids, statuses, errors)


async def deliver_chat_pending(
    pool: asyncpg.Pool,
    *,
    clients: Mapping[ChatPlatform, ChatWebhookClient],
    cipher: FieldCipher,
    base_url: str,
    now: datetime | None = None,
    budget_seconds: float = telegram.RUN_BUDGET_SECONDS,
) -> int:
    """Queue new notifications for chat channels and send what the rate limit allows.

    Returns the number of messages sent. Safe to run concurrently (see module docstring).
    """

    clock: Callable[[], datetime] = (lambda: now) if now else (lambda: datetime.now(UTC))
    deadline = time.monotonic() + budget_seconds
    async with pool.acquire() as connection:
        await _enqueue_due(connection, clock())
        candidates: list[Any] = await connection.fetch(
            _CANDIDATE_CHANNELS, clock(), telegram.CHANNELS_PER_RUN, telegram.MIN_INTERVAL
        )
        sent = 0
        for candidate in candidates:
            if time.monotonic() >= deadline:
                break
            try:
                delivered = await _deliver_channel(
                    connection,
                    candidate["channel_id"],
                    clients=clients,
                    cipher=cipher,
                    base_url=base_url,
                    now=clock(),
                )
            except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError):
                raise  # the connection is gone: let the task rebuild the pool
            except Exception:
                # One bad channel must not abort the run for the others.
                logger.exception(
                    "chat_channel_failed", extra={"channel_id": str(candidate["channel_id"])}
                )
                continue
            if delivered:
                sent += 1
    return sent
