# M15 · Audit & Evidence (`api` + `worker`)

**Status:** Detailed — decisions finalized by the tech lead under the project lead's delegation (2026-10-11) · **Path:** `docs/modules/audit/` · **Code:** `services/api/.../audit`, `services/worker/.../evidence` · **Epic:** `[EPIC] M15 · Audit & Evidence`
**Decisions:** M15-D1 … M15-D9 (§14)

---

## 1. Purpose and boundaries

M15 gives TreasuryPilot a **tamper-evident memory** and a way to **prove** what happened: a hash-chained audit log written in the same transaction as every money/authority action, and evidence bundles that tie a request or demo scenario to approvals, plans, validations, AI calls, attestations and on-chain transactions.

| In scope (M1) | Out of scope |
|---|---|
| Hash-chained, append-only audit log per org | Daily on-chain anchoring of the hash root (Later AUD-L01) |
| Audit read + chain verification (API + offline script) | |
| Evidence bundle schema v1 + exporter (request and scenario) | |
| Coverage labels propagated through API responses | |

## 2. Features, requirements and rules

F-120 (FR-911, FR-912, BR-097, NFR-AUD-01–02), F-121 (FR-913, BR-095), F-122 (FR-914).

## 3. Concepts

| Term | Definition |
|---|---|
| **Audit record** | `{seq, org_id, at, actor_type (USER, SYSTEM, AI, CONTRACT), actor_id, action, entity_type, entity_id, data, prev_hash, hash}`; `hash = sha256(prev_hash ‖ canonical_json(record without hash))`. |
| **Audited action** | Anything that affects money or authority: approvals, governance txs and signatures, mandate activation, payee changes, exceptions, plan attestations, operations, pause/resume, role changes, wallet links, solo mode, fee acceptance, review actions, exports. |
| **Evidence bundle** | JSON `evidence-bundle.v1` + optional attachments (document hash, report), sha256-sealed. |
| **Daily audit anchor** | One immutable SHA-256 chain head per organization and UTC day, published by an authorized platform account to `AuditRootAnchor`. |

## 4. Data model

`audit_log` (bigserial seq, per-org chain, no UPDATE/DELETE trigger), `audit_heads` (one locked head per org, created with the org), and `evidence_bundles` (id, org_id, request_id or scenario_id, storage_key, sha256, schema_version, created_at).

## 5. State

Append-only. Verification status computed on demand: `INTACT | BROKEN_AT(seq)`. `brokenAt` is the first record whose `prev_hash` does not link or whose hash does not recompute; the API also checks the chain ends at the org's head, so a record past the head or a removed tail is reported (a removed tail at the head's `last_seq`). The API reads the head and the rows in one `REPEATABLE READ` snapshot.

## 6. Interfaces

| Method | Endpoint | Perm |
|---|---|---|
| GET | `/orgs/{o}/audit-log?entityType=&entityId=&actor=&from=&to=&cursor=&limit=` → `{items, nextCursor}` (`from` inclusive, `to` exclusive, both timezone-aware) | Auditor, OWN, ADM |
| GET | `/orgs/{o}/audit-log/verify` → `{status, checked, brokenAt}` | Auditor, OWN |
| GET | `/orgs/{o}/requests/{r}/evidence` → bundle (JSON) | Auditor, OWN, FIN |
| POST | `/orgs/{o}/scenarios/{id}/evidence` (demo/benchmark runs) | OWN, ADM |
| CLI | `python services/api/src/treasurypilot_api/audit/chain.py verify --dump file.jsonl` (standard library only, the same module the API hashes with; JSON Lines of `audit-log` items; exit 0 intact, 1 broken, 2 unreadable; a dump has no head, so a removed tail is only caught by the API) | offline |

## 7. Flows

Service performs action → `audit.write(...)` inside the same DB transaction (row lock on the org's chain head) → commit; failure → whole action rolls back (BR-097). Evidence: request Paid/Blocked → on demand exporter joins everything → validates against JSON schema → stores with sha256.

## 8. Algorithms

- **Chain head lock:** each organization gets its genesis head (`last_hash` = 32 zero bytes) when it is created (DB trigger); a missing head raises `AuditHeadMissing`, never a new chain. `write()` locks the head with `SELECT … FOR UPDATE` (re-read, never from the session cache) and allocates `seq` in the same statement, inserts with `prev_hash = head.last_hash` and updates the head, all in the caller's transaction (it flushes, never commits). The lock is held until commit: call `write()` last, and write several orgs in ascending `org_id` order. `hash = sha256(canonical_json(record))`; the record includes `prev_hash` as lowercase hex, and `compute_hash(row)` (in the stdlib-only `audit/chain.py`) recomputes it from a stored row. Canonical JSON uses sorted keys and no spaces; amounts are integer base-unit strings (integral Decimals are converted; floats, fractional Decimals and NUL are rejected so values survive the JSONB round trip); timestamps are ISO-8601 UTC. `audit_log` rejects UPDATE, DELETE and TRUNCATE; a started head cannot be deleted or truncated.
- **Evidence bundle v1 fields:** request (ids, vendor display, amounts, fingerprint, invoiceHash), approval (typed data, signer address, signature hash only), flags + acks, plan (planner source, plan hash, steps), validations (all stages), ai_calls (purpose, model, prompt version, output summary), attestation (typed data, signer), operations/transactions (hashes, blocks, fees), verifications, reconciliation, EAS UID, coverage labels, fixture labels (TEST asset/router), generated_at, app version. **No fabricated hashes**: a blocked request has no tx section (BR-095).
- **Coverage labels:** every status DTO includes `coverage {level, missing[], snapshotBlock}`.

### Exporter implementation boundary (AUD-003)

The API contract and schema live in `services/api/src/treasurypilot_api/audit/evidence.py` and `evidence-bundle.v1.schema.json`. The request evidence route accepts an injected `EvidenceRepository`; that repository must scope the request to the organization, provide the operation/transaction rows, and resolve every transaction hash against its configured chain before returning. Missing hashes raise an invalid-bundle result and the HTTP route returns `409 EVIDENCE_INVALID` without a bundle. An empty transaction list is omitted, so blocked requests carry validator logs without a fabricated tx section. Signature values are rejected; only `signatureHash` is representable. Unknown fields are rejected and contact fields are checked recursively, with vendor display name as the sole exception.

The SQL exporter/storage adapter remains dependent on execution persistence from EXE-008 (#65). Until that adapter is wired into `create_app(evidence_repository=...)`, this route returns `503 EVIDENCE_UNAVAILABLE`; do not treat the schema/model slice as proof that operation or chain evidence has been integrated. Fixture labels are supplied by that adapter and must distinguish synthetic/testnet data.

## 9. Configuration

Audit retention: forever in M1; evidence stored in the private bucket; verification CLI shipped with the repo.

## 10. Security

DB trigger blocks UPDATE/DELETE; chain detects edits in a dump; signatures stored as hashes in bundles; bundles exclude Confidential data except vendor display name.

## 11. Failure scenarios

Audit write fails → financial action fails closed; storage full → alert and block financial actions; exporter finds a tx hash that does not resolve → bundle marked INVALID and not delivered.

## 12. Test plan

Trigger rejects update/delete; chain valid per org; tamper in a test DB → verify reports first broken seq; forced audit failure aborts an approval; bundle validates against schema; every tx hash resolves on Anvil/Sepolia; blocked request bundle has no tx section.

## 13. Tickets

AUD-001 → AUD-002 → AUD-004 → AUD-003. Later AUD-L01.

## 14. Decisions

| ID | Decision |
|---|---|
| M15-D1 | Per-org sha256 hash chain with a locked head row. |
| M15-D2 | Audit write in the same transaction; failure aborts the action. |
| M15-D3 | Audited action list per §3. |
| M15-D4 | Offline verification CLI. |
| M15-D5 | Evidence bundle v1 fields per §8; no fabricated hashes. |
| M15-D6 | Bundles store signature hashes, not raw signatures. |
| M15-D7 | Coverage object on every status DTO. |
| M15-D8 | Audit retention forever in M1. |
| M15-D9 | Bundle exclude Confidential data except vendor display name. |

### Later · AUD-L01 anchoring boundary

`contracts/src/AuditRootAnchor.sol` is the on-chain registry for daily roots. The
contract accepts one root per opaque organization identifier and UTC day, rejects
future dates and overwrites, and restricts publication to the configured publisher
for that organization. A separate existence bit allows the all-zero genesis head to
be anchored. The worker reads `audit_heads.last_hash` values inside one read-only
`REPEATABLE READ` transaction and publishes those exact bytes. Retries read `isAnchored`
for that organization and UTC day. Once an anchor exists, a retry is a no-op even if
the live audit head has advanced; the first daily root is immutable and is never
overwritten.

The worker runs daily at 00:05 UTC. Configure `TP_AUDIT_ANCHOR_RPC_URL`,
`TP_AUDIT_ANCHOR_CHAIN_ID`, `TP_AUDIT_ANCHOR_CONTRACT_ADDRESS`, and the dedicated
`TP_AUDIT_ANCHOR_PRIVATE_KEY` only in the core worker, after the publisher address is
allowlisted in the contract. The RPC chain id is checked before signing; the private
key is never logged. Do not configure a general purpose treasury signing key.

The contract is not deployed by the current deployment scripts. Production use still
requires reviewed deployment/address publication and provisioned dedicated publisher
secrets. Until those external steps are complete, the scheduled task fails closed.
