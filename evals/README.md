# Evaluation datasets

Versioned invoice labels, planner ground truth, prompt-injection cases and Copilot numeric-fidelity cases live here. Dataset authoring is handled by the matching M09/M20 tickets.

## Planner benchmark

`make bench` (AGT-014) runs three arms on every case in `scenarios/` with identical state and
checks: B0 (manual/EDF, idle cash), B1 (deterministic planner: EDF plus the liquidity action) and
B2 (B1 plus the AI proposal through `select_plan`), N repetitions of B2 (`--repetitions`, default
3). It writes `build/bench/planner-benchmark.md` and `.csv`, and exits non-zero if B1 or B2
breaks a policy check. Ground truth (`expected*`) is never placed in a prompt or tool result.

Modes: `recorded` replays model turns from `scenarios/recorded/<prompt version>/`; `live` calls
the model (needs `ANTHROPIC_API_KEY`), and `make bench-record` also stores the turns; `stand-in`
is an offline scripted EDF provider that exercises the pipeline but is not a model result. The
default `auto` picks live, then recorded, then stand-in. Code: `services/worker/src/treasurypilot_worker/planner_bench/`.
