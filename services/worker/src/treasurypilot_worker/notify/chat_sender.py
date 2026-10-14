"""Delivery queue for Slack, Lark and WeCom notification channels."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.privacy import DecryptionError, FieldCipher
from treasurypilot_worker.notify.chat_adapters import (
    ChatDeliveryError,
    ChatPlatform,
    ChatTransientError,
    ChatWebhookClient,
)
from treasurypilot_worker.notify.telegram_sender import (
    BACKLOG_WINDOW,
    CHANNELS_PER_RUN,
    MAX_ATTEMPTS,
    MIN_INTERVAL,
    RETRY_BACKOFF,
    _pending_message,
    build_text,
)

logger = logging.getLogger(__name__)

_ENQUEUE = """
INSERT INTO chat_deliveries (id, notification_id, channel_id, next_attempt_at)
SELECT gen_random_uuid(), n.id, c.id, $1
FROM notifications AS n
JOIN notification_channels AS c ON c.user_id = n.user_id
WHERE c.kind IN ('SLACK', 'LARK', 'WECOM') AND c.active
  AND n.severity IN ('ACTION', 'CRITICAL')
  AND n.created_at >= c.verified_at
  AND n.created_at > $1::timestamptz - $2::interval
ON CONFLICT (notification_id, channel_id) DO NOTHING
"""
_CANDIDATES = """
SELECT DISTINCT channel_id FROM chat_deliveries
WHERE status = 'PENDING' AND next_attempt_at <= $1 LIMIT $2
"""
_LOCK = """
SELECT id, user_id, kind, target, show_amounts FROM notification_channels
WHERE id = $1 AND kind IN ('SLACK', 'LARK', 'WECOM') AND active
  AND (last_sent_at IS NULL OR last_sent_at <= $2::timestamptz - $3::interval)
FOR UPDATE SKIP LOCKED
"""
_PENDING = """
SELECT d.id AS delivery_id, d.attempts, n.title, n.link,
       CASE WHEN $2 THEN pr.amount END AS amount,
       CASE WHEN $2 THEN a.symbol END AS symbol,
       CASE WHEN $2 THEN a.decimals END AS decimals,
       CASE WHEN $2 THEN v.name END AS vendor
FROM chat_deliveries AS d
JOIN notifications AS n ON n.id = d.notification_id AND n.user_id = $3
LEFT JOIN domain_events AS e
  ON e.id = n.event_id AND e.org_id = n.org_id AND e.entity_type = 'payment_request'
LEFT JOIN payment_requests AS pr ON pr.id = e.entity_id AND pr.org_id = n.org_id
LEFT JOIN assets AS a ON a.id = pr.asset_id
LEFT JOIN vendors AS v ON v.id = pr.vendor_id AND v.org_id = pr.org_id
WHERE d.channel_id = $1 AND d.status = 'PENDING' AND d.next_attempt_at <= $4
ORDER BY n.created_at, n.id
"""
_MARK_SENT = """
UPDATE chat_deliveries SET status='SENT', sent_at=$2, attempts=attempts+1, last_error=NULL
WHERE id=ANY($1::uuid[])
"""
_MARK_RETRY = """
UPDATE chat_deliveries SET attempts=attempts+1, last_error=$3,
  status=CASE WHEN attempts+1 >= $4 THEN 'FAILED' ELSE 'PENDING' END,
  next_attempt_at=$2::timestamptz + CASE WHEN attempts=0 THEN $5::interval ELSE $6::interval END
WHERE id=ANY($1::uuid[])
"""
_MARK_FAILED = "UPDATE chat_deliveries SET status='FAILED', last_error=$2 WHERE id=ANY($1::uuid[])"
_MARK_CHANNEL_SENT = "UPDATE notification_channels SET last_sent_at=$2 WHERE id=$1"
_FAIL_PENDING = "UPDATE chat_deliveries SET status='FAILED', last_error=$2 WHERE channel_id=$1 AND status='PENDING'"


async def _deliver_channel(
    connection: asyncpg.Connection,
    channel_id: uuid.UUID,
    *,
    clients: Mapping[ChatPlatform, ChatWebhookClient],
    cipher: FieldCipher,
    base_url: str,
    now: datetime,
) -> bool:
    async with connection.transaction():
        channel = await connection.fetchrow(_LOCK, channel_id, now, MIN_INTERVAL)
        if channel is None:
            return False
        rows = await connection.fetch(
            _PENDING, channel_id, channel["show_amounts"], channel["user_id"], now
        )
        if not rows:
            return False
        delivery_ids = [row["delivery_id"] for row in rows]
        message = build_text([_pending_message(row) for row in rows], base_url)
        try:
            target = cipher.decrypt_text(channel["target"], context="notification_channels.target")
        except DecryptionError:
            logger.error("chat_target_undecryptable", extra={"channel_id": str(channel_id)})
            await connection.execute(_FAIL_PENDING, channel_id, "target_undecryptable")
            return False
        platform = ChatPlatform(channel["kind"])
        try:
            await clients[platform].send_message(target, message)
        except ChatDeliveryError as error:
            if not isinstance(error, ChatTransientError):
                await connection.execute(_MARK_FAILED, delivery_ids, type(error).__name__)
            else:
                await connection.execute(
                    _MARK_RETRY,
                    delivery_ids,
                    now,
                    type(error).__name__,
                    MAX_ATTEMPTS,
                    RETRY_BACKOFF[0],
                    RETRY_BACKOFF[1],
                )
            logger.warning(
                "chat_send_failed",
                extra={
                    "channel_id": str(channel_id),
                    "kind": platform.value,
                    "error": type(error).__name__,
                },
            )
            return False
        await connection.execute(_MARK_SENT, delivery_ids, now)
        await connection.execute(_MARK_CHANNEL_SENT, channel_id, now)
        return True


async def deliver_chat_pending(
    pool: asyncpg.Pool,
    *,
    clients: Mapping[ChatPlatform, ChatWebhookClient],
    cipher: FieldCipher,
    base_url: str,
    now: datetime | None = None,
) -> int:
    """Deliver eligible notifications with Telegram-equivalent filtering and throttling."""

    moment = now or datetime.now(UTC)
    async with pool.acquire() as connection:
        await connection.execute(_ENQUEUE, moment, BACKLOG_WINDOW)
        candidates: list[Any] = await connection.fetch(_CANDIDATES, moment, CHANNELS_PER_RUN)
        sent = 0
        for candidate in candidates:
            if await _deliver_channel(
                connection,
                candidate["channel_id"],
                clients=clients,
                cipher=cipher,
                base_url=base_url,
                now=moment,
            ):
                sent += 1
    return sent
