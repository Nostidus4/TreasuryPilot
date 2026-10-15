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
| Worker killed at points around the signer call and the DB write | 24 in-process iterations: 6 crash points (`before_signer`, `after_reserve`, `after_sign`, `after_broadcast`, `mid_commit`, `after_submit_commit`) x 4 runs each. The schedule is a seeded shuffle with fixed coverage (`TP_CRASH_SEED`, default 169, printed with the schedule). The crash is an in-process `BaseException` out of `sequence_plan`; the pool is dropped so uncommitted work rolls back |
| Real process death | `test_process_death_never_double_pays`: a child process runs `execute_step` and calls `os._exit` at `after_sign`, `after_broadcast`, `mid_commit` and `after_submit_commit` (connection lost mid-transaction, no `finally` blocks) |
| State after the death | asserted before the restart: operation status, `attempts`, `transactions` rows and mined PAYs (e.g. `mid_commit` leaves `NotSubmitted`, zero rows, one mined transfer) |
| Restart and recovery | startup `scan_in_flight`, `sequence_plan`, `track_transactions`, `sequence_plan` to Paid; a duplicate `execute_step` on a Submitted/Confirmed operation |
| Exactly one PAY, request Paid | one mined transfer to the iteration's recipient; one `transactions` row whose hash and nonce equal the mined tx; the signer's stored hash equals it too; `attempts` is 2 (1 after `after_submit_commit`); request `Paid`, one `Confirmed` operation |
| The worker's own idempotency is tested, not the signer's replay | the restarted worker reaches the signer exactly once (zero times after `after_submit_commit`), and a duplicate `execute_step` on a Confirmed operation makes no signer call. Removing the `status != 'NotSubmitted'` early return in `execute_step` fails both tests |

The signer stand-in (`crash_support.StoreSigner`) runs on the real `SignerStore` and mirrors the `SigningService` order: reserve under (attestation nonce, step id), persist the raw tx (`record_signed`), broadcast; a replay rebroadcasts the stored bytes and treats "already known" or a mined nonce as success; a reservation with no raw tx is re-signed with the same nonce.

Limits: the real `SigningService` is not driven (it needs a deployed module, a trusted policy signer and attestation fixtures), so its attestation, mandate and fee checks are not exercised. Each PAY is a plain ETH transfer from an Anvil dev key; `TreasuryPilotModule` and its on-chain `stepUsed`/`requestPaid` guards are covered by RCV-002 and the contract tests. `after_submit_commit` stops after the Submitted commit; a crash between operation `Confirmed` and request `Paid` is not injected here.

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
