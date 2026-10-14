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
from collections import OrderedDict
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
_NIL_UUID = uuid.UUID(int=0)


@dataclass(frozen=True, slots=True)
class StreamOptions:
    poll_interval: float = 1.0  # well inside the 2 s delivery target
    heartbeat_interval: float = 15.0
    # Bounds how long one authenticated connection lives; EventSource reconnects with
    # Last-Event-ID, which re-checks the session and membership.
    max_lifetime: float | None = 900.0
    batch_size: int = 100
    retry_ms: int = 2000
    # Transactions can commit out of order, so a row older than the cursor may become
    # visible after the cursor passed it. Every poll therefore re-queries this far
    # behind the cursor and de-duplicates against ids already sent.
    lookback: timedelta = timedelta(seconds=5)
    sent_memory: int = 1000  # bounded per-connection set of already-sent ids


@dataclass(frozen=True, slots=True)
class StreamCursor:
    """Position in the two sources; carried in the SSE ``id`` field."""

    event_id: uuid.UUID
    notification_at: datetime
    notification_id: uuid.UUID

    def encode(self) -> str:
        micros = (self.notification_at - _EPOCH) // _MICROSECOND
        return f"{self.event_id}.{micros}.{self.notification_id}"


def _lookback_cursor(cursor: StreamCursor, window: timedelta) -> StreamCursor:
    """Cursor moved ``window`` back; domain event ids are uuid7 (48-bit ms prefix)."""
    event_id = cursor.event_id
    if event_id.int:
        millis = max((event_id.int >> 80) - int(window.total_seconds() * 1000), 0)
        event_id = uuid.UUID(int=millis << 80)
    return StreamCursor(event_id, cursor.notification_at - window, _NIL_UUID)


def _remember(sent: OrderedDict[uuid.UUID, None], item_id: uuid.UUID, limit: int) -> None:
    sent[item_id] = None
    while len(sent) > limit:
        sent.popitem(last=False)


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
    resumed: bool = True,
) -> AsyncIterator[str]:
    """Yield SSE text frames until the client disconnects or the lifetime ends.

    Each poll reads from ``cursor - options.lookback`` and skips ids already sent on
    this connection, so a late-committed row with an older id is still delivered once.
    A resumed connection (``Last-Event-ID``) starts with an empty sent set and may
    therefore re-send up to ``lookback`` of frames; frame payload ids are stable, so
    clients de-duplicate on ``eventId`` / ``notificationId``. A fresh connection
    (``resumed=False``) first marks the rows inside the window as already seen.
    """
    sent_events: OrderedDict[uuid.UUID, None] = OrderedDict()
    sent_notes: OrderedDict[uuid.UUID, None] = OrderedDict()
    memory = max(options.sent_memory, 1)
    if not resumed:
        primed = await source.stream_batch(
            organization_id=organization_id,
            user_id=user_id,
            cursor=_lookback_cursor(cursor, options.lookback),
            limit=memory,
        )
        for event in primed.events:
            if event.id <= cursor.event_id:
                _remember(sent_events, event.id, memory)
        for item in primed.notifications:
            if (item.created_at, item.id) <= (cursor.notification_at, cursor.notification_id):
                _remember(sent_notes, item.id, memory)
    yield f"retry: {options.retry_ms}\n\n"
    started = last_sent = time.monotonic()
    while True:
        # Room for the already-sent rows of the window plus a full page of new ones.
        limit = options.batch_size + memory
        batch = await source.stream_batch(
            organization_id=organization_id,
            user_id=user_id,
            cursor=_lookback_cursor(cursor, options.lookback),
            limit=limit,
        )
        fresh_events = [e for e in batch.events if e.id not in sent_events][: options.batch_size]
        fresh_notes = [n for n in batch.notifications if n.id not in sent_notes][
            : options.batch_size
        ]
        for event in fresh_events:
            _remember(sent_events, event.id, memory)
            cursor = replace(cursor, event_id=max(cursor.event_id, event.id))
            yield event_frame(event, cursor)
        for item in fresh_notes:
            _remember(sent_notes, item.id, memory)
            if (item.created_at, item.id) > (cursor.notification_at, cursor.notification_id):
                cursor = replace(cursor, notification_at=item.created_at, notification_id=item.id)
            yield notification_frame(item, cursor)
        now = time.monotonic()
        if fresh_events or fresh_notes:
            last_sent = now
            if len(fresh_events) >= options.batch_size or len(fresh_notes) >= options.batch_size:
                continue  # more is waiting: drain without sleeping
        elif now - last_sent >= options.heartbeat_interval:
            last_sent = now
            yield ": heartbeat\n\n"
        if options.max_lifetime is not None and now - started >= options.max_lifetime:
            return
        if await is_disconnected():
            return
        await asyncio.sleep(options.poll_interval)
