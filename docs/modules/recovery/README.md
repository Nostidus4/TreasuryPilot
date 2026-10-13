# M12 · Recovery & Exceptions (`worker` + `api`)

**Status:** Detailed and reviewed with the project lead (2026-10-11) · **Path:** `docs/modules/recovery/` · **Code:** `services/worker/.../recovery`, `services/api/.../review` · **Epic:** `[EPIC] M12 · Recovery & Exceptions`
**Decisions:** M12-D1 … M12-D11 (§14)

---

## 1. Purpose and boundaries

M12 makes sure **uncertainty never turns into a second payment**. It resolves in-flight operations after crashes and timeouts from chain evidence, resumes partially completed plans safely, classifies errors for retry, runs the circuit breaker, and turns every stop into exactly one actionable review item for the right role.

| In scope (M1) | Out of scope |
|---|---|
| Startup and periodic scan of in-flight operations | Detecting status (M06) |
| Unknown resolution from receipt, nonce and module flags | Deciding allow/block (M08) |
| Partial completion and resume | Executing steps (M10) |
| Retry policy and error classifier | Notifications delivery (M13) |
| Review queue: creation, routing, SLA, actions | UI (WEB-013) |
| Circuit breaker rules and actions (uses the sentinel, ADR-017) | |
| Crash-recovery proof (RCV-007) | |

## 2. Features, requirements and rules

| Feature | FR | BR |
|---|---|---|
| F-080 Crash/Unknown recovery | FR-701, FR-702 | BR-060, BR-061 |
| F-081 Partial completion | FR-703 | BR-054 |
| F-082 Review queue | FR-704, FR-705 | BR-057 |
| F-083 Retry policy | FR-706 | BR-061 |
| F-027 Circuit breaker | FR-222 | BR-065, BR-068 |

## 3. Concepts

| Term | Definition |
|---|---|
| **In-flight** | Operation in NotSubmitted, Submitted, Pending or Unknown. |
| **Blocked treasury** | Has ≥ 1 Unknown operation → no new planning (BR-060). |
| **Resolution evidence** | (1) receipt by tx hash; (2) executor nonce consumed by which tx; (3) module flags `stepUsed[stepId]`, `requestPaid[requestId]`. |
| **Review item** | One open item per (request, type) with reason codes, completed steps, routed role, SLA. |
| **Circuit rule** | Deterministic condition over recent events that triggers ALERT or PAUSE. |

## 4. Data model

| Table | Columns | Notes |
|---|---|---|
| `review_items` | id, org_id, treasury_id, request_id, plan_id, type enum(POLICY_BLOCK, NEEDS_AUTHORITY, FEE_APPROVAL, UNCERTAIN_TX, DISCREPANCY, AI_REJECTED, INFRA, UNEXPECTED_OUTFLOW), primary_code, reason_codes[], completed_steps jsonb, assigned_role, status enum(Open, Resolved, Dismissed), sla_due_at, source_version, resolved_by/at, resolution enum(RETRY, REPLAN, CANCEL, EDIT_REQUEST, GRANT_EXCEPTION, ACCEPT_FEE, ACKNOWLEDGE, MARK_MATCHED), note, version | unique(request_id, type) where Open; optimistic request-version check |
| `recovery_runs` | id, operation_id, evidence jsonb, outcome enum(CONFIRMED, REVERTED, NEVER_BROADCAST, STILL_PENDING, ESCALATED), at | append-only |
| `circuit_rules` | id, treasury_id null (global default), rule, threshold, window_s, action enum(ALERT, PAUSE), cooldown_s, enabled | |
| `circuit_events` | id, treasury_id, rule, details, action, at | |

## 5. State

Review item: `Open → Resolved | Dismissed`; acting on an item whose underlying state changed returns `STALE_ITEM` (optimistic version). When the request leaves review any other way (`REVIEW_RESOLVED`, `EXCEPTION_GRANTED`, cancel, expiry) its open items are Dismissed, and an item from an earlier visit is Dismissed when the request re-enters review, so every visit gets one fresh, actionable item.
Operation recovery: `Unknown → (Confirmed | Reverted | Abandoned (never broadcast, safe to re-plan) | Unknown (escalated))`.

## 6. Interfaces

| Method | Endpoint | Perm | Request → Response | Errors |
|---|---|---|---|---|
| GET | `/orgs/{o}/review-items?status=&type=&role=` | ANY (filtered by role) | → `{items}` | |
| GET | `/orgs/{o}/review-items/{id}` | ANY | → `{item, request, plan, steps, validations, evidence, allowedActions[]}` | |
| POST | `/orgs/{o}/review-items/{id}/actions` 🔁 | routed role | `{action, note?, version}` → `{item}` | 403 `NOT_ROUTED_ROLE`, 409 `STALE_ITEM`, `ACTION_NOT_ALLOWED`, request-transition errors (e.g. 403 `TRANSITION_FORBIDDEN`), 503 `REVIEW_UNAVAILABLE` |
| GET/PUT | `/orgs/{o}/treasuries/{t}/circuit-rules` | OWN | rules | |
| GET | `/orgs/{o}/treasuries/{t}/circuit-events` | ANY | → `{items}` | |

The API exposes these review operations under `/v1/orgs/{orgId}/review-items`: list (filtered to the caller's routed roles), get, and post an action. The source request version is captured when an item is opened; actions compare both that version and the item's optimistic `version`. A changed request or stale item returns `STALE_ITEM`. `uq_review_items_open_request_type` is a partial unique index, and review creation only emits `NeedsReview:<Role>` when it inserts a new open item, so retries and concurrent workers cannot fan out duplicate work or notifications. Resolving moves the payment request in the same transaction: `CANCEL` → Cancelled (under the request state machine's cancel rules), `RETRY`/`REPLAN` → Scheduled; `GRANT_EXCEPTION` (M03), `EDIT_REQUEST` (re-approval), `ACCEPT_FEE` and the acknowledgements leave it in place. Until the API wires a request state machine, actions that move the request return 503 instead of resolving without effect. Listing defaults to Open items (`includeClosed=true` for history) with `limit` (default 100, max 500). Primary and reason codes use the code token before any `:` detail. Overdue escalation runs only in the worker.

`RequestStateMachine` opens review items in the same transaction for `NEEDS_APPROVAL`, `PLAN_BLOCKED`, `PREPARATION_FAILED`, and `PAY_UNKNOWN` outcomes. Other recovery producers use the same `open_review_item` helper and type-specific routing table. The worker escalates items after `sla_due_at` every 60 seconds, moving the routed role to Owner and enqueueing an outbox notification.

## 7. Flows

### 7.1 Startup / periodic scan (every 60 s and on worker start)

Load in-flight operations → mark their treasuries blocked → for each: `resolve(op)` (§8.1) → unblock when none remain Unknown.

### 7.2 Partial completion (AT-07)

Plan stopped at seq k>0 → `PartiallyCompleted` → review item (POLICY_BLOCK or DISCREPANCY) with completed steps → action **REPLAN**: M10 creates a new plan for the remaining steps (same step ids) → validated/attested → executes only those. Action **CANCEL**: request Cancelled; funds stay where the refill put them; the report says so (no automatic reverse refill).

## 8. Algorithms

### 8.1 Unknown resolution (no AI, BR-060)

```
1. If op has tx hashes: getTransactionReceipt for each (primary + secondary)
     receipt status 1 → Confirmed (verify via M11) ; status 0 → Reverted
2. Else / no receipt: executor nonce = getTransactionCount(executor, latest)
     if op.nonce < nonce → some tx with that nonce mined → find it (by nonce scan of recent blocks) → link → 1.
     if op.nonce ≥ nonce and not in mempool → NEVER_BROADCAST → Abandoned (same step id may be re-planned)
3. Module flags: stepUsed[stepId] or requestPaid[requestId] true → treat as Confirmed even without our receipt (e.g. replacement we did not record) → reconcile
4. Still unclear after 30 min → ESCALATED: review item UNCERTAIN_TX (Operator + Owner), treasury stays blocked
```

### 8.2 Retry classifier (RCV-005)

| Error | Class | Action |
|---|---|---|
| RPC 5xx, timeout before broadcast, connection reset | retryable | backoff 2 s × 2ⁿ, max 6 |
| `nonce too low` | retryable after resync | signer resyncs nonce; same payload |
| `replacement underpriced` | retryable | bump per policy |
| Signer typed refusal (`PAYLOAD_MISMATCH`, `ATTESTATION_*`) | terminal | review item AI_REJECTED / POLICY_BLOCK |
| `SIMULATION_REVERTED` | terminal for this plan | review POLICY_BLOCK |
| `INSUFFICIENT_GAS` | terminal until funded | review INFRA, low-gas alert |
| Anything after broadcast without receipt | **not retried** | → tracker/Unknown path |

Ids (request, step, operation, idempotency key) never change across attempts (BR-061).

### 8.3 Routing table

| Type | Role | Allowed actions |
|---|---|---|
| NEEDS_AUTHORITY (over cap) | Owner | GRANT_EXCEPTION (→ M03), CANCEL |
| POLICY_BLOCK payee/limit/budget | Owner | REPLAN (after policy edit), CANCEL |
| POLICY_BLOCK amount/payee/approval | Operator → Approver | EDIT_REQUEST (re-approval), CANCEL |
| FEE_APPROVAL | Finance, Operator, Owner | ACCEPT_FEE, defer |
| UNCERTAIN_TX | Operator (+ Owner informed) | ACKNOWLEDGE after resolution only |
| DISCREPANCY | Finance + Owner | ACKNOWLEDGE, MARK_MATCHED |
| AI_REJECTED | Operator | REPLAN (deterministic), CANCEL |
| INFRA | Operator | RETRY |
| UNEXPECTED_OUTFLOW | Owner, Finance | ACKNOWLEDGE |

SLA: NEEDS_AUTHORITY 24 h, FEE_APPROVAL until the last safe execution time, UNCERTAIN_TX 1 h, others 48 h; overdue items escalate to Owner.

### 8.4 Circuit rules (BR-065 defaults)

| Rule | Threshold | Action |
|---|---|---|
| Contract rejections (reverts or simulation reverts) | ≥ 3 in 10 min | PAUSE |
| AI plan out of mandate (AI_PLAN_REJECTED) | ≥ 1 | PAUSE |
| Coverage drop (COMPLETE → other) | any | PAUSE |
| Post-condition DISCREPANCY | any | PAUSE |
| Unexpected outflow (BR-069) | any | ALERT (PAUSE if > 20 % of wallet balance) |

PAUSE = backend pause + sentinel on-chain pause (ADR-017) + notify Owner. Cool-down 30 min before the same rule alerts again. Only the Owner resumes.

## 9. Configuration and defaults

Scan interval 60 s; escalation after 30 min; retry max 6; SLAs per §8.3; circuit rules per §8.4 (Owner can tighten, not disable PAUSE rules in M1).

## 10. Security

| Threat | Control |
|---|---|
| Double payment after crash | outbox + chain evidence resolution + contract replay flags; RCV-007 |
| Retry storms | backoff + max attempts + circuit breaker |
| Wrong person resolves | routed role check; Owner-only for authority |
| AI deciding recovery | none — deterministic only (BR-058) |
| Stale actions | optimistic version → STALE_ITEM |

## 11. Failure scenarios

Worker killed mid-flight → scan + resolution; RPC down during recovery → remain blocked (never guess); sentinel unavailable → backend pause still holds, human guardian prompted.

## 12. Test plan

Unit: classifier table; routing; circuit rule windows. Integration (Anvil): Unknown resolution via receipt, via nonce, via module flags; partial completion resume (AT-07); circuit breaker pause within one cycle via sentinel. Fault injection: RCV-007 — 20/20 runs with exactly one PAY.

## 13. Tickets

RCV-001 scan → RCV-002 resolution → RCV-005 retry → RCV-003 partial/resume → RCV-004 review queue → RCV-006 circuit breaker → RCV-007 crash test.

## 14. Decisions

| ID | Decision |
|---|---|
| M12-D1 | Resolution order: receipt → nonce → module flags; never AI; never resend while Unknown. |
| M12-D2 | Escalate Unknown after 30 min to UNCERTAIN_TX; treasury stays blocked. (reviewed) |
| M12-D3 | Partial completion: REPLAN remaining steps with the same step ids, or CANCEL leaving funds in place. |
| M12-D4 | One open review item per (request, type); optimistic version. |
| M12-D5 | Routing and SLAs per §8.3. (reviewed) |
| M12-D6 | Retry only before broadcast; after broadcast use the tracker path. |
| M12-D7 | Circuit rules per §8.4; PAUSE uses the sentinel. |
| M12-D8 | Unexpected outflow: ALERT, PAUSE above 20 % of wallet balance. (reviewed) |
| M12-D9 | PAUSE rules can be tightened but not disabled in M1. (reviewed) |
| M12-D10 | Cool-down 30 min per rule. (reviewed) |
| M12-D11 | New review types FEE_APPROVAL and UNEXPECTED_OUTFLOW (from M03, M06). |
