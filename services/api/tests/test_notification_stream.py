from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from treasurypilot_api.identity.api import problem_response
from treasurypilot_api.identity.auth import AuthFailure, SessionAccess, UserRecord
from treasurypilot_api.identity.rbac import MemberAccess, organization_not_found, require_member
from treasurypilot_api.notifications.models import Notification
from treasurypilot_api.notifications.routes import router
from treasurypilot_api.notifications.stream import (
    StreamBatch,
    StreamCursor,
    StreamedEvent,
    StreamedNotification,
    StreamOptions,
    event_stream,
    parse_cursor,
)

ORG_ID = uuid.UUID("00000000-0000-4000-8000-000000000111")
OTHER_ORG_ID = uuid.UUID("00000000-0000-4000-8000-000000000999")
USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000333")
NIL = uuid.UUID(int=0)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
FAST = StreamOptions(poll_interval=0.01, heartbeat_interval=0.05, max_lifetime=0.3)


def _uuid7_at(at: datetime) -> uuid.UUID:
    millis = int(at.timestamp() * 1000)
    return uuid.UUID(int=(millis << 80) | (7 << 76) | (0x8 << 62) | uuid.uuid4().int % (1 << 62))


T0 = datetime(2026, 10, 14, tzinfo=UTC)


def _event(
    entity_type: str = "operation",
    ids: dict[str, str] | None = None,
    at: datetime | None = None,
) -> StreamedEvent:
    return StreamedEvent(
        id=_uuid7_at(at or T0),
        event_type="OperationConfirmed",
        entity_type=entity_type,
        entity_id=uuid.uuid4(),
        treasury_id=None,
        created_at=datetime(2026, 10, 14, tzinfo=UTC),
        ids=ids or {},
    )


class _Source:
    """In-memory source that applies the same org filter and cursor as the SQL one."""

    def __init__(self) -> None:
        self.events: dict[uuid.UUID, list[StreamedEvent]] = {ORG_ID: [], OTHER_ORG_ID: []}
        self.notifications: list[StreamedNotification] = []
        self.calls = 0

    async def stream_batch(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID, cursor: StreamCursor, limit: int
    ) -> StreamBatch:
        self.calls += 1
        events = [e for e in self.events[organization_id] if e.id > cursor.event_id]
        notes = [
            n
            for n in self.notifications
            if (n.created_at, n.id) > (cursor.notification_at, cursor.notification_id)
        ]
        return StreamBatch(tuple(sorted(events, key=lambda e: e.id)[:limit]), tuple(notes[:limit]))

    async def list_notifications(self, **_: object) -> tuple[tuple[Notification, ...], int]:
        return (), 0


async def _never() -> bool:
    return False


async def _collect(source: _Source, cursor: StreamCursor, org: uuid.UUID = ORG_ID) -> str:
    return "".join(
        [
            frame
            async for frame in event_stream(
                source,
                organization_id=org,
                user_id=USER_ID,
                cursor=cursor,
                options=FAST,
                is_disconnected=_never,
            )
        ]
    )


def _start() -> StreamCursor:
    return StreamCursor(NIL, EPOCH, NIL)


def test_cursor_round_trips_and_ignores_garbage() -> None:
    cursor = StreamCursor(
        uuid.uuid4(), datetime(2026, 10, 14, 1, 2, 3, 456789, tzinfo=UTC), uuid.uuid4()
    )
    assert parse_cursor(cursor.encode()) == cursor
    for bad in (None, "", "abc", "a.b.c", f"{uuid.uuid4()}.1", f"{uuid.uuid4()}.x.{uuid.uuid4()}"):
        assert parse_cursor(bad) is None


def test_stream_delivers_ids_only_frames_with_a_resume_id() -> None:
    source = _Source()
    event = _event(ids={"operationId": "op-id"})
    source.events[ORG_ID].append(event)
    source.notifications.append(
        StreamedNotification(uuid.uuid4(), event.id, event.created_at, "ACTION")
    )

    body = asyncio.run(_collect(source, _start()))

    assert body.startswith("retry: ")
    assert "event: operation.status\ndata: " in body
    assert "event: notification.created" in body
    assert body.count("id: ") == 2
    data = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert data[0]["entityId"] == str(event.entity_id)
    assert data[0]["operationId"] == "op-id"
    assert set(data[1]) == {"notificationId", "eventId", "severity", "at"}


def test_other_orgs_receive_nothing_and_get_heartbeats() -> None:
    source = _Source()
    source.events[ORG_ID].append(_event())

    body = asyncio.run(_collect(source, _start(), org=OTHER_ORG_ID))

    assert "event:" not in body
    assert ": heartbeat" in body


def test_resume_replays_only_events_after_last_event_id() -> None:
    source = _Source()
    events = [_event(at=T0 + timedelta(seconds=20 * i)) for i in range(3)]
    source.events[ORG_ID].extend(events)
    first = asyncio.run(_collect(source, _start()))
    last_id = [line[4:] for line in first.splitlines() if line.startswith("id: ")][-1]

    resumed_cursor = parse_cursor(last_id)
    assert resumed_cursor is not None
    resumed = asyncio.run(_collect(source, resumed_cursor))

    assert str(events[0].entity_id) not in resumed
    assert str(events[1].entity_id) not in resumed
    # The window may re-send the last event; clients de-duplicate on its stable ids.
    assert str(events[2].entity_id) in resumed


def test_stream_stops_when_the_client_disconnects() -> None:
    source = _Source()

    async def gone() -> bool:
        return True

    async def run() -> list[str]:
        return [
            f
            async for f in event_stream(
                source,
                organization_id=ORG_ID,
                user_id=USER_ID,
                cursor=_start(),
                options=StreamOptions(poll_interval=0.01, max_lifetime=None),
                is_disconnected=gone,
            )
        ]

    assert asyncio.run(run()) == ["retry: 2000\n\n"]
    assert source.calls == 1


def _client(source: _Source, *, member: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.notification_repository = source
    app.state.stream_options = FAST
    app.add_exception_handler(AuthFailure, problem_response)

    def non_member() -> MemberAccess:
        raise organization_not_found()

    def granted() -> MemberAccess:
        access = SessionAccess(
            user=UserRecord(USER_ID, "operator@example.test", None, "active"),
            session_id=uuid.UUID(int=1),
        )
        return MemberAccess(access=access, organization_id=ORG_ID, roles=frozenset({"Operator"}))

    app.dependency_overrides[require_member] = granted if member else non_member
    return TestClient(app)


def test_events_endpoint_streams_sse_headers_and_events() -> None:
    source = _Source()
    event = _event()
    source.events[ORG_ID].append(event)

    response = _client(source).get(
        f"/v1/orgs/{ORG_ID}/events",
        headers={"Last-Event-ID": StreamCursor(NIL, EPOCH, NIL).encode()},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert "event: operation.status" in response.text


def test_non_member_gets_404_on_every_endpoint() -> None:
    client = _client(_Source(), member=False)
    base = f"/v1/orgs/{ORG_ID}"
    assert client.get(f"{base}/events").status_code == 404
    assert client.get(f"{base}/notifications").status_code == 404
    assert (
        client.post(f"{base}/notifications/read", json={"ids": [str(uuid.uuid4())]}).status_code
        == 404
    )
    assert client.post(f"{base}/notifications/{uuid.uuid4()}/read").status_code == 404


class _Inbox(_Source):
    def __init__(self) -> None:
        super().__init__()
        self.read_calls: list[list[uuid.UUID]] = []
        self.matched = 0
        self.listed: dict[str, object] = {}

    async def list_notifications(self, **kwargs: object) -> tuple[tuple[Notification, ...], int]:
        self.listed = kwargs
        now = datetime(2026, 10, 14, tzinfo=UTC)
        row = Notification(
            id=uuid.uuid4(),
            org_id=ORG_ID,
            user_id=USER_ID,
            event_id=uuid.uuid4(),
            event_type="ApprovalNeeded",
            title="Approval required",
            body="A payment request is waiting for approval.",
            link="/requests/1",
            severity="ACTION",
            created_at=now,
            read_at=None,
        )
        return (row,), 3

    async def mark_read(self, *, ids: list[uuid.UUID], **_: object) -> int:
        self.read_calls.append(ids)
        return self.matched


def test_inbox_lists_own_notifications_with_unread_filter() -> None:
    inbox = _Inbox()
    response = _client(inbox).get(f"/v1/orgs/{ORG_ID}/notifications?unread=true&limit=5")

    assert response.status_code == 200
    body = response.json()
    assert body["unreadCount"] == 3
    assert body["items"][0]["title"] == "Approval required"
    assert set(body["items"][0]) == {
        "id",
        "eventId",
        "type",
        "title",
        "body",
        "link",
        "severity",
        "createdAt",
        "readAt",
    }
    assert inbox.listed == {
        "organization_id": ORG_ID,
        "user_id": USER_ID,
        "unread": True,
        "limit": 5,
    }


def test_mark_read_deduplicates_ids_and_reports_matches() -> None:
    inbox = _Inbox()
    inbox.matched = 1
    nid = uuid.uuid4()
    client = _client(inbox)

    response = client.post(
        f"/v1/orgs/{ORG_ID}/notifications/read", json={"ids": [str(nid), str(nid)]}
    )
    assert response.json() == {"updated": 1}
    assert inbox.read_calls == [[nid]]
    assert client.post(f"/v1/orgs/{ORG_ID}/notifications/read", json={"ids": []}).status_code == 422


def test_single_read_is_404_when_the_notification_is_not_the_callers() -> None:
    inbox = _Inbox()
    response = _client(inbox).post(f"/v1/orgs/{ORG_ID}/notifications/{uuid.uuid4()}/read")
    assert response.status_code == 404
    assert response.json()["code"] == "NOTIFICATION_NOT_FOUND"
    inbox.matched = 1
    assert (
        _client(inbox).post(f"/v1/orgs/{ORG_ID}/notifications/{uuid.uuid4()}/read").status_code
        == 200
    )


def test_streamed_batch_never_exceeds_the_limit_and_keeps_draining() -> None:
    source = _Source()
    base = datetime(2026, 10, 14, tzinfo=UTC)
    for index in range(5):
        source.notifications.append(
            StreamedNotification(
                uuid.uuid4(), uuid.uuid4(), base + timedelta(seconds=index), "INFO"
            )
        )
    options = StreamOptions(poll_interval=0.01, max_lifetime=0.1, batch_size=2)

    async def run() -> str:
        return "".join(
            [
                f
                async for f in event_stream(
                    source,
                    organization_id=ORG_ID,
                    user_id=USER_ID,
                    cursor=_start(),
                    options=options,
                    is_disconnected=_never,
                )
            ]
        )

    assert asyncio.run(run()).count("event: notification.created") == 5


def _collect_live(source: _Source, cursor: StreamCursor, publish: list[StreamedEvent]) -> str:
    """Run the stream; between polls, reveal one pending event per poll."""

    async def disconnected() -> bool:
        if publish:
            source.events[ORG_ID].append(publish.pop(0))
        return False

    async def run() -> str:
        return "".join(
            [
                f
                async for f in event_stream(
                    source,
                    organization_id=ORG_ID,
                    user_id=USER_ID,
                    cursor=cursor,
                    options=FAST,
                    is_disconnected=disconnected,
                )
            ]
        )

    return asyncio.run(run())


def test_late_committed_older_row_inside_window_is_delivered_exactly_once() -> None:
    source = _Source()
    newer = _event(at=T0 + timedelta(seconds=10))
    source.events[ORG_ID].append(newer)
    late = _event(at=T0 + timedelta(seconds=8))  # older id, becomes visible afterwards
    assert late.id < newer.id

    body = _collect_live(source, _start(), [late])

    assert body.count(str(newer.entity_id)) == 1
    assert body.count(str(late.entity_id)) == 1
    # The cursor never regressed: the late frame carries the newer event's position.
    ids = [line[4:] for line in body.splitlines() if line.startswith("id: ")]
    assert ids[0].split(".")[0] == ids[1].split(".")[0] == str(newer.id)


def test_rows_older_than_the_window_are_not_replayed() -> None:
    source = _Source()
    newer = _event(at=T0 + timedelta(seconds=60))
    source.events[ORG_ID].append(newer)
    stale = _event(at=T0 + timedelta(seconds=10))  # 50 s behind: outside the 5 s window

    body = _collect_live(source, _start(), [stale])

    assert str(newer.entity_id) in body
    assert str(stale.entity_id) not in body


def test_resume_resends_at_most_the_window_and_fresh_connection_marks_it_seen() -> None:
    source = _Source()
    inside = _event(at=T0 + timedelta(seconds=58))
    old = _event(at=T0 + timedelta(seconds=10))
    last = _event(at=T0 + timedelta(seconds=60))
    source.events[ORG_ID].extend([old, inside, last])
    cursor = StreamCursor(last.id, EPOCH, NIL)

    resumed = asyncio.run(_collect(source, cursor))
    assert str(inside.entity_id) in resumed  # duplicate within the window is acceptable
    assert str(old.entity_id) not in resumed

    async def fresh() -> str:
        return "".join(
            [
                f
                async for f in event_stream(
                    source,
                    organization_id=ORG_ID,
                    user_id=USER_ID,
                    cursor=cursor,
                    options=FAST,
                    is_disconnected=_never,
                    resumed=False,
                )
            ]
        )

    assert "event:" not in asyncio.run(fresh())
