# ADR-015: Google OR-Tools CP-SAT for the terms-aware scheduler
**Status:** Accepted (M07 grilling, 2026-10-11) · **Decisions:** M07-D5 … M07-D8

## Context
The scheduler assigns approved requests to days under integer constraints (daily caps, source capacity, buffers, payee cooling, refill bound) with a lexicographic objective (BR-052). Amounts are integers in base units (ADR-014). Problem size is small (tens of requests, ≤ 30 days) but the result must be optimal, deterministic and explainable.

## Decision
- Use **OR-Tools CP-SAT** (Apache-2.0) as the optimizer behind a `Solver` interface in `py-core`.
- Solve the objective in stages (deadlines met → value → transaction count → approval order).
- Determinism: one worker, fixed seed, sorted inputs. Time limit 5 s per cycle; on error/timeout without a solution, fall back to EDF and mark `FALLBACK`.
- Keep an exhaustive **oracle** (N ≤ 8) for tests only, to prove CP-SAT returns the optimum.
- `py-core` remains free of I/O; OR-Tools is a pure computation dependency (import-linter still forbids DB, HTTP, web3, Celery).

## Alternatives
- Hand-written branch-and-bound: no dependency, but correctness and scale are on us.
- HiGHS via SciPy: light, but floating-point arithmetic on money and multi-pass objectives.
- PuLP + CBC: readable, slower, floating-point.
- Timefold, Gurobi/CPLEX: too heavy or licensed.

## Consequences
- One more dependency (~tens of MB wheel); pinned version in `uv.lock`.
- The deck can state that schedules come from a production-grade solver and are proven optimal on the test set.
