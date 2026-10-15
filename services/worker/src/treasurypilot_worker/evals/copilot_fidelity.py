"""Copilot numeric-fidelity eval (AGT-016, F-092): `make eval-copilot`.

Runs the production Copilot turn (`ask_copilot` through `AiAdapter`, with the numeric post-check)
over the cases in `evals/copilot`. The only tool serves each case's precomputed deterministic
output, so the engine numbers are fixed. A case passes when the answer contains every expected
number exactly, no number outside the tool output, a citation, and the refusal flag matches
`must_refuse`. Failing cases are listed in the report.

Modes share one code path above the provider:

* recorded: replays responses stored in `evals/copilot/recorded/<prompt version>/`. Offline and
  deterministic. A recording is refused when its prompt version or case file hash changed.
* live: calls the configured provider (needs ANTHROPIC_API_KEY); with `--record` it rewrites the
  recordings from that run.
* scripted: no model. Builds reference answers that quote the expected numbers, to keep the
  committed baseline recordings reproducible (`--record` writes them). Not a measurement.

`auto` (the default) is live when the key is set, otherwise recorded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from treasurypilot_worker.agent import (
    AiAdapter,
    AiError,
    InMemoryAiCallLog,
    InMemoryBudgetLedger,
    Provider,
    ProviderRequest,
    ProviderResponse,
    StopReason,
    Tool,
    ToolCall,
    Usage,
    load_ai_config,
)
from treasurypilot_worker.agent.config import AiTask
from treasurypilot_worker.agent.copilot import _numbers, ask_copilot
from treasurypilot_worker.agent.errors import AiUnavailable
from treasurypilot_worker.agent.prompts.copilot import COPILOT_TEMPLATE

EVAL_ORG = "eval-copilot"
TOOL_NAME = "deterministic_tool"
REPO_ROOT = Path(__file__).resolve().parents[5]


class RecordingError(RuntimeError):
    """The recorded responses are missing or stale; re-record with a live run."""


@dataclass(frozen=True)
class Case:
    case_id: str
    data: dict[str, Any]
    sha256: str

    @property
    def question(self) -> str:
        return str(self.data["question"])

    @property
    def expected(self) -> dict[str, str]:
        return dict(self.data["expected_numbers"])

    @property
    def must_refuse(self) -> bool:
        return bool(self.data["must_refuse"])

    @property
    def tool_outputs(self) -> dict[str, Any]:
        return dict(self.data["context"]["tool_outputs"])


def load_cases(dataset: Path) -> list[Case]:
    cases = []
    for path in sorted(dataset.glob("cp-*.yaml")):
        raw = path.read_bytes()
        cases.append(Case(path.stem, yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()))
    return cases


class _NoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def case_tool(case: Case) -> Tool[_NoInput]:
    outputs = case.tool_outputs
    return Tool(
        TOOL_NAME,
        "Returns the engine's precomputed figures for this question, keyed by evidence source. "
        "Takes no arguments.",
        _NoInput,
        lambda _args: outputs,
    )


def _step_to_json(response: ProviderResponse) -> dict[str, Any]:
    return {
        "stop_reason": response.stop_reason.value,
        "text": response.text,
        "tool_calls": [{"id": c.id, "name": c.name, "input": c.input} for c in response.tool_calls],
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }


def _step_from_json(step: dict[str, Any]) -> ProviderResponse:
    return ProviderResponse(
        stop_reason=StopReason(step["stop_reason"]),
        text=step["text"],
        tool_calls=tuple(ToolCall(c["id"], c["name"], c["input"]) for c in step["tool_calls"]),
        usage=Usage(step["input_tokens"], step["output_tokens"]),
    )


class RecordedProvider:
    """Replays the stored responses of the case currently being run, in order."""

    name = "recorded"

    def __init__(self, directory: Path, cases: Sequence[Case]) -> None:
        self.current = ""
        self._queues: dict[str, list[dict[str, Any]]] = {}
        self.recorded_at: list[str] = []
        self.models: set[str] = set()
        for case in cases:
            path = directory / f"{case.case_id}.json"
            if not path.is_file():
                raise RecordingError(f"no recording {path}; run `make eval-copilot-record`")
            data = json.loads(path.read_text())
            if data["prompt_version"] != COPILOT_TEMPLATE.version:
                raise RecordingError(
                    f"{path.name} was recorded with {data['prompt_version']}, "
                    f"prompt is {COPILOT_TEMPLATE.version}; re-record"
                )
            if data["case_sha256"] != case.sha256:
                raise RecordingError(f"{path.name} was recorded for a different case; re-record")
            self._queues[case.case_id] = list(data["responses"])
            self.recorded_at.append(data["recorded_at"])
            self.models.add(data["model"])

    def complete(self, request: ProviderRequest, *, timeout_s: float) -> ProviderResponse:
        queue = self._queues.get(self.current)
        if not queue:
            raise AiUnavailable("recorded responses exhausted", retryable=False)
        return _step_from_json(queue.pop(0))


class RecordingProvider:
    """Wraps a provider and keeps each case's responses for later replay."""

    def __init__(self, inner: Provider) -> None:
        self.name = inner.name
        self._inner = inner
        self._current = ""
        self.responses: dict[str, list[dict[str, Any]]] = {}

    @property
    def current(self) -> str:
        return self._current

    @current.setter
    def current(self, case_id: str) -> None:
        self._current = case_id
        if hasattr(self._inner, "current"):
            self._inner.current = case_id

    def complete(self, request: ProviderRequest, *, timeout_s: float) -> ProviderResponse:
        response = self._inner.complete(request, timeout_s=timeout_s)
        self.responses.setdefault(self.current, []).append(_step_to_json(response))
        return response

    def write(self, directory: Path, cases: Sequence[Case], *, model: str, now: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for case in cases:
            if case.case_id not in self.responses:
                continue
            record = {
                "case_id": case.case_id,
                "prompt_version": COPILOT_TEMPLATE.version,
                "model": model,
                "case_sha256": case.sha256,
                "recorded_at": now,
                "responses": self.responses[case.case_id],
            }
            (directory / f"{case.case_id}.json").write_text(json.dumps(record, indent=2) + "\n")


class ScriptedProvider:
    """Reference answers that quote the expected numbers: call the tool, then answer."""

    name = "scripted"

    def __init__(self) -> None:
        self.current = ""
        self.cases: dict[str, Case] = {}
        self._turn: dict[str, int] = {}

    def complete(self, request: ProviderRequest, *, timeout_s: float) -> ProviderResponse:
        turn = self._turn.get(self.current, 0)
        self._turn[self.current] = turn + 1
        if turn == 0:
            return ProviderResponse(
                stop_reason=StopReason.TOOL_USE,
                tool_calls=(ToolCall("t1", TOOL_NAME, {}),),
                usage=Usage(10, 10),
            )
        case = self.cases[self.current]
        figures = "; ".join(f"{name} is {value}" for name, value in case.expected.items())
        answer = {
            "answer": f"From the cited figures (base units): {figures}.",
            "citations": [{"tool_call_id": "t1", "path": "$"}],
        }
        return ProviderResponse(
            stop_reason=StopReason.END_TURN, text=json.dumps(answer), usage=Usage(10, 10)
        )


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    passed: bool
    problems: tuple[str, ...] = field(default=())


def score_case(case: Case, answer: str, *, refused: bool, cited: bool) -> CaseScore:
    problems = []
    found = _numbers(answer)
    if missing := {n: v for n, v in case.expected.items() if v not in found}:
        problems.append("missing " + ", ".join(f"{n}={v}" for n, v in sorted(missing.items())))
    allowed = _numbers(json.dumps(case.tool_outputs))
    if stray := sorted(found - allowed):
        problems.append(f"numbers not in the engine output: {stray}")
    if not cited:
        problems.append("no citation")
    if refused != case.must_refuse:
        problems.append(f"refused={refused}, expected {case.must_refuse}")
    return CaseScore(case.case_id, not problems, tuple(problems))


def run_cases(adapter: AiAdapter, cases: Sequence[Case], provider: Any) -> list[CaseScore]:
    scores = []
    for case in cases:
        provider.current = case.case_id
        try:
            reply = ask_copilot(
                adapter, org_id=EVAL_ORG, question=case.question, tools=[case_tool(case)]
            )
        except AiError as error:
            scores.append(CaseScore(case.case_id, False, (f"{type(error).__name__}: {error}",)))
        else:
            scores.append(
                score_case(case, reply.answer, refused=reply.refused, cited=bool(reply.citations))
            )
    return scores


def render_report(
    scores: Sequence[CaseScore], *, mode: str, model: str, notes: Sequence[str]
) -> str:
    passed = sum(s.passed for s in scores)
    lines = [
        "# Copilot numeric-fidelity eval (AGT-016)",
        "",
        "Generated by `make eval-copilot`; do not edit by hand.",
        "",
        f"- Prompt: `{COPILOT_TEMPLATE.version}`",
        f"- Model: `{model}`",
        f"- Mode: {mode}",
        f"- Cases: {len(scores)} (`evals/copilot`), numerically faithful: {passed}/{len(scores)}",
        *[f"- {note}" for note in notes],
        "",
        "A case passes when the answer holds every expected number exactly (integer base "
        "units), no number outside the engine output, a citation, and a refusal exactly when "
        "`must_refuse`. Cases are AI-authored and pending second-person review.",
        "",
        "## Cases",
        "",
        "| Case | Result |",
        "| --- | --- |",
        *[f"| {s.case_id} | {'pass' if s.passed else 'FAIL'} |" for s in scores],
        "",
        "## Failures",
        "",
    ]
    failed = [s for s in scores if not s.passed]
    if not failed:
        lines.append("None.")
    lines += [f"- {s.case_id}: " + "; ".join(s.problems) for s in failed]
    return "\n".join(lines) + "\n"


def _live_provider() -> Provider:
    import anthropic

    from treasurypilot_worker.agent.anthropic_provider import AnthropicProvider

    return AnthropicProvider(anthropic.Anthropic(), name="anthropic")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--mode", choices=("auto", "recorded", "live", "scripted"), default="auto")
    parser.add_argument("--record", action="store_true", help="live/scripted: store the responses")
    parser.add_argument("--strict", action="store_true", help="exit 1 when any case fails")
    parser.add_argument("--dataset", type=Path, default=REPO_ROOT / "evals" / "copilot")
    parser.add_argument("--recordings", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "ai.yaml")
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "docs" / "evidence" / "copilot-fidelity.md"
    )
    args = parser.parse_args(argv)

    mode = args.mode
    if mode == "auto":
        mode = "live" if os.environ.get("ANTHROPIC_API_KEY") else "recorded"
    recordings = args.recordings or args.dataset / "recorded" / COPILOT_TEMPLATE.version
    cases = load_cases(args.dataset)
    config = load_ai_config(args.config)
    model = config.tasks[AiTask.COPILOT].model
    notes: list[str] = []

    provider: Any
    recorder: RecordingProvider | None = None
    if mode == "live":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("live mode needs ANTHROPIC_API_KEY", file=sys.stderr)
            return 2
        recorder = provider = RecordingProvider(_live_provider())
    elif mode == "scripted":
        scripted = ScriptedProvider()
        scripted.cases = {c.case_id: c for c in cases}
        model = "scripted-reference"
        recorder = provider = RecordingProvider(scripted)
        notes.append("Scripted reference answers, not model output: no fidelity is measured.")
    else:
        try:
            replay = RecordedProvider(recordings, cases)
        except RecordingError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        provider = replay
        model = ", ".join(sorted(replay.models))
        notes.append(f"Recorded {min(replay.recorded_at)} .. {max(replay.recorded_at)}")
        if model == "scripted-reference":
            notes.append("Recordings are scripted reference answers, not model output.")

    adapter = AiAdapter(
        provider=provider,
        config=config,
        ledger=InMemoryBudgetLedger(),
        call_log=InMemoryAiCallLog(),
    )
    scores = run_cases(adapter, cases, provider)
    if recorder is not None and args.record:
        from datetime import UTC, datetime

        stamp = datetime.now(UTC).strftime("%Y-%m-%d")
        recorder.write(recordings, cases, model=model, now=stamp)
        notes.append(f"Recorded {stamp} to `{recordings.relative_to(REPO_ROOT)}`")
    report = render_report(scores, mode=mode, model=model, notes=notes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report)
    print(report)
    print(f"report written to {args.out}")
    return 1 if args.strict and not all(s.passed for s in scores) else 0


if __name__ == "__main__":
    raise SystemExit(main())
