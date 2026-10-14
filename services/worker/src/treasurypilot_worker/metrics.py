"""Prometheus series served by the worker on the internal network (OBS-003, M17 §6).

Labels are bounded enums only, never org, request or address values (M17-D5).
"""

import os
from collections.abc import Iterator
from wsgiref.simple_server import WSGIServer

import structlog
from celery import Celery
from kombu.exceptions import ChannelError
from prometheus_client import REGISTRY, CollectorRegistry, Counter, Histogram, start_http_server
from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.multiprocess import MultiProcessCollector

RPC_ERRORS = Counter("tp_rpc_errors", "Chain RPC calls that failed.", ["provider"])
LLM_LATENCY = Histogram(
    "tp_llm_latency_seconds",
    "Wall-clock time of an LLM task, failed or not, including retries and tool turns.",
    ["task"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120),
)
LLM_COST = Counter("tp_llm_cost_usd", "LLM spend in USD, including failed tasks.", ["task"])
TX_STATUS = Counter("tp_tx_status", "Transactions entering each status.", ["status"])


class QueueDepthCollector:
    """Read each Celery queue's backlog from the broker at scrape time."""

    def __init__(self, app: Celery) -> None:
        self._app = app

    def collect(self) -> Iterator[Metric]:
        depth = GaugeMetricFamily(
            "tp_queue_depth", "Messages waiting in each Celery queue.", labels=["queue"]
        )
        try:
            with self._app.connection_for_read() as connection:
                channel = connection.default_channel
                for queue in self._app.conf.task_queues:
                    try:
                        count = channel.queue_declare(queue.name, passive=True).message_count
                    except ChannelError:
                        count = 0  # not declared yet: nothing was ever published to it
                    depth.add_metric([queue.name], count)
        except Exception as error:  # noqa: BLE001
            # A broker outage must not fail the scrape of every other series.
            structlog.get_logger().warning("queue_depth_unavailable", error=type(error).__name__)
        yield depth


def start_metrics_server(app: Celery, port: int) -> WSGIServer:
    registry = CollectorRegistry()
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        # Prefork children write samples to this directory; the parent serves their sum.
        MultiProcessCollector(registry)
    else:
        registry.register(REGISTRY)
    registry.register(QueueDepthCollector(app))
    server, _thread = start_http_server(port, registry=registry)
    return server
