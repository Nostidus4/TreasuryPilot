from treasurypilot_worker.celery_app import app


@app.task(name="treasurypilot.system.core_probe", queue="core")
def core_probe() -> dict[str, str]:
    """Infrastructure probe; business tasks are added by execution tickets."""

    return {"status": "ok", "queue": "core"}


@app.task(name="treasurypilot.system.ai_probe", queue="ai")
def ai_probe() -> dict[str, str]:
    """AI queue probe. It performs no LLM call and accesses no signing material."""

    return {"status": "ok", "queue": "ai"}
