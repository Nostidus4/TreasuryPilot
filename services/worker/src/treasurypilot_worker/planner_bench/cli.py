"""Planner benchmark (AGT-014, F-092): `make bench`.

Runs B0 (manual/EDF, idle cash), B1 (deterministic planner) and B2 (B1 plus the AI proposal)
on every scenario under `evals/scenarios`, with identical state and checks, N repetitions of B2.
Writes a markdown and a CSV report. Exits non-zero if B1 or B2 breaks a policy check.

Modes (the model call sits behind one provider seam, the code path above it is shared):

* recorded: replays model turns stored in `evals/scenarios/recorded/<prompt version>/`.
  Offline and deterministic. Refused when the prompt version or scenario inputs changed.
* live: calls the configured provider (needs ANTHROPIC_API_KEY); `--record` stores the turns.
* stand-in: offline scripted EDF provider that is not a model; pipeline check only.

`auto` (default) is live with a key, else recorded when recordings exist, else stand-in.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from treasurypilot_worker.agent import (
    AiAdapter,
    AiTask,
    InMemoryAiCallLog,
    InMemoryBudgetLedger,
    load_ai_config,
)
from treasurypilot_worker.planner_bench.providers import (
    PROMPT_VERSION,
    EdfStandInProvider,
    RecordedProvider,
    RecordingError,
    RecordingProvider,
    RunScopedProvider,
)
from treasurypilot_worker.planner_bench.report import RunInfo, render_csv, render_markdown
from treasurypilot_worker.planner_bench.runner import ViolationError, run_all
from treasurypilot_worker.planner_bench.scenarios import SPLITS, ScenarioError, load_scenarios

REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_REPETITIONS = 3


def _live_provider() -> RecordingProvider:
    import anthropic

    from treasurypilot_worker.agent.anthropic_provider import AnthropicProvider

    return RecordingProvider(AnthropicProvider(anthropic.Anthropic(), name="anthropic"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--mode", choices=("auto", "recorded", "live", "stand-in"), default="auto")
    parser.add_argument("--record", action="store_true", help="live: store the model turns")
    parser.add_argument("--split", choices=(*SPLITS, "all"), default="all")
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    parser.add_argument("--scenarios", type=Path, default=REPO_ROOT / "evals" / "scenarios")
    parser.add_argument("--recordings", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "ai.yaml")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "build" / "bench")
    args = parser.parse_args(argv)
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")

    recordings = args.recordings or args.scenarios / "recorded" / PROMPT_VERSION
    mode = args.mode
    if mode == "auto":
        if os.environ.get("ANTHROPIC_API_KEY"):
            mode = "live"
        else:
            mode = "recorded" if recordings.is_dir() else "stand-in"
    if args.record and mode != "live":
        parser.error("--record needs --mode live")

    try:
        scenarios = load_scenarios(args.scenarios, args.split)
    except ScenarioError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    config = load_ai_config(args.config)
    model = config.tasks[AiTask.PLAN].model
    notes: list[str] = []

    provider: RunScopedProvider
    recorder: RecordingProvider | None = None
    if mode == "live":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("live mode needs ANTHROPIC_API_KEY", file=sys.stderr)
            return 2
        recorder = _live_provider()
        provider = recorder
    elif mode == "recorded":
        try:
            replay = RecordedProvider(recordings, scenarios, args.repetitions)
        except RecordingError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        provider = replay
        model = ", ".join(sorted(replay.models))
        notes.append(f"Recorded {min(replay.recorded_at)} .. {max(replay.recorded_at)}")
    else:
        provider = EdfStandInProvider()
        model = "none (scripted EDF stand-in)"

    adapter = AiAdapter(
        provider=provider,
        config=config,
        ledger=InMemoryBudgetLedger(),
        call_log=InMemoryAiCallLog(),
    )
    started = time.monotonic()
    try:
        results = run_all(adapter, provider, scenarios, args.repetitions)
    except ViolationError as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    print(f"run took {time.monotonic() - started:.1f} s", file=sys.stderr)
    if recorder is not None and args.record:
        stamp = datetime.now(UTC).strftime("%Y-%m-%d")
        recorder.write(recordings, scenarios, model=model, recorded_at=stamp)
        notes.append(f"Recorded {stamp} to `{recordings.relative_to(REPO_ROOT)}`")

    info = RunInfo(
        mode=mode,
        model=model,
        prompt_version=PROMPT_VERSION,
        repetitions=args.repetitions,
        notes=tuple(notes),
        stand_in=mode == "stand-in",
    )
    args.out.mkdir(parents=True, exist_ok=True)
    report = render_markdown(results, info)
    (args.out / "planner-benchmark.md").write_text(report)
    (args.out / "planner-benchmark.csv").write_text(render_csv(results))
    print(report)
    print(f"reports written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
