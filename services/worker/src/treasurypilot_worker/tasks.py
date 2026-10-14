import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.privacy import EncryptionConfigurationError, FieldCipher, FieldEncryptionKey
from treasurypilot_worker.celery_app import app
from treasurypilot_worker.chain.safe_config import refresh_safe_config_snapshots_sync
from treasurypilot_worker.config import get_settings
from treasurypilot_worker.locks import _asyncpg_database_url, create_worker_pool
from treasurypilot_worker.notify.publisher import publish_from_pool
from treasurypilot_worker.notify.telegram import HttpTelegramClient
from treasurypilot_worker.notify.telegram_sender import deliver_pending


@app.task(name="treasurypilot.system.core_probe", queue="core")
def core_probe() -> dict[str, str]:
    """Infrastructure probe; business tasks are added by execution tickets."""

    return {"status": "ok", "queue": "core"}


# Mirrors the EXPIRE rules in treasurypilot_api.invoices.state_machine (checked by a test);
# the worker cannot import the API package, so the sweep stays in SQL.
EXPIRABLE_REQUEST_STATUSES = ["Approved", "Scheduled", "AwaitingAuthority", "NeedsReview"]


async def _expire_invoice_approvals(database_url: str) -> int:
    conn = await asyncpg.connect(_asyncpg_database_url(database_url))
    try:
        async with conn.transaction():
            # Only expire signatures of requests the sweep may expire; Paying/Paid keep theirs.
            await conn.execute(
                "UPDATE approvals a SET status = 'Expired' FROM payment_requests r "
                "WHERE a.request_id = r.id AND a.status = 'Valid' AND a.expires_at <= now() "
                "AND r.status = ANY($1::text[])",
                EXPIRABLE_REQUEST_STATUSES,
            )
            rows = await conn.fetch(
                "WITH expired AS (SELECT r.id, r.status AS previous_status "
                "FROM payment_requests r WHERE r.status = ANY($1::text[]) "
                "AND EXISTS (SELECT 1 FROM approvals a WHERE a.request_id = r.id "
                "AND a.revision = r.current_revision AND a.status = 'Expired') "
                "AND NOT EXISTS (SELECT 1 FROM approvals a WHERE a.request_id = r.id "
                "AND a.revision = r.current_revision AND a.status = 'Valid') "
                "FOR UPDATE OF r), changed AS (UPDATE payment_requests r SET status = 'Expired', "
                "version = r.version + 1, updated_at = now() "
                "FROM expired e WHERE r.id = e.id RETURNING r.id, e.previous_status) "
                'INSERT INTO request_status_events (id, request_id, "from", "to", '
                "actor_type, actor_id, reason) "
                "SELECT gen_random_uuid(), id, previous_status, 'Expired', 'SYSTEM', NULL, "
                "'approval expired' FROM changed RETURNING request_id",
                EXPIRABLE_REQUEST_STATUSES,
            )
            return len(rows)
    finally:
        await conn.close()


@app.task(name="treasurypilot.invoices.expire_approvals", queue="core")
def expire_invoice_approvals() -> dict[str, int]:
    """Expire approval signatures and their still-payable requests atomically."""
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for invoice expiry")
    return {"requests_expired": asyncio.run(_expire_invoice_approvals(database_url))}


@app.task(name="treasurypilot.system.ai_probe", queue="ai")
def ai_probe() -> dict[str, str]:
    """AI queue probe. It performs no LLM call and accesses no signing material."""

    return {"status": "ok", "queue": "ai"}


@app.task(name="treasurypilot.treasury.refresh_safe_config_snapshots", queue="core")
def refresh_safe_config_task() -> dict[str, int]:
    """Poll each active treasury Safe and persist its latest observed configuration."""

    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for Safe configuration refresh")
    return {"snapshots_written": refresh_safe_config_snapshots_sync(database_url)}


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
    token = settings.telegram_bot_token
    if token is None or not token.get_secret_value().strip():
        return {"sent": 0}  # Telegram is optional: no token, no channel
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for Telegram delivery")
    try:
        cipher = FieldCipher(FieldEncryptionKey.from_environment())
    except EncryptionConfigurationError:
        logger.error("telegram_delivery_disabled_no_field_key")
        return {"sent": 0}
    client = HttpTelegramClient(token.get_secret_value())

    async def work(pool: Any) -> int:
        return await deliver_pending(
            pool, client=client, cipher=cipher, base_url=settings.app_base_url
        )

    return {"sent": _telegram.run(database_url, work)}
