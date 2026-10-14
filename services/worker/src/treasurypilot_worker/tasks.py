import asyncio

import asyncpg

from treasurypilot_worker.celery_app import app
from treasurypilot_worker.config import get_settings


@app.task(name="treasurypilot.system.core_probe", queue="core")
def core_probe() -> dict[str, str]:
    """Infrastructure probe; business tasks are added by execution tickets."""

    return {"status": "ok", "queue": "core"}


async def _expire_invoice_approvals() -> int:
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("TP_DATABASE_URL is required for invoice expiry")
    database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(database_url)
    try:
        async with conn.transaction():
            await conn.execute(
                "UPDATE approvals SET status = 'Expired' "
                "WHERE status = 'Valid' AND expires_at <= now()"
            )
            rows = await conn.fetch(
                "WITH expired AS (SELECT r.id, r.status AS previous_status "
                "FROM payment_requests r WHERE r.status IN "
                "('Approved', 'Scheduled', 'AwaitingAuthority', 'NeedsReview') "
                "AND EXISTS (SELECT 1 FROM approvals a WHERE a.request_id = r.id "
                "AND a.revision = r.current_revision AND a.status = 'Expired') "
                "AND NOT EXISTS (SELECT 1 FROM approvals a WHERE a.request_id = r.id "
                "AND a.revision = r.current_revision AND a.status = 'Valid') "
                "FOR UPDATE), changed AS (UPDATE payment_requests r SET status = 'Expired', "
                "version = r.version + 1, updated_at = now() "
                "FROM expired e WHERE r.id = e.id RETURNING r.id, e.previous_status) "
                "INSERT INTO request_status_events "
                "(id, request_id, from_status, to_status, actor_type, actor_id, reason) "
                "SELECT gen_random_uuid(), id, previous_status, 'Expired', 'SYSTEM', NULL, "
                "'approval expired' FROM changed RETURNING request_id"
            )
            await conn.execute(
                "UPDATE approvals a SET status = 'Expired' FROM payment_requests r "
                "WHERE a.request_id = r.id AND a.revision = r.current_revision "
                "AND r.status = 'Expired' AND a.status = 'Valid'"
            )
            return len(rows)
    finally:
        await conn.close()


@app.task(name="treasurypilot.invoices.expire_approvals", queue="core")
def expire_invoice_approvals() -> dict[str, int]:
    """Expire approval signatures and their still-payable requests atomically."""
    return {"requests_expired": asyncio.run(_expire_invoice_approvals())}


@app.task(name="treasurypilot.system.ai_probe", queue="ai")
def ai_probe() -> dict[str, str]:
    """AI queue probe. It performs no LLM call and accesses no signing material."""

    return {"status": "ok", "queue": "ai"}
