from __future__ import annotations

import asyncio

import pytest

from treasurypilot_worker.recovery.escalation import escalate_overdue_review_items


class _Transaction:
    async def __aenter__(self) -> _Transaction:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _Connection:
    def __init__(self) -> None:
        self.query = ""
        self.batch_size = 0

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def fetchval(self, query: str, batch_size: int) -> int:
        self.query = query
        self.batch_size = batch_size
        return 3


def test_overdue_review_escalation_claims_once_and_emits_owner_event() -> None:
    connection = _Connection()

    assert asyncio.run(escalate_overdue_review_items(connection, batch_size=7)) == 3  # type: ignore[arg-type]

    assert connection.batch_size == 7
    assert "FOR UPDATE SKIP LOCKED" in connection.query
    assert "assigned_role = 'Owner'" in connection.query
    assert "version = item.version + 1" in connection.query
    assert "'NeedsReview:Owner'" in connection.query
    assert "jsonb_build_object('requestId'" in connection.query


def test_escalation_rejects_non_positive_batch_size() -> None:
    with pytest.raises(ValueError, match="batch_size must be positive"):
        asyncio.run(escalate_overdue_review_items(_Connection(), batch_size=0))  # type: ignore[arg-type]
