import asyncio
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from functools import cache
from typing import Any

import asyncpg  # type: ignore[import-untyped]
from celery import Task
from minio.error import S3Error

from treasurypilot_core.privacy import EncryptionConfigurationError, FieldCipher, FieldEncryptionKey
from treasurypilot_worker.agent.factory import get_ai_adapter
from treasurypilot_worker.audit_anchor import Web3AuditRootChain, publish_daily_audit_roots
from treasurypilot_worker.celery_app import app
from treasurypilot_worker.chain.event_handlers import (
    activate_due_payees as activate_due_payees_in_pool,
)
from treasurypilot_worker.chain.indexer import index_events_sync
from treasurypilot_worker.chain.safe_config import refresh_safe_config_snapshots_sync
from treasurypilot_worker.chain.snapshot import snapshot_dashboards_sync
from treasurypilot_worker.config import get_settings
from treasurypilot_worker.executor.outbox import (
    HttpSignerClient,
    SignerUnavailable,
    StepExecution,
    execute_step,
)
from treasurypilot_worker.invoices.documents import MinioDocumentReader
from treasurypilot_worker.invoices.extraction import extract_invoice_document
from treasurypilot_worker.invoices.recurring import generate_due_recurring_drafts
from treasurypilot_worker.locks import (
    _asyncpg_database_url,
    create_worker_pool,
    treasury_advisory_xact_lock,
)
from treasurypilot_worker.mandate_expiry import expire_mandates
from treasurypilot_worker.notify.chat_adapters import ChatPlatform, HttpChatWebhookClient
from treasurypilot_worker.notify.chat_sender import deliver_chat_pending
from treasurypilot_worker.notify.delivery import deliver_pending_emails
from treasurypilot_worker.notify.publisher import publish_from_pool
from treasurypilot_worker.notify.telegram import HttpTelegramClient
from treasurypilot_worker.notify.telegram_sender import deliver_pending
from treasurypilot_worker.notify.webhooks import deliver_pending_webhooks
from treasurypilot_worker.runtime import MAX_TASK_RETRIES, RetryableTaskError
from treasurypilot_worker.tracker import track_transactions_sync
from treasurypilot_worker.trigger.cycles import (
    CycleResult,
    CycleSkipReason,
    run_execution_cycle,
    run_scheduling_cycle,
)


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


async def _expire_mandates(database_url: str) -> dict[str, int]:
    connection = await asyncpg.connect(_asyncpg_database_url(database_url))
    try:
        return await expire_mandates(connection)
    finally:
        await connection.close()


@app.task(name="treasurypilot.mandates.expire", queue="core")
def expire_mandate_versions() -> dict[str, int]:
    """Warn owners before expiry and stop loading mandates whose expiry has passed."""
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for mandate expiry")
    return asyncio.run(_expire_mandates(database_url))


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


@app.task(name="treasurypilot.chain.track-transactions", queue="core")
def track_transactions_task() -> dict[str, int]:
    """Advance every Submitted/Pending/Unknown transaction from chain facts (CHR-003)."""

    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for transaction tracking")
    return track_transactions_sync(database_url)


@app.task(name="treasurypilot.chain.snapshot_dashboards", queue="core")
def snapshot_dashboards_task() -> dict[str, int]:
    """Store a block-consistent DASHBOARD snapshot per live treasury; prune after 7 days."""

    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for dashboard snapshots")
    return {"snapshots_written": snapshot_dashboards_sync(database_url)}


@app.task(name="treasurypilot.chain.index-events", queue="core")
def index_events_task() -> dict[str, int]:
    """Read module, Safe and token logs into observed_events and update state (CHR-005/006)."""

    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for event indexing")
    return index_events_sync(database_url)


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
_execution_cycles = _PublisherRuntime()
_telegram = _PublisherRuntime()
_chat = _PublisherRuntime()
_webhooks = _PublisherRuntime()
_emails = _PublisherRuntime()
logger = logging.getLogger(__name__)


@app.task(name="treasurypilot.notifications.publish-domain-events", queue="core")
def publish_domain_events() -> dict[str, int]:
    """Materialize pending in-app notifications from the PostgreSQL outbox."""

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for domain-event publishing")

    def dispatch(event_id: uuid.UUID, treasury_id: uuid.UUID) -> None:
        app.send_task(
            "treasurypilot.execution.run_treasury_cycle",
            kwargs={"treasury_id": str(treasury_id), "event_id": str(event_id)},
            task_id=f"execution-cycle:{event_id}",
            queue="core",
        )

    async def publish(pool: Any) -> int:
        async with pool.acquire() as connection:
            from treasurypilot_worker.notify.publisher import publish_pending_events

            return await publish_pending_events(connection, dispatch_execution_cycle=dispatch)

    return {"published": _publisher.run(database_url, publish)}


async def _execute_treasury_cycle(pool: asyncpg.Pool, treasury_id: uuid.UUID) -> CycleResult:
    return await run_execution_cycle(
        treasury_id,
        lock_for=lambda item: treasury_advisory_xact_lock(pool, item),
        schedule_provider=None,
        plan_starter=None,
    )


async def _started_cycles(pool: asyncpg.Pool, treasury_id: uuid.UUID) -> int:
    return int((await _execute_treasury_cycle(pool, treasury_id)).started)


async def _run_all_treasury_cycles(pool: asyncpg.Pool, *, scheduling: bool) -> int:
    rows = await pool.fetch(
        "SELECT id FROM treasuries WHERE status IN ('Ready', 'Paused') ORDER BY id"
    )
    started = 0
    unavailable = 0
    for row in rows:
        treasury_id = row["id"]
        try:
            if scheduling:
                result = await run_scheduling_cycle(
                    treasury_id,
                    lock_for=lambda item: treasury_advisory_xact_lock(pool, item),
                    schedule_writer=None,
                )
            else:
                result = await _execute_treasury_cycle(pool, treasury_id)
        except Exception:
            # One treasury's failure must not abort the sweep or tear down the shared pool.
            logger.exception("treasury_cycle_failed", extra={"treasury_id": str(treasury_id)})
            continue
        started += int(result.started)
        unavailable += result.reason is CycleSkipReason.SCHEDULE_PROVIDER_UNAVAILABLE
    if unavailable:
        # Per-treasury results log this at DEBUG; one line per sweep is enough.
        logger.info(
            "execution_cycle_schedule_provider_unavailable",
            extra={"scheduling": scheduling, "treasuries": unavailable},
        )
    return started


@app.task(name="treasurypilot.execution.activate_due_payees", queue="core")
def activate_due_payees_task() -> dict[str, int]:
    """Activate Cooling payees on the first one second tick after active_from."""
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for payee activation")

    async def activate(pool: asyncpg.Pool) -> int:
        return await activate_due_payees_in_pool(pool)

    activated = _execution_cycles.run(database_url, activate)
    return {"payees_activated": activated}


@app.task(name="treasurypilot.execution.run_treasury_cycle", queue="core")
def run_treasury_cycle_task(treasury_id: str, event_id: str | None = None) -> dict[str, int]:
    """Enter a per-treasury cycle after a durable event enqueue."""
    del (
        event_id
    )  # The outbox event is the enqueue identity; locks/planner claims provide idempotence.
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for execution cycles")
    cycles_started = _execution_cycles.run(
        database_url,
        lambda pool: _started_cycles(pool, uuid.UUID(treasury_id)),
    )
    return {"cycles_started": cycles_started}


@app.task(name="treasurypilot.execution.scheduling_cycle", queue="core")
def scheduling_cycle_task() -> dict[str, int]:
    """Refresh deadline schedules every 15 minutes when the EXE-004 provider is installed."""
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for execution scheduling")
    started = _execution_cycles.run(
        database_url, lambda pool: _run_all_treasury_cycles(pool, scheduling=True)
    )
    return {"schedules_refreshed": started}


@app.task(name="treasurypilot.execution.safety_cycle", queue="core")
def safety_cycle_task() -> dict[str, int]:
    """Run a 60 second safety sweep across all active and paused treasuries."""
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for execution safety cycles")
    started = _execution_cycles.run(
        database_url, lambda pool: _run_all_treasury_cycles(pool, scheduling=False)
    )
    return {"cycles_started": started}


@app.task(name="treasurypilot.invoices.generate-recurring-drafts", queue="core")
def generate_recurring_drafts_task() -> dict[str, int]:
    """Generate due payment drafts from active recurring templates."""

    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for recurring draft generation")

    async def run() -> dict[str, int]:
        pool = await create_worker_pool(database_url, min_size=1, max_size=1)
        try:
            async with pool.acquire() as connection:
                return await generate_due_recurring_drafts(connection)
        finally:
            await pool.close()

    return asyncio.run(run())


@app.task(name="treasurypilot.invoices.extract_document", queue="ai")
def extract_document_task(request_id: str, document_id: str) -> dict[str, str]:
    """Extract an uploaded invoice with the LLM; any AI failure leaves manual entry (AGT-004)."""

    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for invoice extraction")
    try:
        reader = MinioDocumentReader.from_settings(settings)
        outcome = extract_invoice_document(
            uuid.UUID(request_id),
            uuid.UUID(document_id),
            adapter=get_ai_adapter(),
            reader=reader,
            database_url=settings.database_url,
        )
    except (OSError, S3Error) as error:  # storage or database unreachable: safe to redeliver
        raise RetryableTaskError(f"invoice extraction infrastructure failure: {error}") from error
    return {"outcome": outcome}


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


@app.task(name="treasurypilot.notifications.deliver-chat", queue="webhooks")
def deliver_chat() -> dict[str, int]:
    """Send eligible notifications to Slack, Lark and WeCom webhooks (NTF-L03)."""

    settings = get_settings()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for chat notification delivery")
    try:
        cipher = FieldCipher(FieldEncryptionKey.from_environment())
    except EncryptionConfigurationError:
        logger.error("chat_delivery_disabled_no_field_key")
        return {"sent": 0}
    clients = {platform: HttpChatWebhookClient(platform) for platform in ChatPlatform}

    async def work(pool: Any) -> int:
        return await deliver_chat_pending(
            pool, clients=clients, cipher=cipher, base_url=settings.app_base_url
        )

    return {"sent": _chat.run(database_url, work)}


def _deliver_emails(cadence: str) -> dict[str, int]:
    settings = get_settings()
    key = settings.resend_api_key
    if key is None or not key.get_secret_value().strip() or not settings.resend_from_email:
        return {"sent": 0}  # email is optional: no provider configured, no channel
    unsubscribe_key = settings.email_unsubscribe_key
    if unsubscribe_key is None or len(unsubscribe_key.get_secret_value().encode()) < 32:
        logger.error("email_delivery_disabled_no_unsubscribe_key")
        return {"sent": 0}
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


@app.task(name="treasurypilot.execution.execute_step", queue="core")
def execute_step_task(step: dict[str, Any]) -> dict[str, Any]:
    """Outbox-execute one attested step: operation row, signer call, tx hash (EXE-007)."""

    settings = get_settings()
    if not (settings.database_url and settings.signer_url and settings.signer_shared_secret):
        raise RuntimeError("DATABASE_URL, TP_SIGNER_URL and TP_SIGNER_SHARED_SECRET are required")
    execution = StepExecution(
        treasury_id=uuid.UUID(step["treasury_id"]),
        request_id=uuid.UUID(step["request_id"]),
        plan_step_id=uuid.UUID(step["plan_step_id"]),
        step_id=bytes.fromhex(step["step_id"]),
        kind=step["kind"],
        chain_id=int(step["chain_id"]),
        sign_request=step["sign_request"],
    )
    signer = HttpSignerClient(settings.signer_url, settings.signer_shared_secret.get_secret_value())

    async def run() -> dict[str, Any]:
        pool = await create_worker_pool(settings.database_url or "", min_size=1, max_size=2)
        try:
            outcome = await execute_step(pool, signer, execution)
        finally:
            await pool.close()
        return {
            "operation_id": str(outcome.operation_id),
            "status": outcome.status,
            "tx_hash": outcome.tx_hash,
            "nonce": outcome.nonce,
        }

    try:
        return asyncio.run(run())
    except SignerUnavailable as error:
        # Same step_id on retry: the signer replays the original transaction, never a new one.
        raise RetryableTaskError(f"signer unavailable: {error}") from error
