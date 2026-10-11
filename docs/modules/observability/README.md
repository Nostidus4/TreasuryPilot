# M17 · Observability & Analytics (`api` + `worker` + `signer` + `web`)

**Status:** Detailed — decisions finalized by the tech lead under the project lead's delegation (2026-10-11) · **Path:** `docs/modules/observability/` · **Epic:** `[EPIC] M17 · Observability & Analytics`
**ADRs:** ADR-011 (structlog + OpenTelemetry + Sentry + Prometheus) · **Decisions:** M17-D1 … M17-D9 (§14)

---

## 1. Purpose and boundaries

M17 lets the team **see what the system is doing** (logs, traces, errors, metrics) and lets customers and judges **see what it achieved** (operational metrics and savings versus the rule baseline).

| In scope (M1) | Out of scope |
|---|---|
| Structured JSON logs with correlation ids across api/worker/signer | Hosted dashboards (Grafana) beyond a basic compose service (optional) |
| OpenTelemetry tracing (FastAPI, Celery, httpx, SQLAlchemy, signer call) | Billing metrics (M18, Later) |
| Sentry (Python + web) and Prometheus `/metrics` | |
| Operational metrics API and savings report | |

## 2. Features, requirements and rules

F-140 (FR-921), F-141 (FR-922), F-142 (FR-923, NFR-AUD-04).

## 3. Metric definitions (OBS-004/005)

| Metric | Definition |
|---|---|
| Completion rate | Paid requests ÷ requests that entered `Scheduled` in the period (rejected/cancelled by humans excluded, blocked by policy included) |
| On-time % | Paid with PAY block time ≤ due date 23:59:59 UTC ÷ Paid |
| Interventions per request | human actions after approval (review actions, fee acceptances, exception grants, re-approvals) ÷ Paid |
| Fees | Σ fee_wei (incl. reverts) per request and per period; per step type |
| Latency by phase | approval→scheduled, scheduled→attested, attested→first submit, submit→confirmed, confirmed→verified (median, p90) |
| Rejections by reason | count of BLOCK by primary code; contract reverts by selector |
| Savings vs B1 | Σ over executed batches of `value(actual) − value(B1 counterfactual)` using the stored snapshot and schedule inputs (discounts captured − late fees − early-payment fees, FEE-2); negative values reported |

## 4. Data model

No new business tables: metrics are computed from `request_status_events`, `plans`, `operations`, `transactions`, `gas_ledger`, `validations`, `review_items`, `schedules`; optional materialized views refreshed every 15 min.

## 5. State — n/a.

## 6. Interfaces

| Method | Endpoint | Perm |
|---|---|---|
| GET | `/orgs/{o}/metrics/operations?from=&to=&treasuryId=` | OWN, FIN, ADM, Auditor |
| GET | `/orgs/{o}/metrics/savings?from=&to=` → `{total, byRequest[], methodology}` | OWN, FIN |
| GET | `/metrics` (Prometheus, internal network only) | infra |

Prometheus series: `tp_queue_depth{queue}`, `tp_rpc_errors_total{provider}`, `tp_rpc_latency_seconds`, `tp_llm_latency_seconds{task}`, `tp_llm_cost_usd_total{task}`, `tp_tx_status_total{status}`, `tp_validation_decisions_total{decision,code}`, `tp_unknown_operations`, `tp_executor_gas_eth{key}`, `tp_circuit_trips_total{rule}`.

## 7. Flows

Every request/task binds `correlation_id`, `org_id`, `request_id`, `plan_id`, `operation_id` into structlog context; Celery headers carry them; the signer receives them in a header. Traces exported via OTLP to the collector (compose service, console exporter locally).

## 8. Algorithms

Savings counterfactual: for each executed batch day, re-run `schedule_edf` on the stored snapshot and the same requests; compute objective value of B1 and the actual executed plan with M07 `request_value`; savings = actual − B1 per request; methodology text generated with the numbers.

## 9. Configuration

Log level INFO (DEBUG locally); sampling: 100 % traces in M1 (low volume); Sentry DSN per service from secrets; Telegram alert hook for Sentry critical errors (reuses M13).

## 10. Security

Redaction processors (M14) run before any sink; `/metrics` not exposed publicly (Caddy blocks); no PII in metric labels.

## 11. Failure scenarios

Sentry/collector down → logs still local, app unaffected (non-blocking exporters).

## 12. Test plan

Correlation id found in api/worker/signer logs for one request; a planning run produces one trace; metric definitions tested on a seeded dataset; savings equal a hand-computed batch; negative savings shown.

## 13. Tickets

OBS-001 → OBS-002 → OBS-003 → OBS-004 → OBS-005.

## 14. Decisions

| ID | Decision |
|---|---|
| M17-D1 | Correlation ids bound everywhere incl. Celery and signer headers. |
| M17-D2 | Metric definitions §3 are the source of truth for the deck. |
| M17-D3 | Savings vs B1 computed from stored snapshots; negatives shown. |
| M17-D4 | Early-payment gas counts against savings (FEE-2). |
| M17-D5 | Prometheus series list §6; no PII labels. |
| M17-D6 | 100 % trace sampling in M1. |
| M17-D7 | Materialized views refreshed every 15 min if queries are slow. |
| M17-D8 | Grafana optional; not required for M1. |
| M17-D9 | `/metrics` internal only. |

## 15. v0.3 changes (ADR-019)

Savings report adds supply interest earned and lost interest from early payments; metrics add reserve breaches (target 0) and liquidity actions per day; benchmark B0 is the idle-cash baseline.
