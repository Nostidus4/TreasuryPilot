from uuid import UUID

import pytest
from celery import Task

from treasurypilot_worker.celery_app import app
from treasurypilot_worker.runtime import (
    CORRELATION_ID_HEADER,
    MAX_TASK_RETRIES,
    SafeTask,
    current_correlation_id,
    make_idempotency_key,
)
from treasurypilot_worker.tasks import ai_probe, core_probe


def test_worker_uses_safe_delivery_settings() -> None:
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    queues = {queue.name: queue for queue in app.conf.task_queues}
    assert set(queues) == {"ai", "core"}
    assert queues["core"].exchange.name == "core"
    assert queues["core"].routing_key == "core"
    assert queues["ai"].exchange.name == "ai"
    assert queues["ai"].routing_key == "ai"
    assert app.conf.task_default_queue == "core"
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.broker_transport_options["visibility_timeout"] == 3600
    assert app.conf.visibility_timeout == 3600


def test_registered_tasks_inherit_safe_base() -> None:
    assert isinstance(core_probe, SafeTask)
    assert core_probe.acks_late is True
    assert core_probe.reject_on_worker_lost is True
    assert core_probe.retry_backoff is True
    assert core_probe.retry_kwargs == {"max_retries": MAX_TASK_RETRIES}
    assert core_probe.queue == "core"
    assert ai_probe.queue == "ai"


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
