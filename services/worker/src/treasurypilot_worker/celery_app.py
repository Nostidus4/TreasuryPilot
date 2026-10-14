from datetime import timedelta

from celery import Celery, signals
from celery.schedules import crontab
from kombu import Exchange, Queue
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.httpx import HTTPX2ClientInstrumentor

from treasurypilot_core.error_tracking import configure_error_tracking
from treasurypilot_core.observability import configure_logging
from treasurypilot_core.tracing import configure_tracing
from treasurypilot_worker.config import get_settings
from treasurypilot_worker.metrics import start_metrics_server
from treasurypilot_worker.runtime import SafeTask


def create_celery_app() -> Celery:
    settings = get_settings()
    core_exchange = Exchange("core", type="direct")
    ai_exchange = Exchange("ai", type="direct")
    app = Celery(
        "treasurypilot",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=["treasurypilot_worker.tasks"],
        task_cls=SafeTask,
    )
    app.conf.update(
        task_acks_late=True,
        task_default_queue="core",
        task_default_exchange="core",
        task_default_routing_key="core",
        task_queues=(
            Queue("core", exchange=core_exchange, routing_key="core"),
            Queue("ai", exchange=ai_exchange, routing_key="ai"),
        ),
        task_reject_on_worker_lost=True,
        task_ignore_result=True,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        broker_connection_retry_on_startup=True,
        broker_transport_options={"visibility_timeout": settings.visibility_timeout_seconds},
        result_backend_transport_options={
            "visibility_timeout": settings.visibility_timeout_seconds
        },
        worker_prefetch_multiplier=1,
        timezone="UTC",
        enable_utc=True,
        beat_schedule={
            "refresh-safe-config-snapshots": {
                "task": "treasurypilot.treasury.refresh_safe_config_snapshots",
                "schedule": crontab(minute="*/10"),
                "options": {"queue": "core"},
            },
            "expire-invoice-approvals": {
                "task": "treasurypilot.invoices.expire_approvals",
                "schedule": timedelta(minutes=5),
                "options": {"queue": "core"},
            },
            "publish-domain-events": {
                "task": "treasurypilot.notifications.publish-domain-events",
                "schedule": timedelta(seconds=1),
                # A run nobody picked up within 2 s is superseded by the next one; without
                # this, a busy or stopped worker lets thousands pile up in Redis.
                "options": {"queue": "core", "expires": 2},
            },
            "deliver-telegram": {
                "task": "treasurypilot.notifications.deliver-telegram",
                "schedule": timedelta(seconds=1),
                "options": {"queue": "core", "expires": 2},
            },
        },
    )
    return app


app = create_celery_app()


# setup_logging fires for both `celery worker` and `celery beat`, and stops Celery from
# installing its own root handler. It runs before the pool forks; the batch span exporter
# restarts its thread in each child.
@signals.setup_logging.connect
def _configure_observability(**_: object) -> None:
    settings = get_settings()
    configure_logging("worker", settings.log_level, settings.log_format)
    configure_tracing("worker")
    # Celery spans carry the trace through task headers; httpx spans carry it to the signer.
    for instrumentor in (CeleryInstrumentor(), HTTPX2ClientInstrumentor()):
        if not instrumentor.is_instrumented_by_opentelemetry:
            instrumentor.instrument()
    configure_error_tracking("worker")


# worker_init runs once in the parent process, before the prefork pool starts.
@signals.worker_init.connect
def _serve_metrics(**_: object) -> None:
    port = get_settings().metrics_port
    if port is not None:
        start_metrics_server(app, port)
