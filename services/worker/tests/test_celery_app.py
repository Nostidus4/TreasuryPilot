from datetime import timedelta
from uuid import UUID

import pytest
from celery import Task
from celery.contrib.testing.worker import start_worker

from treasurypilot_worker.celery_app import app
from treasurypilot_worker.runtime import (
    CORRELATION_ID_HEADER,
    MAX_TASK_RETRIES,
    SafeTask,
    current_correlation_id,
    make_idempotency_key,
)
from treasurypilot_worker.tasks import (
    ai_probe,
    core_probe,
    generate_recurring_drafts_task,
    publish_daily_audit_roots_task,
    publish_domain_events,
)


def test_worker_uses_safe_delivery_settings() -> None:
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    queues = {queue.name: queue for queue in app.conf.task_queues}
    assert set(queues) == {"ai", "core", "webhooks"}
    assert queues["core"].exchange.name == "core"
    assert queues["core"].routing_key == "core"
    assert queues["ai"].exchange.name == "ai"
    assert queues["ai"].routing_key == "ai"
    assert queues["webhooks"].routing_key == "webhooks"
    assert app.conf.task_default_queue == "core"
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.broker_transport_options["visibility_timeout"] == 3600


def test_safe_config_refresh_is_scheduled_every_ten_minutes() -> None:
    entry = app.conf.beat_schedule["refresh-safe-config-snapshots"]

    assert entry["task"] == "treasurypilot.treasury.refresh_safe_config_snapshots"
    assert entry["schedule"].minute == {0, 10, 20, 30, 40, 50}
    assert entry["options"]["queue"] == "core"


def test_registered_tasks_inherit_safe_base() -> None:
    assert isinstance(core_probe, SafeTask)
    assert core_probe.acks_late is True
    assert core_probe.reject_on_worker_lost is True
    assert core_probe.retry_backoff is True
    assert core_probe.retry_kwargs == {"max_retries": MAX_TASK_RETRIES}
    assert core_probe.queue == "core"
    assert ai_probe.queue == "ai"
    assert isinstance(publish_domain_events, SafeTask)
    assert publish_domain_events.queue == "core"
    assert isinstance(generate_recurring_drafts_task, SafeTask)
    assert generate_recurring_drafts_task.queue == "core"
    assert isinstance(publish_daily_audit_roots_task, SafeTask)
    assert publish_daily_audit_roots_task.queue == "core"


def test_domain_event_publisher_is_scheduled_every_second_on_core_queue() -> None:
    entry = app.conf.beat_schedule["publish-domain-events"]

    assert entry["task"] == "treasurypilot.notifications.publish-domain-events"
    assert entry["schedule"] == timedelta(seconds=1)
    assert entry["options"] == {"queue": "core", "expires": 2}


def test_execution_cycles_use_fifteen_minute_and_sixty_second_cadences() -> None:
    schedule = app.conf.beat_schedule["execution-scheduling-cycle"]
    safety = app.conf.beat_schedule["execution-safety-cycle"]
    activation = app.conf.beat_schedule["activate-due-payees"]

    assert schedule["task"] == "treasurypilot.execution.scheduling_cycle"
    assert schedule["schedule"] == timedelta(minutes=15)
    assert safety["task"] == "treasurypilot.execution.safety_cycle"
    assert safety["schedule"] == timedelta(seconds=60)
    assert activation["task"] == "treasurypilot.execution.activate_due_payees"
    assert activation["schedule"] == timedelta(seconds=1)


def test_recurring_draft_generation_is_scheduled_shortly_after_midnight_utc() -> None:
    entry = app.conf.beat_schedule["generate-recurring-payment-drafts"]

    assert entry["task"] == "treasurypilot.invoices.generate-recurring-drafts"
    assert entry["schedule"].minute == {5}
    assert entry["schedule"].hour == {0}
    assert entry["options"]["queue"] == "core"


def test_webhook_delivery_runs_on_its_own_queue_not_core() -> None:
    from treasurypilot_worker.tasks import deliver_webhooks

    entry = app.conf.beat_schedule["deliver-webhooks"]

    assert entry["options"] == {"queue": "webhooks", "expires": 2}
    assert deliver_webhooks.queue == "webhooks"


def test_telegram_delivery_runs_on_the_egress_worker_queue() -> None:
    from treasurypilot_worker.tasks import deliver_telegram

    entry = app.conf.beat_schedule["deliver-telegram"]

    assert entry["options"] == {"queue": "webhooks", "expires": 2}
    assert deliver_telegram.queue == "webhooks"


def test_daily_audit_root_publisher_is_scheduled_at_utc_0005() -> None:
    entry = app.conf.beat_schedule["publish-daily-audit-roots"]

    assert entry["task"] == "treasurypilot.audit.publish-daily-roots"
    assert entry["schedule"].hour == {0}
    assert entry["schedule"].minute == {5}
    assert entry["options"] == {"queue": "core"}


def test_idempotency_key_is_stable_and_namespaced() -> None:
    first = make_idempotency_key("execute-plan", "plan-1", 2)
    redelivery = make_idempotency_key("execute-plan", "plan-1", 2)

    assert first == redelivery
    assert first.startswith("execute-plan:")
    assert first != make_idempotency_key("execute-plan", "plan-1", 3)
    assert "plan-1" not in first


@pytest.mark.parametrize(
    ("namespace", "identifiers"),
    [("", ("plan-1",)), ("execute-plan", ()), ("execute-plan", (None,))],
)
def test_idempotency_key_rejects_incomplete_identity(
    namespace: str, identifiers: tuple[object, ...]
) -> None:
    with pytest.raises(ValueError):
        make_idempotency_key(namespace, *identifiers)


class _CaptureCorrelationTask(SafeTask):
    name = "test.capture-correlation"

    def run(self) -> str | None:
        return current_correlation_id()


class _PublishChildTask(SafeTask):
    name = "test.publish-child"

    def run(self) -> None:
        _CaptureCorrelationTask().apply_async()


def test_delivery_correlation_id_is_bound_only_for_task_lifetime() -> None:
    _CaptureCorrelationTask.bind(app)
    task = _CaptureCorrelationTask()
    task.push_request(headers={CORRELATION_ID_HEADER: "correlation-123"})
    try:
        assert task() == "correlation-123"
        assert current_correlation_id() is None
    finally:
        task.pop_request()


def test_publish_adds_a_correlation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_headers: dict[str, str] = {}

    def capture_apply_async(
        _task: Task,
        args: tuple[object, ...] | None = None,
        kwargs: dict[str, object] | None = None,
        **options: object,
    ) -> None:
        del args, kwargs
        headers = options["headers"]
        assert isinstance(headers, dict)
        captured_headers.update(headers)

    monkeypatch.setattr(Task, "apply_async", capture_apply_async)
    _CaptureCorrelationTask.bind(app)
    _CaptureCorrelationTask().apply_async()

    UUID(captured_headers[CORRELATION_ID_HEADER])


def test_child_publication_propagates_delivery_correlation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_headers: dict[str, str] = {}

    def capture_apply_async(
        _task: Task,
        args: tuple[object, ...] | None = None,
        kwargs: dict[str, object] | None = None,
        **options: object,
    ) -> None:
        del args, kwargs
        headers = options["headers"]
        assert isinstance(headers, dict)
        captured_headers.update(headers)

    monkeypatch.setattr(Task, "apply_async", capture_apply_async)
    _CaptureCorrelationTask.bind(app)
    _PublishChildTask.bind(app)
    publisher = _PublishChildTask()
    publisher.push_request(headers={CORRELATION_ID_HEADER: "correlation-parent"})
    try:
        publisher()
    finally:
        publisher.pop_request()

    assert captured_headers[CORRELATION_ID_HEADER] == "correlation-parent"


def test_real_delivery_preserves_parent_correlation_id_header() -> None:
    """End-to-end regression test for the ``correlation_id`` header collision.

    ``push_request``/``apply_async`` monkeypatches in the tests above never
    exercise Celery's real message pipeline, so they could not catch a header
    name that collides with one of Celery's own reserved message properties
    (Celery sets ``correlation_id`` on every delivery to the task id). This
    test publishes a task through a real ``memory://`` broker and a real
    worker (``celery.contrib.testing.worker.start_worker``) and asserts that
    the worker-side task actually receives and binds the correlation id that
    was set at publish time. Before the header was renamed to
    ``x_correlation_id`` this failed: the custom value was silently dropped
    on delivery and the task observed a freshly minted uuid instead.
    """

    original_broker_url = app.conf.broker_url
    original_result_backend = app.conf.result_backend
    app.conf.update(
        broker_url="memory://",
        result_backend="cache+memory://",
        task_always_eager=False,
    )

    @app.task(
        base=SafeTask,
        name="test.e2e-capture-correlation",
        bind=True,
        ignore_result=False,
    )
    def capture_correlation(self: SafeTask) -> str | None:
        return current_correlation_id()

    try:
        with start_worker(app, perform_ping_check=False):
            result = capture_correlation.apply_async(headers={CORRELATION_ID_HEADER: "parent-123"})
            assert result.get(timeout=10) == "parent-123"
    finally:
        app.tasks.pop(capture_correlation.name, None)
        app.conf.update(
            broker_url=original_broker_url,
            result_backend=original_result_backend,
        )


def test_notification_email_runs_on_the_egress_queue_not_core() -> None:
    from treasurypilot_worker.tasks import send_daily_notification_digests, send_notification_emails

    immediate = app.conf.beat_schedule["send-notification-emails"]
    daily = app.conf.beat_schedule["send-daily-notification-digests"]

    assert immediate["task"] == "treasurypilot.notifications.send-emails"
    assert immediate["schedule"] == timedelta(seconds=60)
    assert immediate["options"] == {"queue": "webhooks", "expires": 55}
    assert daily["task"] == "treasurypilot.notifications.send-daily-digests"
    assert daily["schedule"].hour == {8} and daily["schedule"].minute == {0}
    assert daily["options"]["queue"] == "webhooks"
    assert send_notification_emails.queue == "webhooks"
    assert send_daily_notification_digests.queue == "webhooks"


def test_transaction_tracker_is_scheduled_every_six_seconds_on_core_queue() -> None:
    entry = app.conf.beat_schedule["track-transactions"]

    assert entry["task"] == "treasurypilot.chain.track-transactions"
    assert entry["schedule"] == timedelta(seconds=6)
    assert entry["options"]["queue"] == "core"


def test_daily_snapshot_is_scheduled_at_utc_midnight() -> None:
    entry = app.conf.beat_schedule["snapshot-daily"]

    assert entry["task"] == "treasurypilot.chain.snapshot_daily"
    assert entry["schedule"].hour == {0}
    assert entry["schedule"].minute == {0}
    assert app.conf.timezone == "UTC"
    assert entry["options"]["queue"] == "core"


def test_dashboard_snapshots_are_scheduled_every_minute() -> None:
    entry = app.conf.beat_schedule["snapshot-dashboards"]

    assert entry["task"] == "treasurypilot.chain.snapshot_dashboards"
    assert entry["schedule"].total_seconds() == 60
    assert entry["options"]["queue"] == "core"


def test_event_indexer_is_scheduled_every_six_seconds_on_core_queue() -> None:
    entry = app.conf.beat_schedule["index-chain-events"]

    assert entry["task"] == "treasurypilot.chain.index-events"
    assert entry["schedule"] == timedelta(seconds=6)
    assert entry["options"]["queue"] == "core"


def test_resume_partial_task_enqueues_sequencing_only_when_resumed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import uuid
    from types import SimpleNamespace

    from treasurypilot_worker import tasks

    plan = uuid.uuid4()
    status = {"v": "Resumed"}

    async def fake(_action, _request, _actor):  # type: ignore[no-untyped-def]
        return SimpleNamespace(status=status["v"], plan_id=plan, treasury_id=uuid.uuid4())

    sent: list[str] = []
    monkeypatch.setattr(tasks, "_partial_action", fake)
    monkeypatch.setattr(
        tasks.sequence_plan_task, "apply_async", lambda args, queue: sent.append(args[0])
    )
    assert tasks.resume_partial_task(str(uuid.uuid4()))["status"] == "Resumed"
    status["v"] = "InFlight"
    tasks.resume_partial_task(str(uuid.uuid4()))
    assert sent == [str(plan)]
