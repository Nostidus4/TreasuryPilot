"""Markdown and CSV report: three arms, per-scenario rows, and where B2 is worse."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from treasurypilot_worker.planner_bench.arms import Outcome
from treasurypilot_worker.planner_bench.runner import ScenarioResult

CSV_FIELDS = (
    "scenario",
    "split",
    "family",
    "arm",
    "repetition",
    "planner_source",
    "ai_status",
    "value_saved",
    "interest",
    "net_benefit",
    "net_after_ai_cost",
    "on_time",
    "requests",
    "missed_deadlines",
    "exceptions",
    "tx_count",
    "violations",
    "reserve_breaches",
    "liquidity_action",
    "latency_ms",
    "cost_usd_micros",
)


@dataclass(frozen=True)
class RunInfo:
    mode: str
    model: str
    prompt_version: str
    repetitions: int
    notes: tuple[str, ...] = ()
    stand_in: bool = False


def _row(
    result: ScenarioResult, arm: str, rep: int | str, o: Outcome, source: str, status: str
) -> dict[str, object]:
    s = result.scenario
    return {
        "scenario": s.id,
        "split": s.split,
        "family": s.family,
        "arm": arm,
        "repetition": rep,
        "planner_source": source,
        "ai_status": status,
        "value_saved": o.value_saved,
        "interest": o.interest,
        "net_benefit": o.net_benefit,
        "net_after_ai_cost": o.net_after_cost,
        "on_time": o.on_time,
        "requests": o.requests,
        "missed_deadlines": o.missed_deadlines,
        "exceptions": o.exceptions,
        "tx_count": o.tx_count,
        "violations": o.violations,
        "reserve_breaches": o.reserve_breaches,
        "liquidity_action": o.liquidity_action,
        "latency_ms": o.latency_ms,
        "cost_usd_micros": o.cost_usd_micros,
    }


def render_csv(results: Sequence[ScenarioResult]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for r in results:
        writer.writerow(_row(r, "B0", "", r.b0, "DETERMINISTIC", "NONE"))
        writer.writerow(_row(r, "B1", "", r.b1, "DETERMINISTIC", "NONE"))
        for run in r.b2:
            writer.writerow(
                _row(r, "B2", run.repetition, run.outcome, run.planner_source, run.ai_status)
            )
    return out.getvalue()


def _pct(part: int, whole: int) -> str:
    return "n/a" if whole == 0 else f"{part * 100 / whole:.1f}%"


def _mean(total: int, count: int) -> int:
    return total // count if count else 0


def _arm_outcomes(results: Sequence[ScenarioResult]) -> dict[str, list[list[Outcome]]]:
    """Per arm, one list of per-scenario outcomes per repetition (B0 and B1 have one list)."""

    reps = len(results[0].b2) if results else 0
    return {
        "B0": [[r.b0 for r in results]],
        "B1": [[r.b1 for r in results]],
        "B2": [[r.b2[i].outcome for r in results] for i in range(reps)],
    }


def _total(rows: list[list[Outcome]], field: Callable[[Outcome], int]) -> int:
    """Sum over scenarios, averaged (floor) over repetitions."""

    return _mean(sum(field(o) for rep in rows for o in rep), len(rows))


def _summary_table(results: Sequence[ScenarioResult]) -> list[str]:
    arms = _arm_outcomes(results)
    lines = [
        "| Metric | B0 manual/EDF, idle cash | B1 deterministic | B2 AI + checks |",
        "| --- | --- | --- | --- |",
    ]

    def add(label: str, field: Callable[[Outcome], int]) -> None:
        cells = " | ".join(str(_total(arms[a], field)) for a in ("B0", "B1", "B2"))
        lines.append(f"| {label} | {cells} |")

    add("Value saved (base units)", lambda o: o.value_saved)
    add("Supply interest (base units)", lambda o: o.interest)
    add("Net benefit (base units)", lambda o: o.net_benefit)
    add("Net benefit after AI cost (base units)", lambda o: o.net_after_cost)
    ontime = " | ".join(
        _pct(_total(arms[a], lambda o: o.on_time), _total(arms[a], lambda o: o.requests))
        for a in ("B0", "B1", "B2")
    )
    lines.append(f"| On-time payments | {ontime} |")
    add("Missed deadlines", lambda o: o.missed_deadlines)
    add("Exceptions needed", lambda o: o.exceptions)
    add("Transactions", lambda o: o.tx_count)
    add("Policy violations", lambda o: o.violations)
    add("Reserve breaches", lambda o: o.reserve_breaches)
    add("Latency, total ms", lambda o: o.latency_ms)
    add("AI cost (USD micros)", lambda o: o.cost_usd_micros)
    return lines


def _b2_spread(results: Sequence[ScenarioResult]) -> str:
    reps = _arm_outcomes(results)["B2"]
    totals = [sum(o.net_benefit for o in rep) for rep in reps]
    return f"{min(totals)} .. {max(totals)}" if totals else "n/a"


def _scenario_table(results: Sequence[ScenarioResult]) -> list[str]:
    lines = [
        "| Scenario | Split | Family | Net benefit B0 / B1 / B2 | Missed B0 / B1 / B2 "
        "| Tx B0 / B1 / B2 | Reserve breaches B0 / B1 / B2 | B2 chose AI |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        runs = r.b2
        reps = len(runs)

        def trio(field: Callable[[Outcome], int], r: ScenarioResult = r) -> str:
            b2 = _mean(sum(field(x.outcome) for x in r.b2), len(r.b2))
            return f"{field(r.b0)} / {field(r.b1)} / {b2}"

        chose = sum(x.planner_source == "AI" for x in runs)
        s = r.scenario
        lines.append(
            f"| {s.id} | {s.split} | {s.family} | {trio(lambda o: o.net_benefit)} "
            f"| {trio(lambda o: o.missed_deadlines)} | {trio(lambda o: o.tx_count)} "
            f"| {trio(lambda o: o.reserve_breaches)} | {chose}/{reps} |"
        )
    return lines


def worse_cases(
    results: Sequence[ScenarioResult], against: str = "b1"
) -> list[tuple[str, int, list[str], str]]:
    """(scenario, repetition, metrics, reason) where a B2 repetition loses to B1 or B0."""

    found = []
    for r in results:
        base = r.b1 if against == "b1" else r.b0
        for run in r.b2:
            metrics = run.outcome.worse_than(base)
            if metrics:
                found.append((r.scenario.id, run.repetition, metrics, run.chosen_reason))
    return found


def _worse_section(results: Sequence[ScenarioResult], reps: int) -> list[str]:
    lines = ["## Scenarios where B2 is worse", ""]
    worse = worse_cases(results)
    if worse:
        lines += [
            f"B2 repetitions that lose to B1 on an outcome metric ({len(worse)} of "
            f"{len(results) * reps}):",
            "",
        ]
        lines += [
            f"- {sid} repetition {rep}: worse on {', '.join(metrics)} ({reason})"
            for sid, rep, metrics, reason in worse
        ]
    else:
        lines += [
            f"None. In all {len(results)} scenarios x {reps} repetitions B2 matched or beat B1 "
            "on every outcome metric (violations, value saved, net benefit, missed deadlines, "
            "on-time, exceptions, transactions, reserve breaches). That is by construction "
            "(`select_plan` keeps B1's plan unless the AI plan is valid and strictly better), "
            "so B2 can only lose on cost and latency, listed next.",
        ]
    lines += ["", "B2 is always worse than B1 on cost and latency where the model was called:", ""]
    called = [r for r in results if any(x.ai_status != "SKIPPED" for x in r.b2)]
    if called:
        for r in called:
            cost = _mean(sum(x.outcome.cost_usd_micros for x in r.b2), len(r.b2))
            lat = _mean(sum(x.outcome.latency_ms for x in r.b2), len(r.b2))
            lines.append(
                f"- {r.scenario.id}: {cost} USD micros, {lat} ms (B1: 0 and {r.b1.latency_ms} ms)"
            )
    else:
        lines.append("- No model call in this run.")
    lines += [
        "",
        "Arms that lose to the idle-cash baseline B0 on an outcome metric (acting costs transactions):",
        "",
    ]
    for arm_name, getter in (("B1", lambda r: r.b1), ("B2", None)):
        losers = []
        for r in results:
            outcomes = [getter(r)] if getter else [x.outcome for x in r.b2]
            metrics = sorted({m for o in outcomes for m in o.worse_than(r.b0)})
            if metrics:
                losers.append(f"{r.scenario.id} ({', '.join(metrics)})")
        lines.append(f"- {arm_name}: {', '.join(losers) if losers else 'none'}")
    return lines


def _improvements(results: Sequence[ScenarioResult]) -> list[str]:
    b1_over_b0 = [r.scenario.id for r in results if r.b0.worse_than(r.b1)]
    b2_over_b1 = [r.scenario.id for r in results if any(r.b1.worse_than(x.outcome) for x in r.b2)]
    ai_chosen = [r.scenario.id for r in results if any(x.planner_source == "AI" for x in r.b2)]
    return [
        f"- B1 beats B0 on at least one outcome metric in {len(b1_over_b0)} scenarios: "
        f"{', '.join(b1_over_b0) or 'none'}.",
        f"- B2 beats B1 on at least one outcome metric in {len(b2_over_b1)} scenarios: "
        f"{', '.join(b2_over_b1) or 'none'}.",
        f"- B2 chose the AI plan in {len(ai_chosen)} scenarios: {', '.join(ai_chosen) or 'none'}.",
    ]


def render_markdown(results: Sequence[ScenarioResult], info: RunInfo) -> str:
    splits = {s: [r for r in results if r.scenario.split == s] for s in ("dev", "heldout")}
    statuses: dict[str, int] = {}
    for r in results:
        for run in r.b2:
            statuses[run.ai_status] = statuses.get(run.ai_status, 0) + 1
    lines = [
        "# Planner benchmark: B0 vs B1 vs B2 (AGT-014)",
        "",
        "Generated by `make bench`; do not edit by hand.",
        "",
    ]
    if info.stand_in:
        lines += [
            "> **Offline stand-in run, not a model result.** The B2 arm used a scripted EDF "
            "stand-in provider, so B2 equals B1 by design. Record a live run to measure the AI.",
            "",
        ]
    lines += [
        f"- Mode: {info.mode}",
        f"- Model: `{info.model}`, prompt `{info.prompt_version}`",
        f"- Scenarios: {len(results)} (dev {len(splits['dev'])}, heldout {len(splits['heldout'])}); "
        f"B2 repetitions: {info.repetitions}",
        "- B2 repetition outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(statuses.items())),
        *[f"- {note}" for note in info.notes],
        "- Policy violations in B1 and B2: 0 (the run fails otherwise)",
        "",
        "Arms: B0 is manual/EDF with idle cash (no supply or withdraw). B1 is the deterministic "
        "planner: EDF plus the liquidity engine's action. B2 is B1 plus the AI proposal through "
        "`select_plan`, planned on B1's post-liquidity state and scored by the same engine "
        "`score`. Ground truth is read for scoring only and never enters a prompt or tool "
        "result. Amounts are integer base units (6 decimals, so 1 USD micro = 1 base unit). "
        "B2 figures are the mean over repetitions (floor). Interest is simple interest on "
        "the Aave balance over the horizon. Latency of B0 and B1 is measured engine wall time "
        "and varies run to run.",
        "",
        "## Summary, all scenarios",
        "",
        *_summary_table(results),
        "",
        f"B2 total net benefit per repetition ranges over {_b2_spread(results)}.",
    ]
    for name, subset in splits.items():
        if subset:
            lines += [
                "",
                f"## Summary, {name} ({len(subset)} scenarios)",
                "",
                *_summary_table(subset),
            ]
    lines += ["", "## Where each arm wins", "", *_improvements(results), ""]
    lines += _worse_section(results, info.repetitions)
    lines += ["", "## Per scenario", "", *_scenario_table(results), ""]
    lines += [
        "## Caveats",
        "",
        "- Scenarios and labels were authored by the same AI assistant, are public, and await "
        "second-person review; `heldout` is a family partition, not an unseen test set "
        "(`evals/scenarios/README.md`).",
        "- Most scenarios are solved by EDF, so a small difference between arms is expected; "
        "supply interest is zero where the scenario's supply rate is zero.",
    ]
    return "\n".join(lines) + "\n"
