import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from treasurypilot_core.privacy import EncryptionConfigurationError, FieldCipher, FieldEncryptionKey
from treasurypilot_worker.celery_app import app
from treasurypilot_worker.config import get_settings
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.notify.publisher import publish_from_pool
from treasurypilot_worker.notify.telegram import HttpTelegramClient
from treasurypilot_worker.notify.telegram_sender import deliver_pending
from treasurypilot_worker.recovery.escalation import escalate_from_pool


@app.task(name="treasurypilot.system.core_probe", queue="core")
def core_probe() -> dict[str, str]:
    """Infrastructure probe; business tasks are added by execution tickets."""

    return {"status": "ok", "queue": "core"}


@app.task(name="treasurypilot.system.ai_probe", queue="ai")
def ai_probe() -> dict[str, str]:
    """AI queue probe. It performs no LLM call and accesses no signing material."""

    return {"status": "ok", "queue": "ai"}


class _PublisherRuntime:
    """One event loop and connection pool per worker process, reused across runs.

    The publish task fires every second; opening a pool (TCP + Postgres session) on
    every run would cost ~86k connections a day for a usually empty SELECT. A forked
    child (prefork pool) builds its own loop and pool on first use.
    """

    def __init__(self) -> None:
        self._pid: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pool: Any = None

    def publish(self, database_url: str) -> int:
        return self.run(database_url, publish_from_pool)

    def run(self, database_url: str, work: Callable[[Any], Awaitable[int]]) -> int:
        if self._pid != os.getpid() or self._loop is None:
            self._pid, self._loop, self._pool = os.getpid(), asyncio.new_event_loop(), None
        loop = self._loop

        async def run() -> int:
            if self._pool is None:
                self._pool = await create_worker_pool(database_url, min_size=1, max_size=1)
            return await work(self._pool)

        try:
            return loop.run_until_complete(run())
        except Exception:
            # A broken connection must not poison later runs: rebuild the pool next time.
            if self._pool is not None:
                pool, self._pool = self._pool, None
                loop.run_until_complete(pool.close())
            raise


_publisher = _PublisherRuntime()
_telegram = _PublisherRuntime()
logger = logging.getLogger(__name__)


@app.task(name="treasurypilot.notifications.publish-domain-events", queue="core")
def publish_domain_events() -> dict[str, int]:
    """Materialize pending in-app notifications from the PostgreSQL outbox."""

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for domain-event publishing")
    return {"published": _publisher.publish(database_url)}


@app.task(name="treasurypilot.notifications.deliver-telegram", queue="core")
def deliver_telegram() -> dict[str, int]:
    """Send ACTION/CRITICAL notifications to linked Telegram chats (NTF-003)."""

    settings = get_settings()
    if settings.telegram_bot_token is None:
        return {"sent": 0}  # Telegram is optional: no token, no channel
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for Telegram delivery")
    try:
        cipher = FieldCipher(FieldEncryptionKey.from_environment())
    except EncryptionConfigurationError:
        logger.error("telegram_delivery_disabled_no_field_key")
        return {"sent": 0}
    client = HttpTelegramClient(settings.telegram_bot_token.get_secret_value())

    async def work(pool: Any) -> int:
        return await deliver_pending(
            pool, client=client, cipher=cipher, base_url=settings.app_base_url
        )

    return {"sent": _telegram.run(database_url, work)}


@app.task(name="treasurypilot.recovery.escalate-overdue-review-items", queue="core")
def escalate_overdue_review_items() -> dict[str, int]:
    """Route overdue open review items to Owner and enqueue their notification."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for review-item escalation")

    async def escalate() -> int:
        pool = await create_worker_pool(database_url, min_size=1, max_size=1)
        try:
            return await escalate_from_pool(pool)
        finally:
            await pool.close()

    return {"escalated": asyncio.run(escalate())}
