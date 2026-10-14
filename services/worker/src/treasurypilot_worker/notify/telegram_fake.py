"""In-memory Telegram client for tests: records messages, can script failures."""

from __future__ import annotations

from collections import deque

from treasurypilot_worker.notify.telegram import TelegramError


class FakeTelegramClient:
    def __init__(self, *failures: TelegramError) -> None:
        self.sent: list[tuple[str, str]] = []
        self._failures = deque(failures)

    async def send_message(self, chat_id: str, text: str) -> None:
        if self._failures:
            raise self._failures.popleft()
        self.sent.append((chat_id, text))
