"""The worker's Prometheus endpoint exposes the M17 series and live queue depth."""

import urllib.request

from treasurypilot_worker.celery_app import app
from treasurypilot_worker.metrics import LLM_COST, LLM_LATENCY, start_metrics_server

SERIES = (
    "tp_queue_depth",
    "tp_rpc_errors_total",
    "tp_llm_latency_seconds",
    "tp_llm_cost_usd_total",
    "tp_tx_status_total",
)


def test_metrics_endpoint_exposes_the_listed_series() -> None:
    LLM_LATENCY.labels(task="test_task").observe(1.5)
    LLM_COST.labels(task="test_task").inc(0.25)
    original = (app.conf.broker_url, app.conf.result_backend)
    app.conf.update(broker_url="memory://", result_backend="cache+memory://")
    server = start_metrics_server(app, port=0)
    try:
        app.send_task("test.queued", queue="ai")
        app.send_task("test.queued", queue="ai")
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/metrics") as response:
            body = response.read().decode()
    finally:
        server.shutdown()
        server.server_close()
        app.conf.update(broker_url=original[0], result_backend=original[1])

    lines = body.splitlines()
    for name in SERIES:
        assert f"# TYPE {name} " in body, name
    assert 'tp_queue_depth{queue="ai"} 2.0' in lines
    assert 'tp_queue_depth{queue="core"} 0.0' in lines
    assert 'tp_llm_cost_usd_total{task="test_task"} 0.25' in lines
