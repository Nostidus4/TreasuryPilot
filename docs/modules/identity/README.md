# M01 · Identity & Access (`api`)

**Status:** Detailed — decisions finalized by the tech lead under the project lead's delegation (2026-10-11) · **Path:** `docs/modules/identity/` · **Code:** `services/api/.../identity/` · **Epic:** `[EPIC] M01 · Identity & Access`
**ADRs:** ADR-009 (authentication) · **Decisions:** M01-D1 … M01-D12 (§14)

---

## 1. Purpose and boundaries

M01 answers **who is this person, which organization are they acting for, what may they do, and which wallet proves their signing authority**. App login never grants on-chain power: signing roles act only through linked wallets (BR-006).

| In scope (M1) | Out of scope |
|---|---|
| Magic-link login, sessions, CSRF, rate limits | MFA, SSO, SCIM (Later: IDN-L01…L03) |
| SIWE wallet linking (EOA + ERC-1271) | Owner keys (never held, BR-092) |
| Organizations, onboarding checklist, settings (solo mode, auto-match) | Billing (M18) |
| Memberships, 8 roles, invites, last-admin/owner guards | |
| RBAC dependencies, tenant isolation (404 for non-members) | |
| Maker-checker service and solo mode | |

## 2. Features, requirements and rules

F-001 (FR-001–003), F-002 (FR-004–006, BR-006), F-003 (FR-007, FR-009), F-004 (FR-008, FR-010–013, BR-093), F-005 (FR-014–015, BR-005); Later F-006/F-007 (FR-016–017).

## 3. Concepts and roles

| Role | Can | Cannot |
|---|---|---|
| **OrgAdmin** | members, roles, org settings except solo mode, treasury creation (with Owner) | sign approvals/governance unless also Owner/Approver |
| **Owner** | sign Safe governance (mandate, payees, exceptions, resume, revoke, cancel), solo mode, fee policy | approve requests they created (maker-checker) |
| **Approver** | sign `PaymentApproval`, ack flags, reject/request changes, on-chain `cancelRequest` | create governance |
| **Operator** | create/edit requests, upload, CSV, propose payees, run-now, review actions routed to them | approve |
| **Finance** | reconciliation, exports, fee acceptance, discrepancy | approve, governance |
| **Guardian** | pause (backend + Guardian Safe) | resume, anything else |
| **Auditor** | read-only everything incl. audit log and evidence bundles | any write |
| **PlatformAdmin** | platform operations (M18); no customer data by default | sign or move funds (BR-094) |

A user can hold several roles. Signer roles (Owner, Approver, Guardian) are **inactive** until a wallet is linked (FR-012). Owner in the app = a user whose linked wallet is an owner of Safe T (checked on-chain at link time and periodically).

## 4. Data model (DATA_MODEL §2.1)

`users`, `sessions` (idle 30 min, absolute 12 h), `magic_links` (hashed, single use, 15 min), `wallet_links` (unique active address), `siwe_nonces` (single use, 10 min), `organizations` (+ `settings` jsonb: solo_mode, auto_match, display_tz), `memberships` (roles[]), `invites` (hashed token, 7 days). Additional: `role_events` (append-only audit of role changes).

## 5. State

Invite: `Pending → Accepted | Expired | Revoked`. Session: `Active → Expired | Revoked`. Wallet link: `Linked → Unlinked` (unlink refused while the user is the only linked signer for a role that has pending items).

## 6. Interfaces (API_SPEC §1)

| Method | Endpoint | Perm | Errors |
|---|---|---|---|
| POST | `/auth/magic-link` | public, rate-limited (5/15 min per email, 20/15 min per IP) | 429 `RATE_LIMITED` with `Retry-After` = seconds left in the fixed 15-min window (1–900); 503 `AUTH_UNAVAILABLE` with `Retry-After: 30` |
| POST | `/auth/magic-link/verify` | public, rate-limited (20/15 min per IP); returns `{user, csrfToken}` | 400 `TOKEN_INVALID`, 410 `TOKEN_EXPIRED`, 429 `RATE_LIMITED` with `Retry-After` = seconds left in the fixed 15-min window (1–900); 503 `AUTH_UNAVAILABLE` with `Retry-After: 30` |
| POST | `/auth/logout` · GET `/me` | auth | |
| GET | `/auth/siwe/nonce` · POST `/me/wallets` · DELETE `/me/wallets/{a}` | auth | `SIWE_INVALID`, `ADDRESS_LINKED_ELSEWHERE`, `SIGNER_ROLE_REQUIRES_WALLET` |
| POST | `/orgs` · GET `/orgs/{o}` · PATCH `/orgs/{o}/settings` | auth / ANY / ADM (solo: OWN) | 403 |
| GET/POST | `/orgs/{o}/members`, `/orgs/{o}/invites` · POST `/invites/{token}/accept` | ADM | `ALREADY_MEMBER`, `INVITE_EXPIRED` |
| PATCH/DELETE | `/orgs/{o}/members/{u}` | ADM | `LAST_ADMIN`, `LAST_OWNER` |

SIWE message: domain = app host, `chainId` = treasury chain (11155111), statement "Link this wallet to TreasuryPilot", nonce single use, expiry 10 min, clock skew ± 2 min.

## 7. Flows

Sign-in: email → link (Resend; console locally) → verify → session cookie (httpOnly, Secure, SameSite=Lax) + CSRF token. Organization creation inserts the creator's `OrgAdmin` membership in the same transaction. The current onboarding response computes active member count, whether any member has an active wallet, whether a treasury exists, and whether its module address has been recorded from persisted data. Onboarding checklist: members → wallet linked → treasury → module enabled → mandate Active → payee Active → first invoice; computed from data, not stored flags.

## 8. Algorithms

- **RBAC:** FastAPI dependencies `require_member(org)` (non-member → **404**) and `require_role(*roles)` (member without role → 403); repositories always filter by `org_id`. An automated test enumerates every org-scoped route and calls it as a non-member.
- **Maker-checker:** `approver ∉ {created_by, last_edited_by}` unless `solo_mode` (Owner-only toggle), then the approval and audit entry carry `solo_mode = true`.
- **Owner check:** at link time and every hour, compare the user's linked addresses with Safe T owners; mismatch removes the effective Owner capability (role stays but shows "not an on-chain owner").

## 9. Configuration

Session idle 30 min / absolute 12 h; magic link 15 min; invite 7 days; SIWE nonce 10 min; rate limits per §6.

Deployed API instances require `DATABASE_URL`, a high-entropy `TP_SESSION_SECRET`
(at least 32 bytes), an HTTPS `TP_MAGIC_LINK_BASE_URL`, and
`TP_RESEND_API_KEY` / `TP_RESEND_FROM_EMAIL`. The `local` environment uses the
console delivery adapter and prints the one-time URL intentionally; every other
`TP_ENVIRONMENT` value (including `test`) is treated as deployed and never falls
back to console delivery, the fixed local session secret or an in-process rate
limiter (`TP_REDIS_URL` is required).

## 10. Security

Hashed tokens; single-use nonces; CSRF on mutations; 404 for non-members; audit for role and wallet changes; no passwords stored in M1 (magic link only); email enumeration avoided (same response for unknown emails).

## 11. Failure scenarios

Email provider down → the link is sent after the 202 response, so a failed send invalidates that link and is logged; the caller still gets 202 (no account enumeration) and requests a new link; Redis down → rate limiter fails closed for auth endpoints; nonce store down → linking refused.

## 12. Test plan

Unit: token lifecycle, SIWE verification (EOA + ERC-1271 mock), maker-checker matrix. Integration: cross-tenant route enumeration; last admin/owner guards; rate limits. Security: CSRF, cookie flags.

## 13. Tickets

IDN-001 → IDN-002 → IDN-003 → IDN-004 → IDN-005 → IDN-006 → IDN-008 → IDN-007. Later IDN-L01…L03.

### IDN-L01 foundation (partial)

The API exposes POST `/v1/me/mfa/totp/enrollment`, POST
`/v1/me/mfa/totp/confirm`, and POST `/v1/me/mfa/step-up`. All three require
an authenticated session and CSRF token. Enrollment presents the TOTP seed once,
expires after ten minutes, and becomes active only after a valid code. Confirmation
returns ten one-use recovery codes once; only keyed hashes are stored. TOTP seeds
are encrypted at rest with a key derived from `TP_SESSION_SECRET`; rotating that
secret requires an MFA seed migration or reenrollment plan. Verification permits
one adjacent 30-second time step for clock drift and persists the last accepted
counter to reject replay. Five attempts per 15 minutes per account are allowed;
the limiter fails closed. A successful TOTP or recovery verification marks only
the current session as stepped up for five minutes. The
`require_recent_mfa` FastAPI dependency is the guard for sensitive handlers.

IDN-L01 remains open: WebAuthn enrollment and attaching that guard to approve,
exception and mandate edit handlers are still required. Those handlers do not
exist on `main` yet.

## 14. Decisions

| ID | Decision |
|---|---|
| M01-D1 | Magic-link only in M1 (no passwords). |
| M01-D2 | Server-side sessions; idle 30 min, absolute 12 h. |
| M01-D3 | Non-members get 404 on org routes. |
| M01-D4 | Eight roles; multiple per user; signer roles need a linked wallet. |
| M01-D5 | App Owner capability requires the linked wallet to be a Safe T owner on-chain. |
| M01-D6 | SIWE chainId = treasury chain; nonce 10 min; skew ± 2 min. |
| M01-D7 | Solo mode Owner-only, flagged and audited (OQ-07). |
| M01-D8 | Rate limits per §6; fail closed if Redis is down. |
| M01-D9 | Invites expire after 7 days. |
| M01-D10 | Same response for known/unknown emails (no enumeration). |
| M01-D11 | Unlinking the last signer wallet with pending signer items is refused. |
| M01-D12 | Email provider Resend; console in local. |
