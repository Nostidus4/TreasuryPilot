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
| `review_items` | id, org_id, treasury_id, request_id, plan_id, type enum(POLICY_BLOCK, NEEDS_AUTHORITY, FEE_APPROVAL, UNCERTAIN_TX, DISCREPANCY, AI_REJECTED, INFRA, UNEXPECTED_OUTFLOW), primary_code, reason_codes[], completed_steps jsonb, assigned_role, status enum(Open, Resolved, Dismissed), sla_due_at, resolved_by/at, resolution enum(RETRY, REPLAN, CANCEL, EDIT_REQUEST, GRANT_EXCEPTION, ACCEPT_FEE, ACKNOWLEDGE, MARK_MATCHED), note, version | unique(request_id, type) where Open |
| `recovery_runs` | id, operation_id, evidence jsonb, outcome enum(CONFIRMED, REVERTED, NEVER_BROADCAST, STILL_PENDING, ESCALATED), at | append-only |
| `circuit_rules` | id, treasury_id null (global default), rule, threshold, window_s, action enum(ALERT, PAUSE), cooldown_s, enabled | |
| `circuit_events` | id, treasury_id, rule, details, action, at | |

## 5. State

Review item: `Open → Resolved | Dismissed`; acting on an item whose underlying state changed returns `STALE_ITEM` (optimistic version).
Operation recovery: `Unknown → (Confirmed | Reverted | Abandoned (never broadcast, safe to re-plan) | Unknown (escalated))`.

## 6. Interfaces

| Method | Endpoint | Perm | Request → Response | Errors |
|---|---|---|---|---|
| GET | `/orgs/{o}/review-items?status=&type=&role=` | ANY (filtered by role) | → `{items}` | |
| GET | `/orgs/{o}/review-items/{id}` | ANY | → `{item, request, plan, steps, validations, evidence, allowedActions[]}` | |
| POST | `/orgs/{o}/review-items/{id}/actions` 🔁 | routed role | `{action, note?, version}` → `{item}` | 403 `NOT_ROUTED_ROLE`, 409 `STALE_ITEM`, `ACTION_NOT_ALLOWED` |
| GET/PUT | `/orgs/{o}/treasuries/{t}/circuit-rules` | OWN | rules | |
| GET | `/orgs/{o}/treasuries/{t}/circuit-events` | ANY | → `{items}` | |

## 7. Flows

### 7.1 Startup / periodic scan (every 60 s and on worker start)

Load operations in Submitted, Pending or Unknown that have a transaction (`recovery/scan.py`; NotSubmitted is excluded, the executor owns it) → for each: `resolve(op)` (§8.1), inline, with a 30 s timeout per operation; one failing or slow operation is logged and does not stall the rest. A treasury is blocked exactly while one of its operations is Unknown (the execution cycle skips it); there is no separate flag, so it unblocks when none remain Unknown. Scans never overlap (a Postgres session advisory lock; a second scan returns early). The worker-start scan is sent only by workers that consume the `core` queue. There is no per-treasury advisory lock: `resolve_operation` relies on the `FOR UPDATE` row locks and re-checks in `_close`.

### 7.2 Partial completion (AT-07)

Plan stopped at seq k>0 → `PartiallyCompleted` → review item (POLICY_BLOCK or DISCREPANCY) with completed steps → action **RETRY** (types POLICY_BLOCK and INFRA only): the same plan resumes, `RESUME_PARTIAL` NeedsReview → Preparing, Confirmed steps are skipped and the first unfinished step is re-validated (`recovery/partial.py`; refused while an operation is in flight, or if any is Reverted/Abandoned or another review type is open). Action **REPLAN** (plan-shape changes): M10 creates a new plan for the remaining steps (same step ids) → validated/attested → executes only those. Action **CANCEL** (refused while an operation is in flight): request Cancelled, plan Superseded, open items resolved CANCEL; funds stay where the refill put them; the report says so (no automatic reverse refill).

## 8. Algorithms

### 8.1 Unknown resolution (no AI, BR-060)

```
1. If op has tx hashes: getTransactionReceipt for each (primary + secondary)
     receipt status 1 → Confirmed (verify via M11) ; status 0 → Reverted
2. Else / no receipt: executor nonce = getTransactionCount(executor, latest)
     if op.nonce < nonce → some tx with that nonce mined → find it (by nonce scan of recent blocks) → link → 1.
     if op.nonce ≥ nonce and not in mempool → NEVER_BROADCAST → NotSubmitted (the executor replays the same step id; a replay refused as ATTESTATION_EXPIRED ends Abandoned)
3. Module flags: stepUsed[stepId] or requestPaid[requestId] true → treat as Confirmed even without our receipt (e.g. replacement we did not record) → reconcile
4. Still unclear after 30 min → ESCALATED: review item UNCERTAIN_TX (Operator + Owner), treasury stays blocked
```

Code: `treasurypilot_worker.recovery.resolve.resolve_operation(pool, rpc, operation_id)`, called per in-flight operation by the scan (§7.1).

- **Receipt (step 1).** A receipt on the primary or the secondary provider (`RpcClient.receipt_anywhere`) is left to the tracker, which confirms or reverts it (Unknown rows included) once both providers agree; the resolver reports `Receipt`. "No receipt" is claimed only when every provider answered; an error from either returns Unclear and changes nothing.
- **Module flags (step 3).** `stepUsed[stepId]`, or `requestPaid[onchain_request_id]` for a PAY step, read 3 blocks deep, makes the operation Confirmed (our hashes become Dropped). The flags are not re-watched for reorgs.
- **Never broadcast (step 2).** A hash that is unseen and whose nonce is unused, silent for 10 min, returns the operation to NotSubmitted so the executor replays the same step id (the signer returns the same hash, so no new row is inserted and rows restart as Submitted with a fresh clock). A replay the signer refuses as terminal (e.g. `ATTESTATION_EXPIRED`) ends `Abandoned` in the executor (`executor.outbox.execute_step`, `TERMINAL_REFUSALS`), not in the resolver.
- **Consumed nonce (step 2).** The nonce is traced to its block by binary search over the executor's historical `eth_getTransactionCount` (about 15 calls) bounded to the last `TRACE_WINDOW` (7200) blocks, then read from that block. Only a block 3 confirmations deep is classified. If that transaction reverted the operation is `Reverted`; if it succeeded without using the step (flags checked first), our signed transaction can never be mined and the operation is `Abandoned`. Both record `NONCE_CONSUMED_BY <hash>` and drop our rows. Too recent, older than the window, unreadable history or a block without the transaction stays unresolved.
- **Otherwise** it stays Unknown and, after 30 min of silence, opens one UNCERTAIN_TX item (`TX_UNKNOWN`); resolving evidence later sets `evidence_resolved`. Rows are locked transactions-then-operation (the tracker's order) and re-checked first: a receipt, a final status or a newer mempool sighting recorded meanwhile aborts the change. A Pending tx seen in the mempool is left alone. RPC errors or undecodable answers return Unclear.

Remaining limits: the nonce trace needs providers that keep historical state for `TRACE_WINDOW` blocks (otherwise the operation escalates to a human); a single-provider chain never gets a tracker cross-check, so its receipts are not finalized by the tracker.

Traceability (RCV-002, #164):

| Requirement | Evidence |
|---|---|
| Step used on chain becomes Confirmed without resubmission | `test_step_used_on_chain_confirms_without_resubmission`; Anvil with a deployed contract true only for one step id: `test_anvil_step_used_confirms_without_resubmission` |
| `requestPaid` confirms a PAY step | `test_request_paid_on_chain_confirms_a_pay_step`, Anvil: `test_anvil_request_paid_confirms_a_pay_step` |
| Never-broadcast operation is resubmitted with the same step id | `test_never_broadcast_is_replayed_with_the_same_step_id`, Anvil: `test_anvil_never_broadcast_returns_to_not_submitted` |
| Replay refused as ATTESTATION_EXPIRED ends Abandoned | `test_replay_refused_as_attestation_expired_ends_abandoned` |
| Receipt is left to the tracker (BR-060 order), primary or secondary | `test_receipt_or_mempool_is_left_to_the_tracker`, `test_secondary_provider_receipt_is_left_to_the_tracker`, Anvil: `test_anvil_receipt_is_left_to_the_tracker` (stepUsed true, receipt wins) |
| Reverted receipt is not stranded in Unknown | Anvil: `test_anvil_reverted_receipt_is_reverted_by_the_tracker` |
| Consumed nonce traced to its tx: Reverted / Abandoned, bounded | `test_consumed_nonce_traced_to_a_reverted_transaction_is_reverted`, `..._unrelated_success_is_abandoned`, `test_nonce_trace_is_bounded_and_waits_for_confirmations`, Anvil: `test_anvil_consumed_nonce_is_traced_to_its_block` |
| Escalate to UNCERTAIN_TX after 30 min, treasury stays blocked | `test_consumed_nonce_without_evidence_escalates_after_30_minutes`, Anvil: `test_anvil_consumed_nonce_without_evidence_escalates` (asserts the execution-cycle gate) |
| Never guess on RPC failure | `test_rpc_errors_and_empty_answers_never_fall_through` |

All in `services/worker/tests/test_recovery_resolve.py` (CI: Anvil + Postgres job).

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

Code: `treasurypilot_worker.recovery.retry`. The executor wraps each pre-broadcast step in `run_with_retry`, which passes the same frozen `OperationIds` to every attempt and returns a `Stop` with a `ReviewIntent` (type, primary code) that the executor persists via `create_for_outcome`. Exhaustion is `INFRA` / `RETRY_EXHAUSTED`; post-broadcast errors are `UNCERTAIN_TX` / `TX_UNKNOWN`; unknown errors stop as `INFRA` / `UNCLASSIFIED_ERROR` (fail closed).

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
| INFRA | Operator | RETRY (resumes the same plan if it is PartiallyCompleted) |
| UNEXPECTED_OUTFLOW | Owner, Finance | ACKNOWLEDGE |

SLA: NEEDS_AUTHORITY 24 h, FEE_APPROVAL until the last safe execution time, UNCERTAIN_TX 1 h, others 48 h; overdue items escalate to Owner.

`create_for_outcome` is the transaction-scoped queue adapter. It returns no item for
ALLOW and uses the open `(request_id, type)` uniqueness rule for every other
outcome, so repeated or concurrent reports share one actionable item. Review
actions check the routed role and item version under a row lock. UNCERTAIN_TX
acknowledgment stays unavailable until chain evidence marks the item resolved.
The downstream command for actions such as CANCEL and GRANT_EXCEPTION is wired by
the corresponding request and mandate flows; the queue records the reviewed
decision and does not execute a chain transaction itself.

### 8.4 Circuit rules (BR-065 defaults)

| Rule | Threshold | Action |
|---|---|---|
| Contract rejections (reverts or simulation reverts) | ≥ 3 in 10 min | PAUSE |
| AI plan out of mandate (AI_PLAN_REJECTED) | ≥ 1 | PAUSE |
| Coverage drop (COMPLETE → other) | any | PAUSE |
| Post-condition DISCREPANCY | any | PAUSE |
| Unexpected outflow (BR-069) | any | ALERT (PAUSE if > 20 % of wallet balance) |

PAUSE = backend pause + sentinel on-chain pause (ADR-017) + notify Owner. Cool-down 30 min before the same rule alerts again. Only the Owner resumes.

Implementation (RCV-006): worker task `treasurypilot.recovery.circuit_breaker` runs every 60 s (`recovery/circuit.py`). Rejections are `operations` that are `Reverted` or carry `SIMULATION_REVERTED` in the window (by `created_at`); AI_PLAN_REJECTED counts `AI_REJECTED` review items; DISCREPANCY and UNEXPECTED_OUTFLOW consume the pending `CIRCUIT_BREAKER` signals the verifier and indexer raise; COVERAGE_DROP compares `treasuries.coverage` with the last value stored in `circuit_rules.state`. Each trip writes a `circuit_events` row (signal rules are deduplicated per signal, windowed rules by the 30-min cool-down); PAUSE upserts `backend_pause`, emits `CircuitBreakerTripped` (Owner, Guardian) and calls the signer sentinel. Outflow percentage uses the latest stored snapshot balance of the moved wallet; with no snapshot it fails closed (PAUSE). Owners tighten via `PUT /v1/orgs/{org}/treasuries/{t}/circuit/rules/{rule}` (Owner + step-up; only REJECTIONS count/window and the outflow percent, tighten-only; there is no disable flag); history at `GET .../circuit/events`.

Windowed rules count only rejections newer than the rule's last trip (so a spent rejection cannot re-trip it after the cool-down), as distinct plan steps (reverts) or distinct requests (AI_REJECTED). Signal rules (DISCREPANCY, UNEXPECTED_OUTFLOW) record every signal in `circuit_events` and pause each time, but emit `CircuitBreakerTripped` once per 30-min cool-down per rule (signals in one cycle collapse into one notification). The Owner's on-chain resume (indexer `Resumed`) consumes the `CIRCUIT_BREAKER` signals already turned into events, which unblocks planning; nothing else consumes them.

Sentinel retry: every cycle, if the backend pause is still `Requested` on-chain and the latest PAUSE event has `details.onchain` empty, `NOT_CONFIGURED` or `SENTINEL_FAILED`, the worker calls the sentinel again and stamps the result (the signer is idempotent via `alreadyPaused`). If the sentinel is never configured, the on-chain pause never becomes `Effective`, so `resume-tx` is refused: the Owner lifts the backend-only pause with `POST .../pause/cancel`, or a Guardian submits the Guardian Safe pause tx from the notification (after which `resume-tx` works).

Known gap: the on-chain pause only happens when the signer has a sentinel target for the treasury (`/sentinel/pause`). Without one, or if it fails, the backend pause still blocks the worker, `circuit_events.details.onchain` records `NOT_CONFIGURED` or `SENTINEL_FAILED`, and a Guardian must submit the Guardian Safe pause from the notification. Resume stays Owner-only (`POST .../resume-tx`).

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

Traceability (RCV-007, #169): `services/worker/tests/test_recovery_crash_suite.py::test_executor_crash_never_double_pays` (CI: Anvil + Postgres job, ~9 s).

| Requirement | Evidence |
|---|---|
| Worker killed at randomized points around the signer call and the DB write | 20 iterations; the order of 5 crash points (`before_signer`, `after_sign`, `after_broadcast`, `mid_commit`, `after_commit`, 4 runs each) is shuffled by `TP_CRASH_SEED` (default 169, printed with the schedule). The crash is an in-process `BaseException` out of `sequence_plan`; the pool is dropped so uncommitted work rolls back |
| Restart and recovery | startup `scan_in_flight`, then `sequence_plan` again (the stand-in signer replays the stored raw tx by step id), then `track_transactions`, then `sequence_plan` to Paid |
| Exactly one PAY on-chain, request Paid | per iteration: one mined transfer to the iteration's recipient (block scan) and recipient balance equal to the amount; `payment_requests.status = 'Paid'`, one `Confirmed` operation. Mutating the signer to re-sign on retry fails the suite with `2 PAY transfers mined` |

Limits: the worker is simulated in process, not a killed Celery process, and the signer is a stand-in that signs once per step id with an Anvil dev key. `TreasuryPilotModule` and its `requestPaid`/`stepUsed` flags are not deployed here (covered separately in RCV-002 and the contract tests).

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
