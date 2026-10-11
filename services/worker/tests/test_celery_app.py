from treasurypilot_worker.celery_app import app


def test_worker_uses_safe_delivery_settings() -> None:
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert {queue.name for queue in app.conf.task_queues} == {"ai", "core"}
