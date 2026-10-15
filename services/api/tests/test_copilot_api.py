from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from treasurypilot_api.copilot import api
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
