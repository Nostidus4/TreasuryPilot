"""Copilot threads and messages (F-090). Read-only: the answer comes from `CopilotAnswerer`,
which runs the worker's tool loop; this API stores the exchange and streams it as SSE."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.copilot.models import CopilotMessage, CopilotThread
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.treasury.models import Treasury

_ROLES = (
    OrganizationRole.OWNER,
    OrganizationRole.FINANCE,
    OrganizationRole.OPERATOR,
    OrganizationRole.AUDITOR,
)


@dataclass(frozen=True)
class CopilotReply:
    answer: str
    citations: list[dict[str, Any]]
    ai_call_id: uuid.UUID | None = None


class CopilotAnswerer(Protocol):
    async def answer(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID, text: str
    ) -> CopilotReply:
        """Raises `AuthFailure` 503 `AI_UNAVAILABLE` or 429 `AI_BUDGET_EXCEEDED`."""
        ...


class CopilotRepository(Protocol):
    async def create_thread(self, *, org_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID: ...

    async def thread_exists(
        self, *, org_id: uuid.UUID, user_id: uuid.UUID, thread_id: uuid.UUID
    ) -> bool: ...

    async def add_message(
        self,
        *,
        thread_id: uuid.UUID,
        role: str,
        content: str,
        citations: list[dict[str, Any]] | None = None,
        ai_call_id: uuid.UUID | None = None,
    ) -> uuid.UUID: ...

    async def add_exchange(
        self, *, thread_id: uuid.UUID, question: str, reply: CopilotReply
    ) -> uuid.UUID:
        """Stores the user and assistant messages in one transaction; returns the answer id."""
        ...

    async def treasury_in_org(self, *, org_id: uuid.UUID, treasury_id: uuid.UUID) -> bool: ...

    async def messages(self, *, thread_id: uuid.UUID) -> list[CopilotMessage]: ...


class SqlAlchemyCopilotRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create_thread(self, *, org_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
        async with self._sessions() as session, session.begin():
            thread = CopilotThread(org_id=org_id, user_id=user_id)
            session.add(thread)
            await session.flush()
            return thread.id

    async def thread_exists(
        self, *, org_id: uuid.UUID, user_id: uuid.UUID, thread_id: uuid.UUID
    ) -> bool:
        async with self._sessions() as session:
            found = await session.scalar(
                select(CopilotThread.id).where(
                    CopilotThread.id == thread_id,
                    CopilotThread.org_id == org_id,
                    CopilotThread.user_id == user_id,
                )
            )
            return found is not None

    async def add_message(
        self,
        *,
        thread_id: uuid.UUID,
        role: str,
        content: str,
        citations: list[dict[str, Any]] | None = None,
        ai_call_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        async with self._sessions() as session, session.begin():
            message = CopilotMessage(
                thread_id=thread_id,
                role=role,
                content=content,
                citations=citations or [],
                ai_call_id=ai_call_id,
            )
            session.add(message)
            await session.flush()
            return message.id

    async def add_exchange(
        self, *, thread_id: uuid.UUID, question: str, reply: CopilotReply
    ) -> uuid.UUID:
        async with self._sessions() as session, session.begin():
            session.add(CopilotMessage(thread_id=thread_id, role="user", content=question))
            await session.flush()  # the user row sorts first
            answer = CopilotMessage(
                thread_id=thread_id,
                role="assistant",
                content=reply.answer,
                citations=reply.citations,
                ai_call_id=reply.ai_call_id,
            )
            session.add(answer)
            await session.flush()
            return answer.id

    async def treasury_in_org(self, *, org_id: uuid.UUID, treasury_id: uuid.UUID) -> bool:
        async with self._sessions() as session:
            found = await session.scalar(
                select(Treasury.id).where(Treasury.id == treasury_id, Treasury.org_id == org_id)
            )
            return found is not None

    async def messages(self, *, thread_id: uuid.UUID) -> list[CopilotMessage]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(CopilotMessage)
                .where(CopilotMessage.thread_id == thread_id)
                .order_by(CopilotMessage.created_at, CopilotMessage.id)
            )
            return list(rows)


class ThreadResponse(ApiModel):
    thread_id: uuid.UUID


class AskRequest(ApiModel):
    text: str = Field(min_length=1, max_length=2_000)
    treasury_id: uuid.UUID


class CitationView(ApiModel):
    tool_call_id: str
    path: str


class MessageView(ApiModel):
    id: uuid.UUID
    role: str
    content: str
    citations: list[CitationView]
    created_at: datetime


class ThreadHistory(ApiModel):
    messages: list[MessageView]


def unavailable() -> AuthFailure:
    return AuthFailure(
        status=503,
        code="AI_UNAVAILABLE",
        title="AI unavailable",
        detail="The Copilot is unavailable. The deterministic dashboard is still current.",
    )


def budget_exceeded() -> AuthFailure:
    return AuthFailure(
        status=429,
        code="AI_BUDGET_EXCEEDED",
        title="AI budget exceeded",
        detail="The monthly AI budget is spent. The deterministic dashboard is still current.",
    )


def _repository(request: Request) -> CopilotRepository:
    repository = getattr(request.app.state, "copilot_repository", None)
    if repository is None:
        raise unavailable()
    return cast(CopilotRepository, repository)


async def _owned_thread(
    request: Request, member: MemberAccess, thread_id: uuid.UUID
) -> CopilotRepository:
    repository = _repository(request)
    if not await repository.thread_exists(
        org_id=member.organization_id, user_id=member.user_id, thread_id=thread_id
    ):
        raise AuthFailure(
            status=404,
            code="THREAD_NOT_FOUND",
            title="Thread not found",
            detail="The Copilot thread does not exist.",
        )
    return repository


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


router = APIRouter(prefix="/v1/orgs/{organization_id}/copilot", tags=["copilot"])
_require_member = require_role(*_ROLES)


@router.post(
    "/threads",
    response_model=ThreadResponse,
    status_code=201,
    openapi_extra={"x-organization-scoped": True},
)
async def create_thread(
    organization_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_require_member),  # noqa: B008
) -> ThreadResponse:
    thread_id = await _repository(request).create_thread(
        org_id=member.organization_id, user_id=member.user_id
    )
    return ThreadResponse(thread_id=thread_id)


@router.get(
    "/threads/{thread_id}",
    response_model=ThreadHistory,
    openapi_extra={"x-organization-scoped": True},
)
async def get_thread(
    organization_id: uuid.UUID,
    thread_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_require_member),  # noqa: B008
) -> ThreadHistory:
    repository = await _owned_thread(request, member, thread_id)
    rows = await repository.messages(thread_id=thread_id)
    return ThreadHistory(
        messages=[
            MessageView(
                id=row.id,
                role=row.role,
                content=row.content,
                citations=[CitationView(**c) for c in row.citations],
                created_at=row.created_at,
            )
            for row in rows
        ]
    )


@router.post(
    "/threads/{thread_id}/messages",
    response_class=StreamingResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def ask(
    organization_id: uuid.UUID,
    thread_id: uuid.UUID,
    body: AskRequest,
    request: Request,
    member: MemberAccess = Depends(_require_member),  # noqa: B008
) -> StreamingResponse:
    repository = await _owned_thread(request, member, thread_id)
    answerer = cast(CopilotAnswerer | None, getattr(request.app.state, "copilot_answerer", None))
    if answerer is None:
        raise unavailable()
    if not await repository.treasury_in_org(
        org_id=member.organization_id, treasury_id=body.treasury_id
    ):
        raise AuthFailure(
            status=404,
            code="TREASURY_NOT_FOUND",
            title="Treasury not found",
            detail="Treasury not found.",
        )
    # Errors (503/429) surface before the stream starts, as plain problem responses; nothing
    # is stored for a failed turn, so a thread never holds an unanswered question.
    reply = await answerer.answer(
        organization_id=member.organization_id, treasury_id=body.treasury_id, text=body.text
    )
    message_id = await repository.add_exchange(thread_id=thread_id, question=body.text, reply=reply)

    async def events() -> AsyncIterator[str]:
        yield _sse("message", {"messageId": str(message_id)})
        # The post-checked answer is released whole; only checked text reaches the client.
        yield _sse("answer", {"text": reply.answer, "citations": reply.citations})
        yield _sse("done", {})

    return StreamingResponse(events(), media_type="text/event-stream")
