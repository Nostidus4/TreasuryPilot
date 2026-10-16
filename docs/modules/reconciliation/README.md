# M11 · Verification & Reconciliation (`worker` + `api`)

**Status:** Detailed and reviewed with the project lead (2026-10-11) · **Path:** `docs/modules/reconciliation/` · **Code:** `services/worker/.../verify`, `services/api/.../reconciliation` · **Epic:** `[EPIC] M11 · Verification & Reconciliation`
**ADRs:** ADR-018 (EAS receipts) · **Decisions:** M11-D1 … M11-D11 (§14)

---

## 1. Purpose and boundaries

M11 answers two questions after money moves: **did the chain end up exactly as planned?** (post-conditions, per step) and **can Finance close the books on this payment?** (reconciliation, per request). It also publishes the EAS receipt and the accounting export.

| In scope (M1) | Out of scope |
|---|---|
| Post-condition verification per confirmed step (PASSED / DISCREPANCY / UNKNOWN) | Tracking receipts (M06) |
| Reconciliation records with classified lines (BR-096) | Executing or retrying (M10, M12) |
| Match / discrepancy / auto-match (org setting, default off) | QuickBooks and NetSuite adapters (Later, REC-L02, REC-L03) |
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
| `chain_attestations` | id, request_id (unique), chain_id, schema_uid, attestation_uid, tx_hash, status enum(Queued, Sent, Confirmed, Failed), attempts, next_attempt_at, last_error (exception type only), created_at, updated_at | ADR-018; written only by the core worker. `reconciliations.eas_uid` is set when Confirmed |

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

The reconciliation detail `evidence` also carries `easUrl` (easscan link, once Confirmed) and `receipt{status, attempts, txHash, nextAttemptAt}`; the evidence bundle carries `easUid` and `easUrl`.

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
| EAS receipt | as soon as the request is Paid and the PAY block is finalized (independent of matching); beat sweep every 30 s (`treasurypilot.reconciliation.publish_receipts`), off unless `TP_EAS_RPC_URL`, `TP_EAS_CONTRACT_ADDRESS` and `TP_EAS_RECEIPT_PRIVATE_KEY` are set (`TP_EAS_RECEIPT_ADDRESS` must be that key's address so the low-gas sweep watches it) |
| EAS retry | exponential backoff 30 s doubling to 1 h, unbounded; a broadcast not mined after 15 min is retried |
| Export formats | CSV, journal CSV |
| ERP connectors | off unless the provider's OAuth app is configured (`TP_XERO_CLIENT_ID`, `TP_XERO_CLIENT_SECRET`; QuickBooks: `TP_QUICKBOOKS_CLIENT_ID`, `TP_QUICKBOOKS_CLIENT_SECRET`, `TP_QUICKBOOKS_SANDBOX`; NetSuite: `TP_NETSUITE_ACCOUNT_ID`, `TP_NETSUITE_CLIENT_ID`, `TP_NETSUITE_CLIENT_SECRET`; plus `TP_ERP_OAUTH_REDIRECT_URI`) and `TP_FIELD_ENCRYPTION_KEY` is set; ERP retry backoff 30 s doubling to 1 h, 8 attempts, then Failed; payment poll for bill approval 15 min |

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
| M11-D11 | ERP sync creates bills as drafts only and applies a payment only after a human approves the bill in the ERP (§16). |

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
- **Traceability:**

  | Scope item | Where |
  |---|---|
  | Expected effects per step type | `verify.py::expected_effects` |
  | Observed = Multicall3 state at header(B).hash minus header(B).parentHash, other txs' transfers netted | `compute`, `_state`, `_concurrent_net` |
  | PASSED / DISCREPANCY / UNKNOWN, 3-read rule | `PostConditionVerifier.verify`, `executor/sequencer.py::_post_condition` |
  | Review item and breaker signal | `sequencer.py::_post_condition`, `PostConditionVerifier._store` |
  | EXE-008 gating (verify before the next step is sent) | the sequencer calls the verifier (`tasks.py`) |
  | Unit / Postgres tests | `tests/reconcile/test_verify.py`, `tests/executor/test_sequencer_integration.py` |
  | Anvil end to end | `tests/reconcile/test_verify_anvil.py`, `execution-integration` CI job |

- Anvil tests use real Multicall3 code and the compiled `TestUSDC`, `MockAavePool`/`MockAToken` from `contracts/src`. The module is `contracts/test/helpers/ReconcileModuleStandIn.sol` (real Solidity, holds the funds, honours `stepUsed`, `requestPaid`, `usedToday` per action and asset); the full `TreasuryPilotModule` needs a Safe and EIP-712 approvals. Cases: normal PAY, same-block concurrent transfer, wrong amount (review item and breaker), SUPPLY with aToken rounding, WITHDRAW. With `CI` set, a missing anvil, forge or database fails the tests instead of skipping.

## Match, discrepancy and auto-match implementation notes (REC-003, #157)

- Routes live in `services/api/.../reconciliation/routes.py`. All writes lock the row and bump `version`; an optional `If-Match` header (`"N"`, `W/"N"` or `N`; no other route requires it, so it stays optional here) returns 412 `VERSION_CONFLICT` when stale. List and detail also show Operators/Admins per §6; list filters `from`/`to` use the UTC day of `created_at`.
- **Evidence rule** (`treasurypilot_core.reconciliation_evidence`, shared by API and worker, one facts query): valid approval, attestation covering every operation's step, all operations Confirmed, every Confirmed operation has a PASSED verification (any DISCREPANCY blocks), and every line still backed by its Confirmed transaction at the same block with its `gas_ledger` fee (this re-check catches stale FEE lines after a reorg). Missing items are returned as `EVIDENCE_INCOMPLETE{missing}`; then the PAY block must be at or below the chain's `finalized` block, else `NOT_FINALIZED`. The EAS UID is not required yet (REC-005, and M11-D8 makes it independent of matching).
- **Discrepancy**: Finance flags a Pending reconciliation with a note. The worker also flags a Pending one when any of its operations has a DISCREPANCY verification. **Resolve** takes `{note}` from Finance and `{acknowledge: true}` from an Owner, in either order; it becomes Matched (`USER`, Finance user) once both are on record. The Owner must be a different user from the Finance author unless the org is in solo mode. The final resolve step still requires the PAY block to be finalized (`NOT_FINALIZED`), checked with the RPC read done before the row lock; it does not re-run the other evidence checks (a human accepted the difference). The Owner acknowledgment re-checks on-chain ownership when the wallet service is configured.
- **Auto-match** (`worker/.../reconcile/auto_match.py`, beat task every minute): only for orgs with `organizations.auto_match` on, which now defaults to **off** (migration 0073 also switches existing orgs off). It applies the same rule plus §8.3 strict checks (no document differs from the request's invoice hash and the Valid approval signed that hash; PAY lines sum to the invoice amount and went to the request's payee and asset) and finality.
- Follow-up: step-up on the Owner acknowledgment; list pagination.
- Not done: step-up is not required on these routes (the spec lists none); the setting is changed through the existing `PATCH /orgs/{id}/settings`.

## Export implementation notes (REC-004, #158)

- **M1 ships a synchronous `GET /v1/orgs/{o}/reconciliation/export?from=&to=&format=csv|journal`** that streams the CSV in the response. The async `POST /exports` -> `202`, signed URL, `exports` table and stored sha256 flow are deferred.
- **Roles:** Finance and OrgAdmin only (Owner and Operator get 403). The spec's export rows above are aligned to FIN, ADM.
- **Period:** inclusive UTC days, `to` must not precede `from` (422 `EXPORT_PERIOD_INVALID`), at most 366 days (422 `EXPORT_PERIOD_TOO_LONG`).
- **Totals check (M11-D7):** per (class, asset), the integer sum of exported lines is compared with an independent aggregate over the source rows: `SUM(plan_steps.amount)` of Confirmed operations with Confirmed transactions (by `confirmed_at` UTC day) for non-FEE classes, and `SUM(gas_ledger.fee_wei)` by `gas_ledger.day` for FEE, both limited to requests that have a reconciliation. A difference returns 409 `EXPORT_TOTALS_MISMATCH` listing `(class, asset, expected, exported)`. An ERC-20 without an `assets` row returns 409 `EXPORT_ASSET_UNKNOWN`.
- **Fee column (`fee (ETH)`):** the tx fee in ETH, repeated on every non-FEE line of the same transaction. It is blank on FEE lines, whose `amount` already is the fee. Do not sum the column.
- Unmatched (Pending) and other-status reconciliations are included with their status.
- **Per-org account mappings (migration 0084):** `account_mappings` stores one row per (org, class, side DEBIT|CREDIT) because a journal line pair needs two accounts (the spec's single `account_code` column is split by `side`). Finance/OrgAdmin read the effective mapping with `GET .../reconciliation/account-mappings` and replace the org's overrides with `PUT` (audited, 422 `ACCOUNT_MAPPING_INVALID` for unknown classes). Unlisted sides use the generic defaults in code; mapping cells are formula-neutralized in the export.
- **Supply interest:** classification `SUPPLY_INTEREST` (generic 1300 Lending Position / 4100 Interest Income), one `Computed` line per treasury dated the period end: aToken balance in the last snapshot before the period end minus the last snapshot before the period start minus net SUPPLY-WITHDRAW confirmed between those two snapshots. No line when either snapshot is missing or the result is not positive. It is appended after the totals check (it is derived from snapshots, not reconciled lines). Snapshots must be `COMPLETE` and lie within one day before the period start and before the end plus one day (the worker stores a retained `DAILY` snapshot per treasury at 00:00 UTC); otherwise, or when the result is not positive, the line is omitted, a warning is logged and the reason is returned in the `X-Export-Notes` response header. `SUPPLY_INTEREST` is excluded from the on-chain totals check.
- Follow-up: async export (`POST /exports`, `exports` table, stored sha256) is not built; the synchronous export meets the acceptance criteria.

## 16. ERP integration framework (REC-L01, F-075)

Code: `services/api/.../integrations/erp`. Migration `20261016_0089` adds `erp_connections` (per org and provider: tenant id, AES-GCM `FieldCipher` envelopes for the access and refresh token bound to their column, expiry, `status` Connected | ReauthRequired, `payment_account_code`) and `erp_sync_records` (one row per reconciliation, connection and kind BILL | PAYMENT; status Pending | AwaitingApproval | Synced | Failed; deterministic `idempotency_key`; attempts, `next_attempt_at`, `last_error` without bodies). The per-org journal `account_mappings` (REC-004) is reused: the EXTERNAL_EXPENSE debit account is the bill's expense account.

**Provider protocol** (`provider.py`, `ErpProvider`): `authorize_url`, `exchange_code`, `refresh`, `resolve_tenant`, `create_draft_bill`, `bill_status`, `create_payment`. Adapters are stateless and HTTP goes through the `HttpClient` protocol (`http.py`); a new ERP is one adapter module plus one line in `registry.py`. Errors: `ErpTransientError` (network, 429 with Retry-After, 5xx: retried with backoff), `ErpAuthError` (connection flagged ReauthRequired), `ErpPermanentError` (record Failed until an explicit re-sync).

**Flow.** `POST .../integrations/erp/{provider}/sync {reconciliationId}` (Finance, Owner, Org admin) queues and runs the BILL, and the PAYMENT too once the reconciliation is Matched. Records are committed before any network call; adapters look the object up by invoice number or tx-hash reference and send the idempotency key, so a retry after a crash reuses the object. `POST .../{provider}/retry` runs due records (the same `ErpService.retry_due` is what a scheduler would call).

**Mapping** (`mapping.py`, pure): bill = vendor, invoice no, issue and due dates, request fiat amount and currency, else a USD stablecoin booked as USD cents; sub-cent precision or an asset without a fiat value is refused, never rounded. Payment = EXTERNAL_EXPENSE line, `Reference` = tx hash, date = execution day, bank account from the connection setting.

**Never approves.** Bills are created as drafts (Xero `ACCPAY`, `Status: DRAFT`) and no protocol method can authorise one. A payment is applied only after `bill_status` reports the bill approved by a human in the ERP; until then it stays AwaitingApproval and is polled.

**OAuth.** The `state` is an encrypted, 10 minute token bound to org, user and provider. The web app calls `.../authorize`, sends the user to the ERP, and posts the returned `code` and `state` to `.../callback`. Tokens never appear in responses, logs or audit data; rotated refresh tokens are persisted before use. Audit actions: `erp.connected`, `erp.disconnected`, `erp.settings_changed`, `erp.reauth_required`, `erp.bill_drafted`, `erp.payment_recorded`, `erp.sync_failed`.

Not verified against a live Xero account (tests use scripted HTTP shaped like Xero's documented responses). Xero-specific limits: one organisation per connection, contacts are matched by exact name.

**NetSuite adapter (REC-L03).** `netsuite.py`, registered as `netsuite`. OAuth 2.0 authorization code against `https://<account>.app.netsuite.com` (scope `rest_webservices`); tokens at `https://<account>.suitetalk.api.netsuite.com/services/rest/auth/oauth2/v1/token`. The account id comes from `TP_NETSUITE_ACCOUNT_ID` and is the tenant id. Bills are `vendorBill` records with `approvalStatus` Pending Approval (`1`); no call sets Approved (`2`), so the NetSuite account must enable "Require approvals on vendor bills" for the approval gate to hold (state APPROVED only when `approvalStatus` is `2`; `VendBill:B` is PAID, `VendBill:V` VOIDED). Payments are `vendorBill/{id}/!transform/vendorPayment` with the tx hash in `memo`. Vendors (by company name), bills (by transaction number and vendor) and payments (by memo) are looked up with SuiteQL before any create; NetSuite has no idempotency header. `expense_account_code` and the payment account setting are NetSuite internal account ids. Not verified against a live account; OneWorld subsidiary, custom forms and exchange rates are not set, so accounts requiring them return a permanent error.

### 16.1 QuickBooks Online connector (REC-L02)

`integrations/erp/quickbooks.py`, registered in `registry.py` when `TP_QUICKBOOKS_CLIENT_ID` and `TP_QUICKBOOKS_CLIENT_SECRET` are set; it passes the same adapter contract tests as Xero (`tests/test_erp_quickbooks.py`). Differences from Xero:

- **No draft state.** QuickBooks posts a bill on creation, so the adapter writes it with `PrivateNote` = `[TP-PENDING-APPROVAL]`; `bill_status` is DRAFT while that marker is present, APPROVED once a human removes it in QuickBooks, PAID at zero balance, VOIDED when voided. No adapter call removes the marker, so it still never approves.
- **Company id.** QuickBooks returns the `realmId` in the OAuth redirect, not from an API. The web app passes it as `realmId` in the `POST /v1/orgs/{organization_id}/integrations/erp/quickbooks/callback` body (optional for other ERPs); the route forwards it to the adapter, and `exchange_code` returns it as `TokenSet.tenant_hint` and the framework then skips `resolve_tenant` (the only shared-framework change, in `provider.py` and `service.py`).
- Account codes (expense account, payment bank account) are QuickBooks account Ids. Payments are `BillPayment` (Check) linked to the bill, `PrivateNote` = tx hash. Idempotency uses the `requestid` parameter plus lookups by `DocNumber` and tx hash. Invoice numbers over 21 characters are refused, not truncated.

Not verified against a live QuickBooks company (tests use scripted HTTP shaped like Intuit's documented responses).
