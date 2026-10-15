"""Providers for the benchmark: recorded replay, live recording, and an offline stand-in.

Recorded mode replays the model turns of an earlier live run, per scenario and repetition, so CI
and reviewers reproduce a report exactly. A recording is refused when the prompt version or the
scenario inputs have changed since it was made.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from treasurypilot_worker.agent.errors import AiError, AiTimeout, AiUnavailable
from treasurypilot_worker.agent.prompts.plan import PLAN_TEMPLATE
from treasurypilot_worker.agent.types import (
    Provider,
    ProviderRequest,
    ProviderResponse,
    StopReason,
    ToolCall,
    ToolResult,
    Usage,
)
from treasurypilot_worker.planner_bench.scenarios import Scenario, proposal_needed

PROMPT_VERSION = PLAN_TEMPLATE.version


class RecordingError(RuntimeError):
    """Recordings are missing or stale; re-record with a live run."""


class RunScopedProvider(Provider, Protocol):
    """A provider told which (scenario, repetition) the next adapter run belongs to."""

    def begin(self, scenario_id: str, repetition: int) -> None: ...

    def recorded_latency_ms(self, scenario_id: str, repetition: int) -> int | None: ...

    def finish(self, latency_ms: int) -> None:
        """The run ended after `latency_ms` (a recorder keeps it)."""
        ...


def _usage(raw: dict[str, Any]) -> Usage:
    return Usage(
        raw["input_tokens"],
        raw["output_tokens"],
        raw.get("cache_write_tokens", 0),
        raw.get("cache_read_tokens", 0),
    )


def _dump(response: ProviderResponse) -> dict[str, Any]:
    return {
        "stop_reason": response.stop_reason.value,
        "text": response.text,
        "tool_calls": [{"id": c.id, "name": c.name, "input": c.input} for c in response.tool_calls],
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_write_tokens": response.usage.cache_write_tokens,
        "cache_read_tokens": response.usage.cache_read_tokens,
    }


def _load(step: dict[str, Any]) -> ProviderResponse:
    return ProviderResponse(
        stop_reason=StopReason(step["stop_reason"]),
        text=step["text"],
        tool_calls=tuple(ToolCall(c["id"], c["name"], c["input"]) for c in step["tool_calls"]),
        usage=_usage(step),
    )


class RecordedProvider:
    """Replays stored turns for each (scenario, repetition), in order."""

    name = "recorded"

    def __init__(self, directory: Path, scenarios: Sequence[Scenario], repetitions: int) -> None:
        self._runs: dict[tuple[str, int], dict[str, Any]] = {}
        self._queue: list[dict[str, Any]] = []
        self.recorded_at: list[str] = []
        self.models: set[str] = set()
        for scenario in scenarios:
            if not proposal_needed(scenario):
                continue  # the trigger rule never calls the model for it
            path = directory / f"{scenario.id}.json"
            if not path.is_file():
                raise RecordingError(f"no recording {path}; run `make bench-record`")
            data = json.loads(path.read_text())
            if data["prompt_version"] != PROMPT_VERSION:
                raise RecordingError(
                    f"{path.name} was recorded with {data['prompt_version']}, "
                    f"prompt is {PROMPT_VERSION}; re-record"
                )
            if data["inputs_sha256"] != scenario.inputs_sha256:
                raise RecordingError(f"{path.name} was recorded for different inputs; re-record")
            by_rep = {run["repetition"]: run for run in data["runs"]}
            for rep in range(repetitions):
                if rep not in by_rep:
                    raise RecordingError(f"{path.name} has no repetition {rep}; re-record")
                self._runs[(scenario.id, rep)] = by_rep[rep]
            self.recorded_at.append(data["recorded_at"])
            self.models.add(data["model"])

    def begin(self, scenario_id: str, repetition: int) -> None:
        run = self._runs.get((scenario_id, repetition))
        if run is None:
            raise RecordingError(f"no recorded run for {scenario_id} repetition {repetition}")
        self._queue = list(run["steps"])

    def recorded_latency_ms(self, scenario_id: str, repetition: int) -> int | None:
        return int(self._runs[(scenario_id, repetition)]["latency_ms"])

    def finish(self, latency_ms: int) -> None:
        pass

    def complete(self, request: ProviderRequest, *, timeout_s: float) -> ProviderResponse:
        if not self._queue:
            raise AiUnavailable("recorded responses exhausted", retryable=False)
        step = self._queue.pop(0)
        if "error" in step:
            if step["error"] == "AiTimeout":
                raise AiTimeout(step["message"])
            raise AiUnavailable(step["message"], retryable=False)
        return _load(step)


class RecordingProvider:
    """Wraps a live provider and keeps every turn for later replay."""

    def __init__(self, inner: Provider) -> None:
        self.name = inner.name
        self._inner = inner
        self._current: tuple[str, int] | None = None
        self._runs: dict[str, dict[int, dict[str, Any]]] = {}

    def begin(self, scenario_id: str, repetition: int) -> None:
        self._current = (scenario_id, repetition)
        begin = getattr(self._inner, "begin", None)  # a scoped inner provider (tests)
        if begin is not None:
            begin(scenario_id, repetition)
        self._runs.setdefault(scenario_id, {})[repetition] = {
            "repetition": repetition,
            "latency_ms": 0,
            "steps": [],
        }

    def recorded_latency_ms(self, scenario_id: str, repetition: int) -> int | None:
        return None

    def finish(self, latency_ms: int) -> None:
        assert self._current is not None
        scenario_id, repetition = self._current
        self._runs[scenario_id][repetition]["latency_ms"] = latency_ms

    def complete(self, request: ProviderRequest, *, timeout_s: float) -> ProviderResponse:
        assert self._current is not None
        scenario_id, repetition = self._current
        steps = self._runs[scenario_id][repetition]["steps"]
        try:
            response = self._inner.complete(request, timeout_s=timeout_s)
        except AiError as error:
            steps.append({"error": type(error).__name__, "message": str(error)})
            raise
        steps.append(_dump(response))
        return response

    def write(
        self, directory: Path, scenarios: Sequence[Scenario], *, model: str, recorded_at: str
    ) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for scenario in scenarios:
            runs = self._runs.get(scenario.id)
            if not runs:
                continue
            record = {
                "scenario_id": scenario.id,
                "prompt_version": PROMPT_VERSION,
                "model": model,
                "inputs_sha256": scenario.inputs_sha256,
                "recorded_at": recorded_at,
                "runs": [runs[rep] for rep in sorted(runs)],
            }
            (directory / f"{scenario.id}.json").write_text(json.dumps(record, indent=2) + "\n")


class EdfStandInProvider:
    """Offline stand-in, NOT a model: reads the tools, then proposes plain EDF order.

    It exercises the whole B2 path (tool turns, schema, reference check, `select_plan`) with no
    network. Because it only reproduces B1's order, B2 equals B1 under it.
    """

    name = "edf-stand-in"

    def begin(self, scenario_id: str, repetition: int) -> None:
        self._scenario_id = scenario_id

    def recorded_latency_ms(self, scenario_id: str, repetition: int) -> int | None:
        return None

    def finish(self, latency_ms: int) -> None:
        pass

    def complete(self, request: ProviderRequest, *, timeout_s: float) -> ProviderResponse:
        results = [b for m in request.messages for b in m.content if isinstance(b, ToolResult)]
        usage = Usage(0, 0)
        if not results:
            calls = tuple(
                ToolCall(f"t-{name}", name, {"treasury_id": self._scenario_id})
                for name in ("get_snapshot", "list_requests")
            )
            return ProviderResponse(StopReason.TOOL_USE, tool_calls=calls, usage=usage)
        by_call = {r.tool_call_id: json.loads(r.content) for r in results}
        requests = by_call["t-list_requests"]["requests"]
        order = [
            r["id"]
            for r in sorted(
                requests,
                key=lambda r: (r["terms"]["net_due_day"], r["approved_seq"], r["id"]),
            )
        ]
        proposal = {
            "request_order": order,
            "rationale": [
                {
                    "claim": "Earliest due day first.",
                    "evidence_ids": [by_call["t-get_snapshot"]["snapshot_id"]],
                }
            ],
        }
        return ProviderResponse(StopReason.END_TURN, text=json.dumps(proposal), usage=usage)
