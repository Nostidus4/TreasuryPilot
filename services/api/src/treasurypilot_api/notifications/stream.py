"""Org-scoped SSE framing, resume cursor and polling loop (M13-D3, M13-D4, M13-D8).

The ``domain_events`` outbox and ``notifications`` tables are the source of truth, so
the loop polls them with a resumable cursor. A restart, a missed Redis message or a
dropped connection can therefore never lose an event: the client reconnects with
``Last-Event-ID`` and receives everything after it. Frames carry ids only.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

# domain_events.entity_type -> SSE event name. Entity types not listed here (for
# example Safe transactions) are not streamed.
EVENT_STREAM_TYPES: dict[str, str] = {
    "payment_request": "request.status",
    "plan": "plan.status",
    "operation": "operation.status",
    "review_item": "review.created",
    "treasury": "treasury.status",
}

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)


@dataclass(frozen=True, slots=True)
class StreamOptions:
    poll_interval: float = 1.0  # well inside the 2 s delivery target
    heartbeat_interval: float = 15.0
    # Bounds how long one authenticated connection lives; EventSource reconnects with
    # Last-Event-ID, which re-checks the session and membership.
    max_lifetime: float | None = 900.0
    batch_size: int = 100
    retry_ms: int = 2000


@dataclass(frozen=True, slots=True)
class StreamCursor:
    """Position in the two sources; carried in the SSE ``id`` field."""

    event_id: uuid.UUID
    notification_at: datetime
    notification_id: uuid.UUID

    def encode(self) -> str:
        micros = (self.notification_at - _EPOCH) // _MICROSECOND
        return f"{self.event_id}.{micros}.{self.notification_id}"


def parse_cursor(value: str | None) -> StreamCursor | None:
    """Decode ``Last-Event-ID``; anything malformed is ignored (fresh connection)."""
    if not value:
        return None
    parts = value.strip().split(".")
    if len(parts) != 3:
        return None
    try:
        micros = int(parts[1])
        return StreamCursor(
            event_id=uuid.UUID(parts[0]),
            notification_at=_EPOCH + timedelta(microseconds=micros),
            notification_id=uuid.UUID(parts[2]),
        )
    except (ValueError, OverflowError):
        return None


@dataclass(frozen=True, slots=True)
class StreamedEvent:
    id: uuid.UUID
    event_type: str
    entity_type: str
    entity_id: uuid.UUID
    treasury_id: uuid.UUID | None
    created_at: datetime
    ids: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class StreamedNotification:
    id: uuid.UUID
    event_id: uuid.UUID
    created_at: datetime
    severity: str


@dataclass(frozen=True, slots=True)
class StreamBatch:
    events: tuple[StreamedEvent, ...] = ()
    notifications: tuple[StreamedNotification, ...] = ()


class _Source(Protocol):
    async def stream_batch(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        cursor: StreamCursor,
        limit: int,
    ) -> StreamBatch: ...


def _frame(name: str, cursor: StreamCursor, data: Mapping[str, object]) -> str:
    return (
        f"id: {cursor.encode()}\nevent: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
    )


def event_frame(event: StreamedEvent, cursor: StreamCursor) -> str:
    data: dict[str, object] = {
        "eventId": str(event.id),
        "eventType": event.event_type,
        "entityType": event.entity_type,
        "entityId": str(event.entity_id),
        "treasuryId": str(event.treasury_id) if event.treasury_id else None,
        "at": event.created_at.isoformat(),
        **event.ids,
    }
    return _frame(EVENT_STREAM_TYPES[event.entity_type], cursor, data)


def notification_frame(item: StreamedNotification, cursor: StreamCursor) -> str:
    return _frame(
        "notification.created",
        cursor,
        {
            "notificationId": str(item.id),
            "eventId": str(item.event_id),
            "severity": item.severity,
            "at": item.created_at.isoformat(),
        },
    )


async def event_stream(
    source: _Source,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    cursor: StreamCursor,
    options: StreamOptions,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    """Yield SSE text frames until the client disconnects or the lifetime ends."""
    yield f"retry: {options.retry_ms}\n\n"
    started = last_sent = time.monotonic()
    while True:
        batch = await source.stream_batch(
            organization_id=organization_id,
            user_id=user_id,
            cursor=cursor,
            limit=options.batch_size,
        )
        for event in batch.events:
            cursor = replace(cursor, event_id=event.id)
            yield event_frame(event, cursor)
        for item in batch.notifications:
            cursor = replace(cursor, notification_at=item.created_at, notification_id=item.id)
            yield notification_frame(item, cursor)
        now = time.monotonic()
        if batch.events or batch.notifications:
            last_sent = now
            if (
                len(batch.events) >= options.batch_size
                or len(batch.notifications) >= options.batch_size
            ):
                continue  # more is waiting: drain without sleeping
        elif now - last_sent >= options.heartbeat_interval:
            last_sent = now
            yield ": heartbeat\n\n"
        if options.max_lifetime is not None and now - started >= options.max_lifetime:
            return
        if await is_disconnected():
            return
        await asyncio.sleep(options.poll_interval)
