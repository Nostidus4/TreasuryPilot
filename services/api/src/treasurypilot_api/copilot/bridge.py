"""Copilot answers from the worker: `treasurypilot.copilot.ask` on the `ai` queue (F-090)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from celery import Celery

from treasurypilot_api.config import Settings
from treasurypilot_api.copilot.api import CopilotReply, budget_exceeded, unavailable

COPILOT_TASK = "treasurypilot.copilot.ask"
# The worker's COPILOT deadline is 30 s (config/ai.yaml); the margin covers queueing.
ANSWER_TIMEOUT_S = 40.0


class CeleryCopilotAnswerer:
    def __init__(self, redis_url: str, *, client: Any = None, timeout_s: float = ANSWER_TIMEOUT_S):
        # The result backend is needed: the answer comes back through it.
        self.client = client or Celery("treasurypilot-api", broker=redis_url, backend=redis_url)
        self._timeout_s = timeout_s

    async def answer(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID, text: str
    ) -> CopilotReply:
        try:
            result = self.client.send_task(
                COPILOT_TASK, args=[str(organization_id), str(treasury_id), text], queue="ai"
            )
            payload = await asyncio.to_thread(result.get, timeout=self._timeout_s)
        except Exception as error:  # broker down, timeout, task crash: all mean "unavailable"
            raise unavailable() from error
        if not isinstance(payload, dict):
            raise unavailable()
        if payload.get("error") == "AI_BUDGET_EXCEEDED":
            raise budget_exceeded()
        if "error" in payload or "answer" not in payload:
            raise unavailable()
        call_id = payload.get("ai_call_id")
        return CopilotReply(
            answer=payload["answer"],
            citations=payload.get("citations", []),
            ai_call_id=uuid.UUID(call_id) if call_id else None,
        )


def build_copilot_answerer(settings: Settings) -> CeleryCopilotAnswerer | None:
    if settings.redis_url is None:
        return None
    return CeleryCopilotAnswerer(settings.redis_url.get_secret_value())
