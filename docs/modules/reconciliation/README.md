# M11 · Verification & Reconciliation (`worker` + `api`)

**Status:** Detailed and reviewed with the project lead (2026-10-11) · **Path:** `docs/modules/reconciliation/` · **Code:** `services/worker/.../verify`, `services/api/.../reconciliation` · **Epic:** `[EPIC] M11 · Verification & Reconciliation`
**ADRs:** ADR-018 (EAS receipts) · **Decisions:** M11-D1 … M11-D10 (§14)

---

## 1. Purpose and boundaries

M11 answers two questions after money moves: **did the chain end up exactly as planned?** (post-conditions, per step) and **can Finance close the books on this payment?** (reconciliation, per request). It also publishes the EAS receipt and the accounting export.

| In scope (M1) | Out of scope |
|---|---|
| Post-condition verification per confirmed step (PASSED / DISCREPANCY / UNKNOWN) | Tracking receipts (M06) |
| Reconciliation records with classified lines (BR-096) | Executing or retrying (M10, M12) |
| Match / discrepancy / auto-match (org setting, default off) | Accounting system sync (Later, REC-L01…L03) |
| CSV + journal export with generic and per-org account mapping | |
| EAS payment receipts (REC-005, ADR-018) | |
| Finality check before a reconciliation can be Matched | |

## 2. Features, requirements and rules

| Feature | FR | BR |
|---|---|---|
| F-071 Post-conditions | FR-603, FR-604 | BR-065 |
| F-072 Reconciliation | FR-605, FR-606 | BR-053, BR-096 |
| F-073 Export | FR-607, FR-307 | |
| F-074 On-chain receipt | FR-608 | BR-074 |
| F-075 ERP (Later) | FR-609 | BR-001 |

## 3. Concepts

| Term | Definition |
|---|---|
| **Expected effects** | Per step type, the exact state changes the plan implies (§8.1). |
| **Verification** | Expected vs observed at the confirmation block (+ the block before) → PASSED / DISCREPANCY / UNKNOWN. |
| **Reconciliation** | Per request: lines (refill, swap, pay, gas) with classes, evidence, status `NotReady → Pending → Matched | Discrepancy`. |
| **Evidence set** | Approval, attestation, operations, transactions (finalized), verifications, invoice document hash, EAS UID. |
| **Finalized** | Block at or below the chain's `finalized` tag (Sepolia ≈ 2 epochs). Matched requires finalized (M11-D2). |

## 4. Data model

| Table | Columns | Notes |
|---|---|---|
| `verifications` | id, operation_id, block_number, expected jsonb, observed jsonb, diffs jsonb, result enum(PASSED, DISCREPANCY, UNKNOWN), at | append-only |
| `reconciliations` | id, org_id, treasury_id, request_id, status enum(NotReady, Pending, Matched, Discrepancy), created_at, matched_by enum(USER, AUTO) null, matched_user_id, matched_at, note, finalized_at, eas_uid, version | one per request |
| `reconciliation_lines` | id, reconciliation_id, classification enum(INTERNAL_TRANSFER, CONVERSION, EXTERNAL_EXPENSE, LENDING_TRANSFER, FEE) (renamed from `class`), operation_id, transaction_id, tx_hash, from_address, to_address (null for FEE), asset_address (null for FEE), amount, fee_wei, block_number, day | |
| `account_mappings` | id, org_id, class, account_code, account_name | default generic rows seeded (OQ-12) |
| `exports` | id, org_id, period_from, period_to, format enum(CSV, JOURNAL), storage_key, sha256, totals jsonb, created_by | |
| `chain_attestations` | id, request_id, schema_uid, attestation_uid, tx_hash, status enum(Queued, Sent, Confirmed, Failed), attempts | ADR-018 |

## 5. State

Reconciliation: `NotReady` (request not Paid) → `Pending` (Paid; lines built) → `Matched` (user or auto, needs finalized + all evidence) | `Discrepancy` (user, or verification DISCREPANCY) → `Matched` after resolution note by Finance + Owner acknowledgment.

## 6. Interfaces

| Method | Endpoint | Perm | Request → Response | Errors |
|---|---|---|---|---|
| GET | `/orgs/{o}/reconciliations?status=&from=&to=` | FIN, OWN, ADM | → `{items}` | |
| GET | `/orgs/{o}/reconciliations/{id}` | FIN, OWN, ADM, OPR | → `{reconciliation, lines[], evidence{approval, attestation, txs, verifications, document, easUid}}` | |
| POST | `/orgs/{o}/reconciliations/{id}/match` | FIN | `{note?}` → `{status: Matched}` | 409 `EVIDENCE_INCOMPLETE{missing}`, `NOT_FINALIZED` |
| POST | `/orgs/{o}/reconciliations/{id}/discrepancy` | FIN | `{note}` → `{status: Discrepancy}` | |
| POST | `/orgs/{o}/reconciliations/{id}/resolve` | FIN + OWN ack | `{note}` → `{status: Matched}` | |
| POST | `/orgs/{o}/exports` | FIN, ADM | `{from, to, format}` → `202 {exportId}` | |
| GET | `/orgs/{o}/exports/{id}` | FIN, ADM | → signed URL | |
| GET/PUT | `/orgs/{o}/account-mappings` | FIN, ADM | mapping table | |

Internal: `verify(operation_id)` (called by M10 before the next step), `build_reconciliation(request_id)`, `publish_receipt(request_id)`.

## 7. Flows

```
step Confirmed (M06) → verify(op) → PASSED → M10 continues
                                   → DISCREPANCY → stop plan, review item (M12), circuit-breaker signal
                                   → UNKNOWN (read failed) → retry 3× then review item
PAY Verified → request Paid → build_reconciliation (Pending)
finalized reached → EAS receipt queued (M11-D8) → auto-match if enabled and evidence complete → Matched
```

## 8. Algorithms

### 8.1 Expected effects

| Step | Expected at block B vs B−1 |
|---|---|
| REFILL(T→Oi, a) | `bal(T) −a`, `bal(Oi) +a`, `usedOn[REFILL,day] +a`, `stepUsed[id]`, `refilledFor[req][Oi]` |
| PAY(Oi→payee, a) | `bal(Oi) −a`, `bal(payee) +a`, `usedOn[PAY,day] +a`, `requestPaid`, `stepUsed`, `fingerprintPaid`; if exception: `exceptions[req].used` |
| SWAP (P2) | input −x, output ≥ minOut, allowance back to 0 |

Observed = values at block B minus values at B−1, read via Multicall3 pinned blocks. Other transfers in the same block that touch the same wallet are subtracted using the indexed `token_movements` of block B (so a concurrent inflow does not cause a false DISCREPANCY). Any remaining difference → DISCREPANCY with `diffs`.

### 8.2 Classification (BR-096)

REFILL → INTERNAL_TRANSFER; SWAP → CONVERSION; SUPPLY/WITHDRAW → LENDING_TRANSFER; PAY → EXTERNAL_EXPENSE; every transaction's fee → FEE (ETH, valued at the reference price only in exports, labelled). A refill whose PAY never succeeded stays on an unpaid request and does not produce an expense.

### 8.3 Auto-match (OQ-09, default off)

All of: PAY verification PASSED, PAY block finalized, approval Valid at execution, attestation present, invoice document hash equals the approval `invoiceHash` (when a document exists), amount equals the invoice amount. Otherwise Pending for manual match.

### 8.4 Export

Period by UTC day of execution. CSV columns: date, request id, vendor, invoice no, class, amount, asset, tx hash, fee (ETH), status, matched by. Journal: per line debit/credit by the mapping (generic default: EXTERNAL_EXPENSE → Dr Expense / Cr Wallet O_i; INTERNAL_TRANSFER → Dr Wallet O_i / Cr Wallet T; FEE → Dr Bank & Fees / Cr Executor Gas). Totals by class must equal the sum of on-chain amounts for the period; mismatch aborts the export. Cells neutralized (FR-307).

## 9. Configuration and defaults

| Parameter | Default |
|---|---|
| Auto-match | off (org setting) |
| Matched requires | finalized block |
| Verification retries on read failure | 3, then UNKNOWN → review |
| EAS receipt | as soon as the request is Paid and the PAY block is finalized (independent of matching) |
| Export formats | CSV, journal CSV |

## 10. Security

| Threat | Control |
|---|---|
| Matching without evidence | server-side evidence checklist; Matched refused otherwise |
| Reorg after Paid | Matched waits for finalized; M06 demotes on reorg |
| Tampered export | sha256 stored; totals check |
| PII on-chain | EAS schema has hashes and addresses only |
| Formula injection | neutralized cells |

## 11. Failure scenarios

| Failure | Behaviour |
|---|---|
| Post-state read fails | UNKNOWN after 3 retries; plan stops; review item |
| Unexpected extra transfer in the same block | subtracted using indexed movements; if unexplained → DISCREPANCY |
| EAS down | receipt Failed, retried with backoff; payment unaffected |
| Export totals mismatch | export aborted with the differing lines |

## 12. Test plan

Unit: expected-effect builder per step type; classification; journal mapping; totals check. Integration (Anvil): normal pay PASSED; injected extra outflow → DISCREPANCY; concurrent inflow not a discrepancy; auto-match on/off; export totals. Testnet: EAS receipt resolves on easscan.

## 13. Tickets

REC-001 verification → REC-002 reconciliation records → REC-003 match/auto-match → REC-005 EAS receipts → REC-004 export. Later: REC-L01…L03.

## 14. Decisions

| ID | Decision |
|---|---|
| M11-D1 | Post-conditions compare block B vs B−1 with concurrent movements subtracted. (reviewed) |
| M11-D2 | Matched requires the PAY block to be finalized. (reviewed) |
| M11-D3 | Auto-match is an org setting, default off (OQ-09). |
| M11-D4 | DISCREPANCY stops the plan and signals the circuit breaker. |
| M11-D5 | Classes per BR-096; fees separate lines in ETH. |
| M11-D6 | Generic account mapping + per-org table (OQ-12). |
| M11-D7 | Export aborts when class totals differ from on-chain totals. |
| M11-D8 | EAS receipt published as soon as the request is Paid and the PAY block is finalized; it does not wait for Finance matching. (reviewed, changed) |
| M11-D9 | Resolving a Discrepancy needs a Finance note and Owner acknowledgment. (reviewed) |
| M11-D10 | Verification UNKNOWN after 3 read failures. |

## 15. v0.3 changes (ADR-019)

SUPPLY and WITHDRAW are reconciled as `LENDING_TRANSFER` lines (treasury ↔ lending position), not expenses; post-conditions: SUPPLY → Safe USDC −x, aToken +≥ x−1, allowance 0; WITHDRAW → Safe USDC +x, aToken −≈x. Exports show supply interest earned for the period (aToken growth minus net supplied). **Tickets:** REC-001, REC-002, REC-004 revised.

## Post-condition verification implementation notes (REC-001, #155)

- Observed effects come from `eth_getLogs` (by `blockHash`) plus Multicall3 reads, not from `token_movements`: the indexer lags the confirmation and a movement row may not exist yet when the next step must be gated. Logs with `removed: true`, a receipt whose `blockHash` differs from header(B), or any unreadable state raise `RpcError`; the step ends as UNKNOWN (never DISCREPANCY) and is retried.
- The B-1 pin is `header(B).parentHash`. Other transactions' transfers in block B are netted out (inflow and outflow).
- `used_today` is not diffed: the module's day key is `block.timestamp / 1 days`, so the counter can reset between B-1 and B. It only has to be `>=` the step amount at B.
- aToken: underlying balances are exact. The aToken delta may be at most 2 wei below expected and at most 2 wei + `before_atoken * 1e-6` above it (one block of interest; conservative).
- Each verifier call makes one read attempt. The sequencer opens the INFRA review on the 3rd UNKNOWN newer than the operation's last PASSED/DISCREPANCY and the request's last resolved `VERIFICATION_UNKNOWN` review.
- One PASSED/DISCREPANCY per operation (partial unique index), so concurrent verifiers raise one breaker signal.
- `chain_safety_signals.observed_event_id` and `token_movement_id` are nullable now; a check constraint requires either both or a `verification_id`.

## Export implementation notes (REC-004, #158)

- **M1 ships a synchronous `GET /v1/orgs/{o}/reconciliation/export?from=&to=&format=csv|journal`** that streams the CSV in the response. The async `POST /exports` -> `202`, signed URL, `exports` table and stored sha256 flow are deferred.
- **Roles:** Finance and OrgAdmin only (Owner and Operator get 403). The spec's export rows above are aligned to FIN, ADM.
- **Period:** inclusive UTC days, `to` must not precede `from` (422 `EXPORT_PERIOD_INVALID`), at most 366 days (422 `EXPORT_PERIOD_TOO_LONG`).
- **Totals check (M11-D7):** per (class, asset), the integer sum of exported lines is compared with an independent aggregate over the source rows: `SUM(plan_steps.amount)` of Confirmed operations with Confirmed transactions (by `confirmed_at` UTC day) for non-FEE classes, and `SUM(gas_ledger.fee_wei)` by `gas_ledger.day` for FEE, both limited to requests that have a reconciliation. A difference returns 409 `EXPORT_TOTALS_MISMATCH` listing `(class, asset, expected, exported)`. An ERC-20 without an `assets` row returns 409 `EXPORT_ASSET_UNKNOWN`.
- **Fee column (`fee (ETH)`):** the tx fee in ETH, repeated on every non-FEE line of the same transaction. It is blank on FEE lines, whose `amount` already is the fee. Do not sum the column.
- Unmatched (Pending) and other-status reconciliations are included with their status.
- Follow-ups: per-org `account_mappings` (generic mapping only for now), supply interest in exports, async export with sha256.
