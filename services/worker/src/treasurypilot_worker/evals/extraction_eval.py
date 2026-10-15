"""Extraction accuracy eval (AGT-013, F-092): `make eval-extraction`.

Runs the production extraction call (`EXTRACT_TEMPLATE` through `AiAdapter`, validated as
`InvoiceExtraction`) over the labelled invoices in `evals/invoices` and scores it with
`extraction_scoring`. Ground truth is read only here, never placed in a prompt (M09-D14).

Two modes share one code path above the provider:

* recorded: replays model responses stored in `evals/invoices/recorded/<prompt version>/`.
  Offline and deterministic, so CI and reviewers reproduce the committed report exactly.
  A recording is refused when its prompt version or PDF hash no longer matches.
* live: calls the configured provider (needs ANTHROPIC_API_KEY) and, with `--record`,
  rewrites the recordings from that run.

`auto` (the default) is live when the key is set, otherwise recorded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from treasurypilot_worker.agent import (
    AiAdapter,
    AiError,
    AiTask,
    DocumentBlock,
    InMemoryAiCallLog,
    InMemoryBudgetLedger,
    Provider,
    ProviderRequest,
    ProviderResponse,
    SourceKind,
    StopReason,
    UntrustedSource,
    Usage,
    load_ai_config,
)
from treasurypilot_worker.agent.errors import AiUnavailable
from treasurypilot_worker.agent.prompts.extract import EXTRACT_TEMPLATE
from treasurypilot_worker.evals.extraction_scoring import (
    FIELDS,
    CaseScore,
    Summary,
    score_case,
    score_failure,
    summarize,
)
from treasurypilot_worker.invoices.extraction import InvoiceExtraction

EVAL_ORG = "eval-extraction"
DECIMALS = 6  # every invoice in the corpus is priced in a six-decimal asset
REPO_ROOT = Path(__file__).resolve().parents[5]


class RecordingError(RuntimeError):
    """The recorded responses are missing or stale; re-record with a live run."""


@dataclass(frozen=True)
class Case:
    invoice_id: str
    label: dict[str, Any]
    pdf: bytes

    @property
    def pdf_sha256(self) -> str:
        return hashlib.sha256(self.pdf).hexdigest()


def load_cases(dataset: Path) -> list[Case]:
    return [
        Case(
            path.stem,
            json.loads(path.read_text()),
            path.with_suffix(".pdf").read_bytes(),
        )
        for path in sorted(dataset.glob("inv-*.json"))
    ]


def _document_id(request: ProviderRequest) -> str:
    for message in request.messages:
        for block in message.content:
            if isinstance(block, DocumentBlock):
                return block.source.partition(":")[2]
    raise RecordingError("request carries no document")


class RecordedProvider:
    """Replays stored responses per invoice, in order (a schema retry is a second one)."""

    name = "recorded"

    def __init__(self, directory: Path, cases: Sequence[Case]) -> None:
        self._queues: dict[str, list[dict[str, Any]]] = {}
        self.recorded_at: list[str] = []
        self.models: set[str] = set()
        for case in cases:
            path = directory / f"{case.invoice_id}.json"
            if not path.is_file():
                raise RecordingError(f"no recording {path}; run `make eval-extraction-record`")
            data = json.loads(path.read_text())
            if data["prompt_version"] != EXTRACT_TEMPLATE.version:
                raise RecordingError(
                    f"{path.name} was recorded with {data['prompt_version']}, "
                    f"prompt is {EXTRACT_TEMPLATE.version}; re-record"
                )
            if data["pdf_sha256"] != case.pdf_sha256:
                raise RecordingError(f"{path.name} was recorded for a different PDF; re-record")
            self._queues[case.invoice_id] = list(data["responses"])
            self.recorded_at.append(data["recorded_at"])
            self.models.add(data["model"])

    def complete(self, request: ProviderRequest, *, timeout_s: float) -> ProviderResponse:
        queue = self._queues.get(_document_id(request))
        if not queue:
            raise AiUnavailable("recorded responses exhausted", retryable=False)
        step = queue.pop(0)
        usage = Usage(step["input_tokens"], step["output_tokens"])
        return ProviderResponse(stop_reason=StopReason.END_TURN, text=step["text"], usage=usage)


class RecordingProvider:
    """Wraps a live provider and keeps each invoice's responses for later replay."""

    def __init__(self, inner: Provider) -> None:
        self.name = inner.name
        self._inner = inner
        self.responses: dict[str, list[dict[str, Any]]] = {}

    def complete(self, request: ProviderRequest, *, timeout_s: float) -> ProviderResponse:
        response = self._inner.complete(request, timeout_s=timeout_s)
        self.responses.setdefault(_document_id(request), []).append(
            {
                "text": response.text or "",
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        )
        return response

    def write(self, directory: Path, cases: Sequence[Case], *, model: str, now: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for case in cases:
            if case.invoice_id not in self.responses:
                continue
            record = {
                "invoice_id": case.invoice_id,
                "prompt_version": EXTRACT_TEMPLATE.version,
                "model": model,
                "pdf_sha256": case.pdf_sha256,
                "recorded_at": now,
                "responses": self.responses[case.invoice_id],
            }
            (directory / f"{case.invoice_id}.json").write_text(json.dumps(record, indent=2) + "\n")


def run_cases(adapter: AiAdapter, cases: Sequence[Case]) -> list[CaseScore]:
    scores = []
    for case in cases:
        source = UntrustedSource(SourceKind.DOCUMENT, case.invoice_id)
        try:
            result = adapter.run(
                AiTask.EXTRACT,
                org_id=EVAL_ORG,
                prompt=EXTRACT_TEMPLATE.render(
                    invoice=DocumentBlock(str(source), "application/pdf", case.pdf)
                ),
                output=InvoiceExtraction,
            )
        except AiError as error:
            scores.append(score_failure(case.invoice_id, case.label, type(error).__name__))
        else:
            scores.append(score_case(case.invoice_id, case.label, result.output, decimals=DECIMALS))
    return scores


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_report(
    scores: Sequence[CaseScore], summary: Summary, *, mode: str, model: str, notes: Sequence[str]
) -> str:
    lines = [
        "# Extraction accuracy eval (AGT-013)",
        "",
        "Generated by `make eval-extraction`; do not edit by hand.",
        "",
        f"- Prompt: `{EXTRACT_TEMPLATE.version}`",
        f"- Model: `{model}`",
        f"- Mode: {mode}",
        f"- Invoices: {summary.cases} (`evals/invoices`), pipeline failures: {summary.failed}",
        *[f"- {note}" for note in notes],
        "",
        "Exact match after trimming; `amount` is compared in integer base units (6 decimals) "
        "as parsed by the draft prefill, so locale formats it cannot read count as misses. "
        "Labels are pending second-person review.",
        "",
        "## Field accuracy",
        "",
        "| Field | Correct | Accuracy |",
        "| --- | --- | --- |",
    ]
    for name in FIELDS:
        correct = sum(s.fields[name] for s in scores)
        lines.append(f"| {name} | {correct}/{summary.cases} | {_pct(summary.accuracy[name])} |")
    terms = summary.terms
    lines += [
        "",
        "## Payment terms",
        "",
        "Elements are (net_days, discount_bps, discount_days, late_fee.kind, "
        "late_fee.rate_bps, late_fee.period_days), micro-averaged over all invoices.",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Precision | {_pct(terms.precision)} |",
        f"| Recall | {_pct(terms.recall)} |",
        f"| F1 | {_pct(terms.f1)} |",
        f"| Invoices with terms exactly right | {_pct(summary.terms_exact)} |",
        "",
        "## Misses",
        "",
    ]
    missed = [s for s in scores if s.misses or not s.terms.exact]
    if not missed:
        lines.append("None.")
    for score in missed:
        detail = [f"{n}: expected `{e}`, got `{g}`" for n, (e, g) in score.misses.items()]
        if not score.terms.exact:
            detail.append(
                f"terms: {score.terms.false_negative} missing, "
                f"{score.terms.false_positive} spurious"
            )
        failure = f" (pipeline failure: {score.failed})" if score.failed else ""
        lines.append(f"- {score.invoice_id}{failure}: " + "; ".join(detail))
    return "\n".join(lines) + "\n"


def _live_provider(model_provider: str) -> Provider:
    import anthropic

    from treasurypilot_worker.agent.anthropic_provider import AnthropicProvider

    return AnthropicProvider(anthropic.Anthropic(), name=model_provider)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--mode", choices=("auto", "recorded", "live"), default="auto")
    parser.add_argument("--record", action="store_true", help="live: store the responses")
    parser.add_argument("--dataset", type=Path, default=REPO_ROOT / "evals" / "invoices")
    parser.add_argument("--recordings", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "ai.yaml")
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "docs" / "evidence" / "extraction-accuracy.md"
    )
    args = parser.parse_args(argv)

    mode = args.mode
    if mode == "auto":
        mode = "live" if os.environ.get("ANTHROPIC_API_KEY") else "recorded"
    recordings = args.recordings or args.dataset / "recorded" / EXTRACT_TEMPLATE.version
    cases = load_cases(args.dataset)
    config = load_ai_config(args.config)
    model = config.tasks[AiTask.EXTRACT].model
    notes: list[str] = []

    provider: Provider
    recorder: RecordingProvider | None = None
    if mode == "live":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("live mode needs ANTHROPIC_API_KEY", file=sys.stderr)
            return 2
        live = _live_provider("anthropic")
        recorder = provider = RecordingProvider(live)
    else:
        try:
            replay = RecordedProvider(recordings, cases)
        except RecordingError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        provider = replay
        model = ", ".join(sorted(replay.models))
        notes.append(f"Recorded {min(replay.recorded_at)} .. {max(replay.recorded_at)}")

    adapter = AiAdapter(
        provider=provider,
        config=config,
        ledger=InMemoryBudgetLedger(),
        call_log=InMemoryAiCallLog(),
    )
    scores = run_cases(adapter, cases)
    if recorder is not None and args.record:
        from datetime import UTC, datetime

        stamp = datetime.now(UTC).strftime("%Y-%m-%d")
        recorder.write(recordings, cases, model=model, now=stamp)
        notes.append(f"Recorded {stamp} to `{recordings.relative_to(REPO_ROOT)}`")
    summary = summarize(scores)
    report = render_report(scores, summary, mode=mode, model=model, notes=notes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report)
    print(report)
    print(f"report written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
