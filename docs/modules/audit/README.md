# M15 · Audit & Evidence (`api` + `worker`)

**Status:** Detailed (spec completion pass, 2026-10-11 — *(mặc định)* = proposal accepted by default, open for review) · **Path:** `docs/modules/audit/` · **Code:** `services/api/.../audit`, `services/worker/.../evidence` · **Epic:** `[EPIC] M15 · Audit & Evidence`
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

## 4. Data model

`audit_log` (bigserial seq, per-org chain, no UPDATE/DELETE trigger), `evidence_bundles` (id, org_id, request_id or scenario_id, storage_key, sha256, schema_version, created_at).

## 5. State

Append-only. Verification status computed on demand: `INTACT | BROKEN_AT(seq)`.

## 6. Interfaces

| Method | Endpoint | Perm |
|---|---|---|
| GET | `/orgs/{o}/audit-log?entity=&actor=&from=&to=` | Auditor, OWN, ADM |
| GET | `/orgs/{o}/audit-log/verify` → `{status, checked, brokenAt?}` | Auditor, OWN |
| GET | `/orgs/{o}/requests/{r}/evidence` → bundle (JSON) | Auditor, OWN, FIN |
| POST | `/orgs/{o}/scenarios/{id}/evidence` (demo/benchmark runs) | OWN, ADM |
| CLI | `python -m treasurypilot.audit verify --dump file.jsonl` | offline |

## 7. Flows

Service performs action → `audit.write(...)` inside the same DB transaction (row lock on the org's chain head) → commit; failure → whole action rolls back (BR-097). Evidence: request Paid/Blocked → on demand exporter joins everything → validates against JSON schema → stores with sha256.

## 8. Algorithms

- **Chain head lock:** `SELECT … FROM audit_heads WHERE org_id = ? FOR UPDATE` then insert with `prev_hash = head.hash`; update head. Canonical JSON: sorted keys, no spaces, amounts as strings, timestamps ISO-8601 UTC.
- **Evidence bundle v1 fields:** request (ids, vendor display, amounts, fingerprint, invoiceHash), approval (typed data, signer address, signature hash only), flags + acks, plan (planner source, plan hash, steps), validations (all stages), ai_calls (purpose, model, prompt version, output summary), attestation (typed data, signer), operations/transactions (hashes, blocks, fees), verifications, reconciliation, EAS UID, coverage labels, fixture labels (TEST asset/router), generated_at, app version. **No fabricated hashes**: a blocked request has no tx section (BR-095).
- **Coverage labels:** every status DTO includes `coverage {level, missing[], snapshotBlock}`.

## 9. Configuration

Audit retention: forever in M1; evidence stored in the private bucket; verification CLI shipped with the repo.

## 10. Security

DB trigger blocks UPDATE/DELETE; chain detects edits in a dump; signatures stored as hashes in bundles; bundles exclude Confidential data except vendor display name *(mặc định)*.

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
| M15-D6 | Bundles store signature hashes, not raw signatures. *(mặc định)* |
| M15-D7 | Coverage object on every status DTO. |
| M15-D8 | Audit retention forever in M1. *(mặc định)* |
| M15-D9 | Bundle exclude Confidential data except vendor display name. *(mặc định)* |
