import asyncio
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from functools import cache
from typing import Any

import asyncpg  # type: ignore[import-untyped]
from celery import Task
from minio.error import S3Error

from treasurypilot_core.privacy import EncryptionConfigurationError, FieldCipher, FieldEncryptionKey
from treasurypilot_worker.agent.copilot import ask_copilot
from treasurypilot_worker.agent.errors import AiBudgetExceeded, AiError
from treasurypilot_worker.agent.factory import get_ai_adapter
from treasurypilot_worker.agent.tools.backend import PostgresToolBackend
from treasurypilot_worker.agent.tools.read_only import build_tools
from treasurypilot_worker.audit_anchor import Web3AuditRootChain, publish_daily_audit_roots
from treasurypilot_worker.celery_app import SCAN_TASK, app
from treasurypilot_worker.chain.event_handlers import (
    activate_due_payees as activate_due_payees_in_pool,
)
from treasurypilot_worker.chain.indexer import index_events_sync
from treasurypilot_worker.chain.rpc import build_rpc_client, decode_rpc_urls
from treasurypilot_worker.chain.safe_config import refresh_safe_config_snapshots_sync
from treasurypilot_worker.chain.snapshot import snapshot_dashboards_sync
from treasurypilot_worker.config import get_settings
from treasurypilot_worker.executor.gate import PlanGate
from treasurypilot_worker.executor.outbox import (
    HttpSignerClient,
    SignerRefused,
    SignerUnavailable,
    StepExecution,
    TreasuryPaused,
    execute_step,
)
from treasurypilot_worker.executor.plan_loader import load_plan, plan_run, simulation_context
from treasurypilot_worker.executor.sequencer import PlanRun, sequence_plan
from treasurypilot_worker.invoices.documents import MinioDocumentReader
from treasurypilot_worker.invoices.extraction import extract_invoice_document
from treasurypilot_worker.invoices.recurring import generate_due_recurring_drafts
from treasurypilot_worker.locks import (
    _asyncpg_database_url,
    create_worker_pool,
    treasury_advisory_xact_lock,
)
from treasurypilot_worker.low_gas import check_low_gas
from treasurypilot_worker.mandate_expiry import expire_mandates
from treasurypilot_worker.notify.chat_adapters import ChatPlatform, HttpChatWebhookClient
from treasurypilot_worker.notify.chat_sender import deliver_chat_pending
from treasurypilot_worker.notify.delivery import deliver_pending_emails
from treasurypilot_worker.notify.publisher import publish_from_pool
from treasurypilot_worker.notify.telegram import HttpTelegramClient
from treasurypilot_worker.notify.telegram_sender import deliver_pending
from treasurypilot_worker.notify.webhooks import deliver_pending_webhooks
from treasurypilot_worker.planner.ai import PROPOSE_TASK, run_proposal
from treasurypilot_worker.planner.context import load_inputs
from treasurypilot_worker.planner.pipeline import plan_request
from treasurypilot_worker.planner.reattest import reattest_fn
from treasurypilot_worker.planner.start import DbPlanStarter, DbScheduleProvider, DbScheduleWriter
from treasurypilot_worker.planner.wiring import build_attest, build_deps
from treasurypilot_worker.reconcile.auto_match import auto_match_reconciliations
from treasurypilot_worker.reconcile.verify import PostConditionVerifier
from treasurypilot_worker.recovery.circuit import evaluate_circuit_breakers, http_sentinel
from treasurypilot_worker.recovery.partial import cancel_partial, resume_partial
from treasurypilot_worker.recovery.scan import scan_in_flight_sync
from treasurypilot_worker.routing import treasury_queue
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


async def _check_low_gas(
    database_url: str, threshold_wei: int, configured: list[tuple[str, str | None]]
) -> dict[str, int]:
    connection = await asyncpg.connect(_asyncpg_database_url(database_url))
    try:
        return await check_low_gas(
            connection,
            lambda urls: build_rpc_client(decode_rpc_urls(urls)),
            threshold_wei,
            configured,
        )
    finally:
        await connection.close()


@app.task(name="treasurypilot.execution.check_low_gas", queue="core")
def check_low_gas_task() -> dict[str, int]:
    """Alert operators when an executor's native balance falls below the threshold."""
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for the low-gas check")
    configured = [
        ("executor", settings.executor_address),
        ("sentinel", settings.sentinel_address),
        ("receipt", settings.eas_receipt_address),
    ]
    return asyncio.run(
        _check_low_gas(settings.database_url, settings.low_gas_threshold_wei, configured)
    )


async def _auto_match(database_url: str) -> dict[str, int]:
    pool = await create_worker_pool(database_url, min_size=1, max_size=2)

    async def finalized_block(chain_id: int) -> int:
        urls = await pool.fetchval("SELECT rpc_urls FROM chains WHERE chain_id = $1", chain_id)
        block = await build_rpc_client(decode_rpc_urls(urls)).call(
            "eth_getBlockByNumber", ["finalized", False]
        )
        return int(block["number"], 16)

    try:
        return await auto_match_reconciliations(pool, finalized_block)
    finally:
        await pool.close()


@app.task(name="treasurypilot.reconciliation.auto_match", queue="core")
def auto_match_task() -> dict[str, int]:
    """Flag verification discrepancies and auto-match finalized, fully evidenced payments."""
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for reconciliation auto-match")
    return asyncio.run(_auto_match(database_url))


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
_planning = _PublisherRuntime()
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
            queue=treasury_queue(treasury_id, get_settings().treasury_queue_shards),
        )

    async def publish(pool: Any) -> int:
        async with pool.acquire() as connection:
            from treasurypilot_worker.notify.publisher import publish_pending_events

            return await publish_pending_events(connection, dispatch_execution_cycle=dispatch)

    return {"published": _publisher.run(database_url, publish)}


PLAN_ENQUEUE_COUNTDOWN_SECONDS = 1


def _enqueue_plan(plan_id: uuid.UUID, treasury_id: uuid.UUID) -> None:
    # The claim commits when the cycle's lock transaction ends; the countdown outlasts it and
    # the task retries if it still cannot see the row.
    app.send_task(
        "treasurypilot.planning.plan_request",
        kwargs={"plan_id": str(plan_id)},
        task_id=f"plan:{plan_id}",
        queue=treasury_queue(treasury_id, get_settings().treasury_queue_shards),
        countdown=PLAN_ENQUEUE_COUNTDOWN_SECONDS,
    )


async def _execute_treasury_cycle(pool: asyncpg.Pool, treasury_id: uuid.UUID) -> CycleResult:
    lead = timedelta(seconds=get_settings().execution_lead_time_seconds)
    return await run_execution_cycle(
        treasury_id,
        lock_for=lambda item: treasury_advisory_xact_lock(pool, item),
        schedule_provider=DbScheduleProvider(lead),
        plan_starter=DbPlanStarter(_enqueue_plan),
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
                    schedule_writer=DbScheduleWriter(
                        timedelta(seconds=get_settings().execution_lead_time_seconds)
                    ),
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


@app.task(name="treasurypilot.planning.plan_request", queue="core")
def plan_request_task(plan_id: str) -> dict[str, str]:
    """Run the planning pipeline for one claimed plan (EXE-004)."""
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for planning")

    async def plan(pool: Any) -> Any:
        try:
            return await plan_request(pool, uuid.UUID(plan_id), build_deps(pool, settings))
        except LookupError as error:  # the starter's transaction has not committed yet
            raise RetryableTaskError(str(error)) from error

    outcome: Any = _planning.run(settings.database_url, plan)
    return {"status": outcome.status if outcome else "AlreadyPlanned"}


@app.task(name=PROPOSE_TASK, queue="ai", ignore_result=False)
def propose_plan_task(org_id: str, treasury_id: str, eligible_ids: list[str]) -> dict[str, Any]:
    """AI plan proposal for the planning pipeline; failures return a code (BR-055)."""
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for plan proposals")
    return run_proposal(
        get_ai_adapter(),
        PostgresToolBackend(settings.database_url),
        org_id=org_id,
        treasury_id=treasury_id,
        eligible_ids=eligible_ids,
    )


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
    """Refresh deadline schedules every 15 minutes (advisory `schedules` row)."""
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


@app.task(name=SCAN_TASK, queue="core")
def scan_in_flight_task() -> dict[str, int]:
    """Resolve Submitted/Pending/Unknown operations from chain evidence (RCV-001)."""

    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for the in-flight scan")
    return scan_in_flight_sync(database_url)


@app.task(name="treasurypilot.recovery.circuit_breaker", queue="core")
def circuit_breaker_task() -> dict[str, int]:
    """Evaluate the BR-065 circuit rules every 60 s and auto-pause on a trip."""
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for circuit-breaker evaluation")
    secret = settings.signer_shared_secret
    sentinel = http_sentinel(settings.signer_url, secret.get_secret_value() if secret else None)
    return {
        "paused": _execution_cycles.run(
            settings.database_url, lambda pool: evaluate_circuit_breakers(pool, sentinel)
        )
    }


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


@app.task(name="treasurypilot.copilot.ask", queue="ai")
def copilot_ask_task(org_id: str, treasury_id: str, question: str) -> dict[str, Any]:
    """One read-only Copilot turn (F-090). Failures return a code: no exception crosses Celery."""

    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for the Copilot")
    # The tools take the treasury id as a model input and refuse any outside the organisation.
    try:
        reply = ask_copilot(
            get_ai_adapter(),
            org_id=org_id,
            question=question,
            treasury_id=treasury_id,
            tools=build_tools(PostgresToolBackend(settings.database_url), org_id),
        )
    except AiBudgetExceeded:
        return {"error": "AI_BUDGET_EXCEEDED"}
    except AiError:
        return {"error": "AI_UNAVAILABLE"}
    return {
        "answer": reply.answer,
        "citations": [c.model_dump() for c in reply.citations],
        "ai_call_id": reply.ai_call_id or None,
    }


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
    except TreasuryPaused:
        # Not retried: the Resumed event re-plans the queued requests.
        return {"status": "Paused"}
    except SignerRefused as error:
        # Definitive answer: retrying the same request cannot succeed (see TERMINAL_REFUSALS).
        return {"status": "Refused", "code": error.code, "terminal": error.terminal}
    except SignerUnavailable as error:
        # Same step_id on retry: the signer replays the original transaction, never a new one.
        raise RetryableTaskError(f"signer unavailable: {error}") from error


class PlanNotExecutable(Exception):
    """The plan cannot be turned into signer requests yet; nothing was validated or sent."""


def plan_fees() -> dict[str, int]:
    """The signer's ``fees`` body (maxFeePerGas, maxPriorityFeePerGas, feeCapWei).

    shortcut: no fee estimation exists in the worker yet (the accepted cap lives in the API's
    fee_acceptances); until EXE-005 supplies it the driver refuses to run rather than guess.
    """

    raise PlanNotExecutable("fee estimation is not wired")


_PLAN_STATUS = {
    "Waiting": "Executing",
    "Completed": "Completed",
    "PartiallyCompleted": "PartiallyCompleted",
}


async def _sequence_plan(plan_id: uuid.UUID) -> dict[str, Any]:
    settings = get_settings()
    secret = settings.signer_shared_secret
    assert settings.signer_url and secret  # checked by sequence_plan_task
    signer = HttpSignerClient(settings.signer_url, secret.get_secret_value())
    pool = await create_worker_pool(settings.database_url or "", min_size=1, max_size=3)
    try:
        loaded = await load_plan(pool, plan_id)
        if loaded is None:
            return {"status": "NoPlan"}
        async with treasury_advisory_xact_lock(pool, loaded.treasury_id) as lock:
            if lock is None:  # another worker is advancing this treasury; the sweep retries
                return {"status": "Locked"}
            inputs = await load_inputs(
                pool, loaded.plan, loaded.treasury_id, executor=loaded.executor
            )
            fees = plan_fees()
            run: PlanRun = plan_run(loaded, inputs, fees)
            urls = await pool.fetchval(
                "SELECT rpc_urls FROM chains WHERE chain_id = $1", loaded.plan.chain_id
            )
            rpc = build_rpc_client(decode_rpc_urls(urls))
            gate = PlanGate.for_treasury(
                pool,
                loaded.treasury_id,
                rpc=rpc,
                plan_id=plan_id,
                plan=loaded.plan,
                inputs=inputs,
                simulation=simulation_context(loaded, inputs),
                reattest_fn=reattest_fn(
                    pool, loaded, inputs, rpc=rpc, attest=build_attest(settings), fees=fees
                ),
            )
            verifier = PostConditionVerifier(
                pool,
                rpc,
                {step.step_id: step for step in loaded.plan.steps},
                loaded.plan.request_id,
                loaded.plan.treasury,
            )
            result = await sequence_plan(pool, signer, run, gate, verifier=verifier)
            # The sequencer only moves the request; the plan row follows its outcome.
            if plan_status := _PLAN_STATUS.get(result.status):
                await pool.execute(
                    "UPDATE plans SET status = $2, updated_at = now() "
                    "WHERE id = $1 AND status IN ('Attested', 'Executing')",
                    plan_id,
                    plan_status,
                )
            return {"status": result.status, "code": result.code, "completed": result.completed}
    finally:
        await pool.close()


@app.task(name="treasurypilot.execution.sequence_plan", queue="core")
def sequence_plan_task(plan_id: str) -> dict[str, Any]:
    """Advance one attested plan by at most one step (EXE-008)."""

    settings = get_settings()
    if not (settings.database_url and settings.signer_url and settings.signer_shared_secret):
        raise RuntimeError("DATABASE_URL, TP_SIGNER_URL and TP_SIGNER_SHARED_SECRET are required")
    try:
        return asyncio.run(_sequence_plan(uuid.UUID(plan_id)))
    except PlanNotExecutable as error:
        logger.warning("plan %s not executable: %s", plan_id, error)
        return {"status": "NotExecutable"}
    except SignerUnavailable as error:
        # The same step_id is replayed on retry, so a second attempt cannot double-pay.
        raise RetryableTaskError(f"signer unavailable: {error}") from error


async def _partial_action(
    action: Callable[..., Awaitable[Any]], request_id: str, actor_id: str | None
) -> Any:
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for partial-plan recovery")
    pool = await create_worker_pool(database_url, min_size=1, max_size=1)
    try:
        return await action(pool, uuid.UUID(request_id), uuid.UUID(actor_id) if actor_id else None)
    finally:
        await pool.close()


@app.task(name="treasurypilot.recovery.resume_partial", queue="core")
def resume_partial_task(request_id: str, actor_id: str | None = None) -> dict[str, str | None]:
    """INTERNAL: resume a PartiallyCompleted plan, then enqueue its next step (RCV-003).

    Not user-facing; the review-item RETRY action endpoint is RCV-004 follow-up work.
    """

    result = asyncio.run(_partial_action(resume_partial, request_id, actor_id))
    plan_id = str(result.plan_id) if result.plan_id else None
    if result.status == "Resumed":
        sequence_plan_task.apply_async(
            (str(result.plan_id),),
            queue=treasury_queue(result.treasury_id, get_settings().treasury_queue_shards),
        )
    return {"status": result.status, "plan_id": plan_id}


@app.task(name="treasurypilot.recovery.cancel_partial", queue="core")
def cancel_partial_task(request_id: str, actor_id: str | None = None) -> dict[str, Any]:
    """INTERNAL: cancel a PartiallyCompleted plan; funds of confirmed steps stay (RCV-003)."""

    report = asyncio.run(_partial_action(cancel_partial, request_id, actor_id))
    return {
        "cancelled": report.cancelled,
        "plan_id": str(report.plan_id) if report.plan_id else None,
        "completed_steps": list(report.completed_steps),
        "in_flight_steps": list(report.in_flight_steps),
        "summary": report.summary,
    }


# Plans whose request is still executing and whose newest operation is Confirmed, awaiting replay
# after a crash (NotSubmitted) or not started: the tracker's trigger may have been lost.
_SWEEP_SQL = (
    "SELECT DISTINCT ON (a.plan_id) a.plan_id, r.treasury_id FROM attestations a "
    "JOIN payment_requests r ON r.onchain_request_id = a.request_id "
    "WHERE r.status IN ('Preparing', 'Paying') AND COALESCE((SELECT o.status::text "
    "FROM operations o WHERE o.request_id = r.id ORDER BY o.created_at DESC, o.id DESC LIMIT 1), "
    "'Confirmed') IN ('Confirmed', 'NotSubmitted') "
    # Paused or revoked treasuries are skipped; the Resumed event re-enqueues the cycle.
    "AND NOT EXISTS (SELECT 1 FROM backend_pause b WHERE b.treasury_id = r.treasury_id "
    "AND b.paused) AND NOT EXISTS (SELECT 1 FROM treasuries t WHERE t.id = r.treasury_id "
    "AND t.status IN ('Paused', 'Revoked')) ORDER BY a.plan_id, a.created_at DESC"
)


@app.task(name="treasurypilot.execution.sequence_plans_sweep", queue="core")
def sequence_plans_sweep() -> dict[str, int]:
    """Re-enqueue plans that are ready for their next step (backstop for the tracker)."""

    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for plan sequencing")

    async def ids() -> list[Any]:
        pool = await create_worker_pool(database_url, min_size=1, max_size=1)
        try:
            return list(await pool.fetch(_SWEEP_SQL))
        finally:
            await pool.close()

    shards = get_settings().treasury_queue_shards
    rows = asyncio.run(ids())
    for row in rows:
        sequence_plan_task.apply_async(
            (str(row["plan_id"]),), queue=treasury_queue(row["treasury_id"], shards)
        )
    return {"plans": len(rows)}
