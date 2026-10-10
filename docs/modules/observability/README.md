# M17 · Observability & Analytics

**Status:** Draft for gate G2 · **Path:** `docs/modules/observability/`

## Purpose
Logs, metrics, traces, error tracking; operational metrics and savings report.

## Features
F-140, F-141, F-142

## Inputs
Events, ai_calls, operations.

## Outputs
Dashboards, metrics endpoints, reports.

## APIs
`/metrics/operations`, `/metrics/savings` (API_SPEC §6), Prometheus `/metrics` (internal).

## Data model
(reads only)

## Dependencies
All modules.

## Security concerns
Redaction in logs; internal-only metrics endpoints.

## Failure scenarios
Sentry down → logs still local.

## Open questions
None.
