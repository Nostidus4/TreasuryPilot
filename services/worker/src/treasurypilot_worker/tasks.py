import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from functools import cache
from typing import Any

import asyncpg  # type: ignore[import-untyped]
from celery import Task

from treasurypilot_core.privacy import EncryptionConfigurationError, FieldCipher, FieldEncryptionKey
from treasurypilot_worker.audit_anchor import Web3AuditRootChain, publish_daily_audit_roots
from treasurypilot_worker.celery_app import app
from treasurypilot_worker.chain.safe_config import refresh_safe_config_snapshots_sync
from treasurypilot_worker.config import get_settings
from treasurypilot_worker.locks import _asyncpg_database_url, create_worker_pool
from treasurypilot_worker.notify.delivery import deliver_pending_emails
from treasurypilot_worker.notify.publisher import publish_from_pool
from treasurypilot_worker.notify.telegram import HttpTelegramClient
from treasurypilot_worker.notify.telegram_sender import deliver_pending
from treasurypilot_worker.notify.webhooks import deliver_pending_webhooks
from treasurypilot_worker.runtime import MAX_TASK_RETRIES, RetryableTaskError


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


# Sequential receipt waits (up to 120s per organization); stays under the broker visibility timeout.
@app.task(name="treasurypilot.audit.publish-daily-roots", queue="core", bind=True, time_limit=1800)
def publish_daily_audit_roots_task(self: Task, utc_day: int | None = None) -> dict[str, int]:
    """Anchor each org's current audit head using the dedicated audit publisher key.

    The target UTC day is fixed on the first run and carried through retries.
    """

    if utc_day is None:
        utc_day = int(time.time()) // 86_400
    settings = get_settings()
    database_url = settings.database_url
    rpc_url = settings.audit_anchor_rpc_url
    chain_id = settings.audit_anchor_chain_id
    contract_address = settings.audit_anchor_contract_address
    private_key = settings.audit_anchor_private_key
    if (
        not database_url
        or not rpc_url
        or chain_id is None
        or not contract_address
        or private_key is None
    ):
        raise RuntimeError("database and complete TP_AUDIT_ANCHOR_* configuration are required")
    try:
        chain = Web3AuditRootChain(
            rpc_url=rpc_url,
            expected_chain_id=chain_id,
            contract_address=contract_address,
            private_key=private_key.get_secret_value(),
        )
        count = asyncio.run(publish_daily_audit_roots(database_url, chain, utc_day=utc_day))
    except Exception as exc:
        # A send may have succeeded even when its receipt timed out. A redelivery
        # re-reads the immutable on-chain day marker before attempting another send.
        # Avoid logging the exception text because RPC errors can echo credentialed URLs.
        # Autoretry would replay the original args, so retry explicitly with the fixed day.
        raise self.retry(
            args=(utc_day,),
            exc=RetryableTaskError(f"daily audit root publication failed ({type(exc).__name__})"),
            countdown=min(2**self.request.retries, 60),
            max_retries=MAX_TASK_RETRIES,
        ) from None
    return {"roots_published": count}


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
                try:
                    loop.run_until_complete(pool.close())
                except Exception:  # a dead pool must not mask the original error
                    logger.warning("worker_pool_close_failed", exc_info=True)
            raise


_publisher = _PublisherRuntime()
_telegram = _PublisherRuntime()
_webhooks = _PublisherRuntime()
_emails = _PublisherRuntime()
logger = logging.getLogger(__name__)


@app.task(name="treasurypilot.notifications.publish-domain-events", queue="core")
def publish_domain_events() -> dict[str, int]:
    """Materialize pending in-app notifications from the PostgreSQL outbox."""

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for domain-event publishing")
    return {"published": _publisher.publish(database_url)}


# Outbound-egress tasks run on the "webhooks" queue: its worker is the only one with public
# egress and holds the field key and bot token but not the policy keystore.
@app.task(name="treasurypilot.notifications.deliver-telegram", queue="webhooks")
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


@cache
def _webhook_encryption_key() -> FieldEncryptionKey:
    return FieldEncryptionKey.from_environment()


async def _deliver_webhooks(pool: Any) -> int:
    async with pool.acquire() as connection:
        return await deliver_pending_webhooks(connection, encryption_key=_webhook_encryption_key())


@app.task(name="treasurypilot.notifications.deliver-webhooks", queue="webhooks")
def deliver_webhooks() -> dict[str, int]:
    """Deliver due webhook attempts; endpoints and payloads stay org-scoped in SQL."""

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for webhook delivery")
    return {"delivered": _webhooks.run(database_url, _deliver_webhooks)}


def _deliver_emails(cadence: str) -> dict[str, int]:
    settings = get_settings()
    key = settings.resend_api_key
    if key is None or not key.get_secret_value().strip() or not settings.resend_from_email:
        return {"sent": 0}  # email is optional: no provider configured, no channel
    database_url = settings.database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for notification email delivery")

    async def work(pool: Any) -> int:
        return (await deliver_pending_emails(pool, settings=settings, cadence=cadence))["sent"]

    return {"sent": _emails.run(database_url, work)}


# Resend is an external HTTPS API, so email runs on the egress-capable "webhooks" queue.
@app.task(name="treasurypilot.notifications.send-emails", queue="webhooks")
def send_notification_emails() -> dict[str, int]:
    """Deliver immediate and mandatory notification mail."""
    return _deliver_emails("immediate")


@app.task(name="treasurypilot.notifications.send-daily-digests", queue="webhooks")
def send_daily_notification_digests() -> dict[str, int]:
    """Deliver 08:00 UTC digests to users who selected daily email."""
    return _deliver_emails("daily")
