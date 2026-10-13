from datetime import timedelta

from celery import Celery
from kombu import Exchange, Queue

from treasurypilot_worker.config import get_settings
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
            "publish-domain-events": {
                "task": "treasurypilot.notifications.publish-domain-events",
                "schedule": timedelta(seconds=1),
                "options": {"queue": "core"},
            }
        },
    )
    return app


app = create_celery_app()
