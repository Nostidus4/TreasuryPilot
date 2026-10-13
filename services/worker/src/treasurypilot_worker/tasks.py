import asyncio
import os

from treasurypilot_worker.celery_app import app
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.notify.publisher import publish_from_pool


@app.task(name="treasurypilot.system.core_probe", queue="core")
def core_probe() -> dict[str, str]:
    """Infrastructure probe; business tasks are added by execution tickets."""

    return {"status": "ok", "queue": "core"}


@app.task(name="treasurypilot.system.ai_probe", queue="ai")
def ai_probe() -> dict[str, str]:
    """AI queue probe. It performs no LLM call and accesses no signing material."""

    return {"status": "ok", "queue": "ai"}


@app.task(name="treasurypilot.notifications.publish-domain-events", queue="core")
def publish_domain_events() -> dict[str, int]:
    """Materialize pending in-app notifications from the PostgreSQL outbox."""

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for domain-event publishing")

    async def publish() -> int:
        pool = await create_worker_pool(database_url, min_size=1, max_size=1)
        try:
            return await publish_from_pool(pool)
        finally:
            await pool.close()

    return {"published": asyncio.run(publish())}
