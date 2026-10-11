from celery import Celery
from kombu import Queue

from treasurypilot_worker.config import get_settings


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery(
        "treasurypilot",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=["treasurypilot_worker.tasks"],
    )
    app.conf.update(
        task_acks_late=True,
        task_default_queue="core",
        task_queues=(Queue("core"), Queue("ai")),
        task_reject_on_worker_lost=True,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
    )
    return app


app = create_celery_app()
