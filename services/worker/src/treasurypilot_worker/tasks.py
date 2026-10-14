import asyncio
import os
from typing import Any

from treasurypilot_worker.audit_anchor import Web3AuditRootChain, publish_daily_audit_roots
from treasurypilot_worker.celery_app import app
from treasurypilot_worker.chain.safe_config import refresh_safe_config_snapshots_sync
from treasurypilot_worker.config import get_settings
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.notify.publisher import publish_from_pool
from treasurypilot_worker.runtime import RetryableTaskError


@app.task(name="treasurypilot.system.core_probe", queue="core")
def core_probe() -> dict[str, str]:
    """Infrastructure probe; business tasks are added by execution tickets."""

    return {"status": "ok", "queue": "core"}


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


@app.task(name="treasurypilot.audit.publish-daily-roots", queue="core")
def publish_daily_audit_roots_task() -> dict[str, int]:
    """Anchor each org's current audit head using the dedicated audit publisher key."""

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
    assert database_url is not None
    assert rpc_url is not None
    assert chain_id is not None
    assert contract_address is not None
    assert private_key is not None
    chain = Web3AuditRootChain(
        rpc_url=rpc_url,
        expected_chain_id=chain_id,
        contract_address=contract_address,
        private_key=private_key.get_secret_value(),
    )
    try:
        count = asyncio.run(publish_daily_audit_roots(database_url, chain))
    except Exception as exc:
        # A send may have succeeded even when its receipt timed out. A redelivery
        # re-reads the immutable on-chain day marker before attempting another send.
        # Avoid logging the exception text because RPC errors can echo credentialed URLs.
        raise RetryableTaskError(
            f"daily audit root publication failed ({type(exc).__name__})"
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
