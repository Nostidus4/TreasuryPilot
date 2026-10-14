import asyncio
import os
import time
from typing import Any

import asyncpg  # type: ignore[import-untyped]
from celery import Task

from treasurypilot_worker.audit_anchor import Web3AuditRootChain, publish_daily_audit_roots
from treasurypilot_worker.celery_app import app
from treasurypilot_worker.chain.safe_config import refresh_safe_config_snapshots_sync
from treasurypilot_worker.config import get_settings
from treasurypilot_worker.locks import _asyncpg_database_url, create_worker_pool
from treasurypilot_worker.notify.publisher import publish_from_pool
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
        if self._pid != os.getpid() or self._loop is None:
            self._pid, self._loop, self._pool = os.getpid(), asyncio.new_event_loop(), None
        loop = self._loop

        async def run() -> int:
            if self._pool is None:
                self._pool = await create_worker_pool(database_url, min_size=1, max_size=1)
            return await publish_from_pool(self._pool)

        try:
            return loop.run_until_complete(run())
        except Exception:
            # A broken connection must not poison later runs: rebuild the pool next time.
            if self._pool is not None:
                pool, self._pool = self._pool, None
                loop.run_until_complete(pool.close())
            raise


_publisher = _PublisherRuntime()


@app.task(name="treasurypilot.notifications.publish-domain-events", queue="core")
def publish_domain_events() -> dict[str, int]:
    """Materialize pending in-app notifications from the PostgreSQL outbox."""

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for domain-event publishing")
    return {"published": _publisher.publish(database_url)}


@app.task(name="treasurypilot.notifications.deliver-webhooks", queue="core")
def deliver_webhooks() -> dict[str, int]:
    """Deliver due webhook attempts; endpoints and payloads stay org-scoped in SQL."""

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for webhook delivery")

    async def deliver() -> int:
        pool = await create_worker_pool(database_url, min_size=1, max_size=1)
        try:
            async with pool.acquire() as connection:
                pending = await connection.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM webhook_deliveries AS delivery "
                    "JOIN webhook_endpoints AS endpoint ON endpoint.id=delivery.endpoint_id "
                    "AND endpoint.org_id=delivery.org_id WHERE endpoint.enabled "
                    "AND delivery.status IN ('pending', 'retrying') "
                    "AND delivery.next_attempt_at <= now())"
                )
                if not pending:
                    return 0
                encryption_key = FieldEncryptionKey.from_environment()
                return await deliver_pending_webhooks(connection, encryption_key=encryption_key)
        finally:
            await pool.close()

    return {"delivered": asyncio.run(deliver())}
