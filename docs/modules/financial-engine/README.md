# M07 · Financial Engine (py-core)

**Status:** Draft for gate G2 · **Path:** `docs/modules/financial-engine/`

## Purpose
Pure deterministic money logic: liquidity formulas, refill decisions, terms-aware scheduler/objective, forecast, minOut, fingerprint normalization.

## Features
F-051, F-052, F-058, F-059 (Later); helpers for F-037, F-064

## Inputs
Snapshot data, approved requests with confirmed terms, mandate limits, date.

## Outputs
Funding numbers, schedules with objective scores, feasibility reasons, runway projections.

## APIs
Python package API (no HTTP): `compute_shortage(...)`, `decide_refill(...)`, `schedule(requests, state, policy) -> Schedule`, `score(plan)`, `forecast(...)`.

## Data model
None (pure functions; inputs/outputs are Pydantic models).

## Dependencies
None. Must not import I/O (import-linter contract).

## Security concerns
Correctness is security: property tests (hypothesis) that no output breaches the buffer or limits, plus Domain §3.4 golden tests.

## Failure scenarios
Invalid inputs raise typed errors; never partial results.

## Open questions
None.
