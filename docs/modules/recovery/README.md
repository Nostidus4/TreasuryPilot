# M12 · Recovery & Exception Handling

**Status:** Draft for gate G2 · **Path:** `docs/modules/recovery/`

## Purpose
Unknown-state recovery, partial completion, review queue and routing, retry policy, circuit breaker.

## Features
F-027, F-080, F-081, F-082, F-083

## Inputs
Operation states, chain lookups, validator outcomes, anomaly signals.

## Outputs
Resolved operations, review items, pause events.

## APIs
`/review-items…` (API_SPEC §5).

## Data model
review_items, circuit_events (+ operations updates)

## Dependencies
M06, M10, M08, M13, M03 (pause).

## Security concerns
Never create new ids on retry; never guess outcomes; no AI in recovery decisions.

## Failure scenarios
Ambiguous for longer than the threshold → NeedsReview; treasury blocked until resolved.

## Open questions
None.
