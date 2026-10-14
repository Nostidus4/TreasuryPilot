# M14 · Compliance (`api` + `worker` + `py-core`)

**Status:** Detailed — decisions finalized by the tech lead under the project lead's delegation (2026-10-11) · **Path:** `docs/modules/compliance/` · **Code:** `services/api/.../compliance`, `packages/py-core/.../privacy` · **Epic:** `[EPIC] M14 · Compliance`
**Decisions:** M14-D1 … M14-D9 (§14)

---

## 1. Purpose and boundaries

M14 keeps TreasuryPilot from **paying the wrong party** (sanctions/blocklist screening) and from **leaking data** (classification, encryption, redaction). In M1 the screening provider is a labelled fixture; the adapter makes a commercial provider a drop-in later.

| In scope (M1) | Out of scope |
|---|---|
| Screening adapter + fixture provider (TEST DATA) | KYB, Travel Rule, retention/deletion, region pinning (Later) |
| Screening at payee registration and before each PAY (TTL) | Legal opinions (DOM tickets) |
| Data classification, field encryption, log redaction | |

## 2. Features, requirements and rules

F-110 (FR-906, BR-085, NFR-CMP-04), F-113 (FR-909, BR-074, NFR-PRIV-01–04); Later F-111, F-112, F-114.

## 3. Concepts

| Class | Examples | Handling |
|---|---|---|
| **Public** | tx hashes, contract addresses | none |
| **Internal** | request ids, amounts, statuses | org isolation |
| **Confidential** | vendor contact, emails, Telegram chat ids, invoice documents, OOB notes | encrypted at rest (field-level, AES-GCM with a key from Docker secret), redacted in logs, never on-chain |
| **Secret** | keys, tokens, signer secrets | never in DB/logs; secrets store only |

Screening result: `CLEAR | HIT | ERROR`, TTL 24 h.

## 4. Data model

`screenings` (M03 §4), `screening_lists` (fixture entries: address, source label, list_name, added_at — marked TEST DATA), `encryption_keys_meta` (key id, created_at, rotated_at; key material outside DB).

## 5. State

Payee screening: `Screening → CLEAR | HIT | ERROR`; re-screen when TTL expires or before PAY when stale.

## 6. Interfaces

Internal `screen(org_id, address, chain) → ScreeningResult`; `encrypt(value, cls)` / `decrypt`; structlog processors. API: `GET /orgs/{o}/payees/{id}/screenings` (OWN, ADM, Auditor).

## 7. Flows

Payee proposal → screen → CLEAR → Owner may register (M03). Before each PAY (validator, M08): latest screening ≤ 24 h old? CLEAR → pass; stale → refresh synchronously (timeout 5 s); HIT or ERROR → BLOCK `SCREENING_HIT` / `DATA_MISSING` (fail closed, BR-085).

The execution caller runs `screen_plan_before_pay()` before policy validation. It screens
each PAY step's destination with the plan chain id, then sets `screening_hit` and
`screening_clear` in `ValidationContext`. `screening_clear` defaults to false, so a
missing screening result blocks with `DATA_MISSING`; a fresh or refreshed HIT blocks
with `SCREENING_HIT`. No PAY executor is currently wired in the repository, so this is
the integration seam that future execution code must call before `validate_plan()`.

## 8. Algorithms

- Fixture list: a sample of public sanctions-list addresses (labelled source and date) + team test entries; exact checksum-insensitive match.
- Redaction processor patterns: emails, 0x-signatures (130+ hex), bearer tokens, JWTs, private-key-like hex (64 hex), document text fields by key name. Addresses and tx hashes are not redacted.

## 9. Configuration

Screening TTL 24 h; provider `fixture` in M1; encryption key from Docker secret `field_key`; redaction on in all environments.

The API exposes the screening adapter through `app.state.screening_service` for
payee-registration and pre-PAY callers. `screen(org_id, address, chain_id)` persists each
result with its `chain_id` and provider, and reuses a CLEAR/HIT record for 24 hours
only for the same address, chain and provider; a reused result is also recorded for
the requesting payee so its screening history is complete. Address matching ignores
case and checksum (`0x`/`0X` or bare hex). The provider call has a 5-second timeout
(M14-D7). A timeout or provider error (`ScreeningProviderError`, network errors) is
logged and persisted as ERROR without a cache lifetime; `require_clear()` raises
`DATA_MISSING` for ERROR and `SCREENING_HIT` for HIT (fail closed, BR-085). Invalid
input (address, `chain_id <= 0`, a naive clock) raises instead of being recorded.

The fixture provider reads the `screening_lists` table (TEST DATA rows seeded by
migration `20261013_0009`, including a sample from the
[OFAC SDN-list update on 2026-03-12](https://ofac.treasury.gov/recent-actions/20260312))
and is only used when `TP_ENVIRONMENT` is `local`, `test` or `demo`. In any other
environment no real provider exists yet, so screening fails closed (every check is
ERROR → `DATA_MISSING`) and startup logs `screening_provider_unconfigured`.
The fixture is not a live sanctions list and must not be used for real screening.

The `field_key` secret contains a base64-encoded 32-byte key. Services load it from
`/run/secrets/field_key` by default; managed environments may inject
`TP_FIELD_ENCRYPTION_KEY` or configure `TP_FIELD_ENCRYPTION_KEY_FILE`. Encrypted
columns store a `tpenc:v1` AES-256-GCM envelope. Callers bind the table/column (and,
where available, tenant id) as encryption context so ciphertext cannot be moved to a
different field. Missing/invalid keys, unknown envelope versions, wrong context and
authentication failures all fail closed. Key material must never be stored in the DB
or logged.

## 10. Security

Fail closed on provider errors; Confidential columns unreadable in raw dumps; log scan test in CI; no PII in EAS receipts or events.

## 11. Failure scenarios

Provider down → registrations blocked, PAY blocked unless a fresh CLEAR exists; key missing at startup → api refuses to start.

## 12. Test plan

Listed address → HIT; provider error → callers fail closed; payee listed after registration → next plan BLOCK (CMP-002); log scan for emails/signatures; raw DB dump shows ciphertext for Confidential columns.

## 13. Tickets

CMP-001 → CMP-003 → CMP-002. Later CMP-L01…L04.

## 14. Decisions

| ID | Decision |
|---|---|
| M14-D1 | Fixture provider with TEST DATA labels in M1; adapter for commercial providers. |
| M14-D2 | Screen at registration and before each PAY; TTL 24 h. |
| M14-D3 | Fail closed on ERROR. |
| M14-D4 | Four data classes; Confidential encrypted at field level. |
| M14-D5 | Redaction processors on in all environments. |
| M14-D6 | Fixture contains a labelled sample of public sanctions addresses. |
| M14-D7 | Synchronous refresh before PAY with 5 s timeout. |
| M14-D8 | Addresses and tx hashes are not redacted (needed for audit). |
| M14-D9 | Encryption key from Docker secret; rotation is Later. |

## 15. Retention and deletion (CMP-L03)

Retention is disabled until an organization has a `retention_policies` row with
`invite_retention_days` set. The period starts when an invitation expires. An
organization legal hold overrides deletion, and policy changes serialize with the
deletion worker through a row lock. Administrators must set a period that satisfies
their applicable legal minimum; the application does not invent a jurisdictional
default. The period is limited to 0-36500 days (database check and validation).
A failure in one organization is logged and does not stop the others; the command
then exits non-zero. A dry run takes no write locks. A real run also locks the
organization's audit head, which every audit writer holds until commit, so an
audit entry cannot reference an invitation between the check and the deletion.
The audit reference check is a text search over the organization's audit rows; an
indexed structured reference is a follow-up that needs an audit schema change.
Use `configure_policy()` in the same transaction as the authorized policy
change. A `None` period disables scheduled deletion.

Run `python -m treasurypilot_api.compliance.retention` to preview a bounded batch;
pass `--execute` to delete it. Schedule that command under an operational identity
with database access. Each deleted invitation leaves a `deletion_receipts` row with
only a SHA-256 digest of its random UUID, a record type and deletion timestamp.
The digest is never computed from email, a name, or a token. The worker skips an
invitation referenced by the immutable audit log, because deleting the source
cannot remove personal data from that hash chain; email matches ignore case. Those records require a separate
legal review before a broader erasure workflow is enabled. Session and magic-link
retention are separate follow-up scopes because they are user-wide rather than
organization-scoped; no policy here silently deletes them.

The original one-day CMP-L03 estimate covers only the invitation slice (about half
a day). Follow-up work is estimated at another 2–3 days: user-wide session and
magic-link retention, subject-level deletion requests and holds, and a policy for
financial records and immutable audit evidence after their storage models land.
Until those slices are designed and implemented, CMP-L03 remains open.
