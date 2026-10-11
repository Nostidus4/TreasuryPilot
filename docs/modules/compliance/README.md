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

Internal `screen(address, chain) → ScreeningResult`; `encrypt(value, cls)` / `decrypt`; structlog processors. API: `GET /orgs/{o}/payees/{id}/screenings` (OWN, ADM, Auditor).

## 7. Flows

Payee proposal → screen → CLEAR → Owner may register (M03). Before each PAY (validator, M08): latest screening ≤ 24 h old? CLEAR → pass; stale → refresh synchronously (timeout 5 s); HIT or ERROR → BLOCK `SCREENING_HIT` / `DATA_MISSING` (fail closed, BR-085).

## 8. Algorithms

- Fixture list: a sample of public sanctions-list addresses (labelled source and date) + team test entries; exact checksum-insensitive match.
- Redaction processor patterns: emails, 0x-signatures (130+ hex), bearer tokens, JWTs, private-key-like hex (64 hex), document text fields by key name. Addresses and tx hashes are not redacted.

## 9. Configuration

Screening TTL 24 h; provider `fixture` in M1; encryption key from Docker secret `field_key`; redaction on in all environments.

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
