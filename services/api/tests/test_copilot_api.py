from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from treasurypilot_api.config import Settings
from treasurypilot_api.copilot import api
from treasurypilot_api.copilot.bridge import CeleryCopilotAnswerer, build_copilot_answerer
from treasurypilot_api.identity.auth import AuthFailure

ORG = uuid.uuid4()
USER = uuid.uuid4()
TREASURY = uuid.uuid4()


class _Repo:
    def __init__(self) -> None:
        self.threads: dict[uuid.UUID, tuple[uuid.UUID, uuid.UUID]] = {}
        self.rows: list[SimpleNamespace] = []

    async def create_thread(self, *, org_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
        thread_id = uuid.uuid4()
        self.threads[thread_id] = (org_id, user_id)
        return thread_id

    async def thread_exists(
        self, *, org_id: uuid.UUID, user_id: uuid.UUID, thread_id: uuid.UUID
    ) -> bool:
        return self.threads.get(thread_id) == (org_id, user_id)

    async def add_message(self, *, thread_id: uuid.UUID, role: str, content: str, **kw: Any):
        row = SimpleNamespace(
            id=uuid.uuid4(),
            thread_id=thread_id,
            role=role,
            content=content,
            citations=kw.get("citations") or [],
            created_at=datetime.now(UTC),
        )
        self.rows.append(row)
        return row.id

    async def add_exchange(self, *, thread_id: uuid.UUID, question: str, reply: Any) -> uuid.UUID:
        await self.add_message(thread_id=thread_id, role="user", content=question)
        return await self.add_message(
            thread_id=thread_id, role="assistant", content=reply.answer, citations=reply.citations
        )

    async def treasury_in_org(self, *, org_id: uuid.UUID, treasury_id: uuid.UUID) -> bool:
        return treasury_id == TREASURY

    async def messages(self, *, thread_id: uuid.UUID) -> list[SimpleNamespace]:
        return [r for r in self.rows if r.thread_id == thread_id]


class _Answerer:
    def __init__(self) -> None:
        self.asked: list[str] = []

    async def answer(self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID, text: str):
        self.asked.append(text)
        return api.CopilotReply("Shortage is 90000000.", [{"tool_call_id": "t1", "path": "$"}])


def _client(*, answerer: Any = None) -> tuple[TestClient, _Repo]:
    app = FastAPI()
    repo = _Repo()
    app.state.copilot_repository = repo
    app.state.copilot_answerer = answerer
    app.include_router(api.router)
    app.dependency_overrides[api._require_member] = lambda: SimpleNamespace(
        organization_id=ORG, user_id=USER
    )

    @app.exception_handler(AuthFailure)
    async def handler(request: Request, exc: AuthFailure) -> JSONResponse:
        return JSONResponse({"code": exc.code}, status_code=exc.status)

    return TestClient(app), repo


def test_ask_streams_cited_answer_and_stores_history() -> None:
    answerer = _Answerer()
    client, _ = _client(answerer=answerer)
    base = f"/v1/orgs/{ORG}/copilot/threads"
    thread_id = client.post(base).json()["threadId"]

    response = client.post(
        f"{base}/{thread_id}/messages", json={"text": "shortage?", "treasuryId": str(TREASURY)}
    )

    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: answer" in response.text and "90000000" in response.text
    assert response.text.rstrip().endswith("event: done\ndata: {}")
    history = client.get(f"{base}/{thread_id}").json()["messages"]
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[1]["citations"] == [{"toolCallId": "t1", "path": "$"}]


def test_unknown_or_foreign_thread_is_404() -> None:
    client, repo = _client(answerer=_Answerer())
    repo.threads[(other := uuid.uuid4())] = (ORG, uuid.uuid4())  # another user's thread
    for thread in (uuid.uuid4(), other):
        r = client.get(f"/v1/orgs/{ORG}/copilot/threads/{thread}")
        assert r.status_code == 404


def test_without_answerer_ask_is_503_ai_unavailable() -> None:
    client, _ = _client()
    base = f"/v1/orgs/{ORG}/copilot/threads"
    thread_id = client.post(base).json()["threadId"]
    r = client.post(f"{base}/{thread_id}/messages", json={"text": "q", "treasuryId": str(TREASURY)})
    assert (r.status_code, r.json()["code"]) == (503, "AI_UNAVAILABLE")


def test_unknown_treasury_is_404() -> None:
    client, _ = _client(answerer=_Answerer())
    base = f"/v1/orgs/{ORG}/copilot/threads"
    thread_id = client.post(base).json()["threadId"]
    r = client.post(
        f"{base}/{thread_id}/messages", json={"text": "q", "treasuryId": str(uuid.uuid4())}
    )
    assert (r.status_code, r.json()["code"]) == (404, "TREASURY_NOT_FOUND")


def test_failed_answer_stores_no_orphan_user_message() -> None:
    class Budget:
        async def answer(self, **kw: Any) -> Any:
            raise api.budget_exceeded()

    client, repo = _client(answerer=Budget())
    base = f"/v1/orgs/{ORG}/copilot/threads"
    thread_id = client.post(base).json()["threadId"]
    r = client.post(f"{base}/{thread_id}/messages", json={"text": "q", "treasuryId": str(TREASURY)})
    assert (r.status_code, r.json()["code"]) == (429, "AI_BUDGET_EXCEEDED")
    assert repo.rows == []


class _FakeResult:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def get(self, timeout: float) -> Any:
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


class _FakeCelery:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.sent: list[tuple[str, list[str], str]] = []

    def send_task(self, name: str, args: list[str], queue: str) -> _FakeResult:
        self.sent.append((name, args, queue))
        return _FakeResult(self.payload)


async def _ask(payload: Any) -> tuple[Any, _FakeCelery]:
    celery = _FakeCelery(payload)
    answerer = CeleryCopilotAnswerer("redis://x", client=celery)
    reply = await answerer.answer(organization_id=ORG, treasury_id=TREASURY, text="q")
    return reply, celery


def test_celery_answerer_returns_worker_answer() -> None:
    call_id = uuid.uuid4()
    reply, celery = asyncio.run(
        _ask(
            {
                "answer": "A",
                "citations": [{"tool_call_id": "t", "path": "$"}],
                "ai_call_id": str(call_id),
            }
        )
    )
    assert (reply.answer, reply.ai_call_id) == ("A", call_id)
    assert celery.sent == [("treasurypilot.copilot.ask", [str(ORG), str(TREASURY), "q"], "ai")]


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        ({"error": "AI_BUDGET_EXCEEDED"}, 429, "AI_BUDGET_EXCEEDED"),
        ({"error": "AI_UNAVAILABLE"}, 503, "AI_UNAVAILABLE"),
        (TimeoutError("slow"), 503, "AI_UNAVAILABLE"),
    ],
)
def test_celery_answerer_maps_failures(payload: Any, status: int, code: str) -> None:
    with pytest.raises(AuthFailure) as caught:
        asyncio.run(_ask(payload))
    assert (caught.value.status, caught.value.code) == (status, code)


def test_no_redis_means_no_answerer() -> None:
    assert build_copilot_answerer(Settings(redis_url=None)) is None
