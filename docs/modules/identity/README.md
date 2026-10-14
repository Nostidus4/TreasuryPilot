# M01 · Identity & Access (`api`)

**Status:** Detailed — decisions finalized by the tech lead under the project lead's delegation (2026-10-11) · **Path:** `docs/modules/identity/` · **Code:** `services/api/.../identity/` · **Epic:** `[EPIC] M01 · Identity & Access`
**ADRs:** ADR-009 (authentication) · **Decisions:** M01-D1 … M01-D12 (§14)

---

## 1. Purpose and boundaries

M01 answers **who is this person, which organization are they acting for, what may they do, and which wallet proves their signing authority**. App login never grants on-chain power: signing roles act only through linked wallets (BR-006).

| In scope (M1) | Out of scope |
|---|---|
| Magic-link login, sessions, CSRF, rate limits, OIDC SSO | SAML and complete SCIM provisioning (Later: IDN-L03) |
| TOTP and WebAuthn second factors, recovery codes, step-up (IDN-L01) | |
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

`users`, `sessions` (idle 30 min, absolute 12 h), `magic_links` (hashed, single use, 15 min), `wallet_links` (unique active address), `siwe_nonces` (single use, 10 min), `organizations` (+ `settings` jsonb: solo_mode, auto_match, display_tz), `memberships` (roles[]), `invites` (hashed token, 7 days). Additional: `role_events` (append-only audit of role changes), `oidc_identities` (issuer/subject binding to a user), `mfa_factors` (TOTP secret as a field-encryption envelope, or a WebAuthn credential id and P-256 key, with the last accepted TOTP step and signature counter), `mfa_recovery_codes` (hashed, single use), and `sessions.step_up_at`.

## 5. State

Invite: `Pending → Accepted | Expired | Revoked`. Session: `Active → Expired | Revoked`. Wallet link: `Linked → Unlinked` (unlink refused while the user is the only linked signer for a role that has pending items).

## 6. Interfaces (API_SPEC §1)

| Method | Endpoint | Perm | Errors |
|---|---|---|---|
| POST | `/auth/magic-link` | public, rate-limited (5/15 min per email, 20/15 min per IP) | 429 `RATE_LIMITED` with `Retry-After` = seconds left in the fixed 15-min window (1–900); 503 `AUTH_UNAVAILABLE` with `Retry-After: 30` |
| POST | `/auth/magic-link/verify` | public, rate-limited (20/15 min per IP); returns `{user, csrfToken}` | 400 `TOKEN_INVALID`, 410 `TOKEN_EXPIRED`, 429 `RATE_LIMITED` with `Retry-After` = seconds left in the fixed 15-min window (1–900); 503 `AUTH_UNAVAILABLE` with `Retry-After: 30` |
| POST | `/auth/logout` · GET `/me` | auth | |
| GET | `/auth/siwe/nonce` | auth; returns domain, Sepolia chain ID, and single-use 10-minute nonce; spent/expired nonces are deleted on issue and at most 5 may be open per user | 429 `RATE_LIMITED` |
| POST | `/me/wallets` | auth + CSRF; verifies EOA or ERC-1271 signature and writes a `wallet.linked` audit record in every org the user is an active member of at that time (a user with no membership has no org log; the link is kept in `wallet_links`) | `SIWE_INVALID` (also a malformed signature), `ADDRESS_LINKED_ELSEWHERE`, `WALLET_ALREADY_LINKED` |
| DELETE | `/me/wallets/{a}` | auth + CSRF; writes an audit record | `WALLET_NOT_FOUND` |
| POST | `/orgs` · GET `/orgs/{o}` · PATCH `/orgs/{o}/settings` | auth / ANY / ADM (solo: OWN) | 403 |
| GET/POST | `/orgs/{o}/members`, `/orgs/{o}/invites` · POST `/invites/{token}/accept` | ADM | `ALREADY_MEMBER`, `INVITE_EXPIRED` |
| PATCH/DELETE | `/orgs/{o}/members/{u}` | ADM | `LAST_ADMIN`, `LAST_OWNER` |
| GET | `/scim/v2/Users` · `/scim/v2/Users/{id}` | configured SCIM bearer token; tenant-scoped existing user resources; list supports `userName eq "email"` | 401, 404, 503 |
| PATCH | `/scim/v2/Users/{id}` | configured SCIM bearer token; only `replace active=false` | 400, 404, 409 last OrgAdmin/Owner |
| GET/POST | `/scim/v2/Groups` · GET `/scim/v2/Groups/{id}` | configured SCIM bearer token; only configured group names; list supports `displayName eq "name"` | 400, 404, 409 duplicate group |
| PATCH/DELETE | `/scim/v2/Groups/{id}` | configured SCIM bearer token; membership add/remove or group delete; existing active tenant users only | 400, 404 |
| GET | `/me/mfa` | auth; enrolled factors and unused recovery codes | |
| POST | `/me/mfa/totp` · `/me/mfa/totp/{f}/confirm` | auth + CSRF; returns an `otpauth://` URI, confirm takes the 6-digit code and returns recovery codes with the first factor | `MFA_CODE_INVALID`, `MFA_UNAVAILABLE` (no field encryption key) |
| POST | `/me/mfa/webauthn/challenge` · `/me/mfa/webauthn` | auth + CSRF; `register` or `assert` challenge, then register an ES256 credential (`none` attestation) | `MFA_REGISTRATION_INVALID`, `MFA_ORIGIN_INVALID`, `MFA_CREDENTIAL_EXISTS` |
| POST | `/me/mfa/step-up` | auth + CSRF; one of `code`, `recoveryCode`, `webauthn` assertion; stamps the session; 20 attempts/15 min per user | `MFA_CODE_INVALID`, 429 `RATE_LIMITED` |
| POST/DELETE | `/me/mfa/recovery-codes` (regenerate) · `/me/mfa/{f}` | auth + CSRF + fresh step-up | `STEP_UP_REQUIRED` |

SIWE message: domain = configured app origin, `chainId` = treasury chain (11155111), statement "Link this wallet to TreasuryPilot", nonce single use, expiry 10 min, clock skew ± 2 min. `/me` includes each membership's `ownerIsOnchain` and `ownerCheckedAt` values; `signerRolesActive` is true only when the membership holds Owner, Approver or Guardian and a wallet is linked.

The opt-in SCIM slice exposes tenant-scoped user reads and `PATCH active=false` at `/scim/v2/Users`. It suspends the user's membership in one configured organization, revokes that organization's scoped sessions, and records a system audit event in the same transaction. Optional `/Groups` resources are restricted to names in `TP_SCIM_GROUP_ROLE_MAP`; their assignments grant only configured `Operator`, `Finance`, or `Auditor` roles to existing active members in that organization. Manual, OIDC, and SCIM role grants are stored separately and the effective membership roles are their union, so removing one source preserves the others. Existing grants remain manual during schema upgrade; an OIDC sync can attribute legacy work roles only in the configured OIDC organization. Identity links never reclassify grants in another organization. Losing the final effective role suspends the membership and revokes scoped sessions. SCIM cannot create or reactivate users, set role names directly, assign privileged roles, or nest groups. SAML and the remaining SCIM provisioning scope are still unimplemented. An organization's last active OrgAdmin or Owner cannot be deprovisioned.

## 7. Flows

Sign-in: email → link (Resend; console locally) → verify → session cookie (httpOnly, Secure, SameSite=Lax) + CSRF token. Enterprise sign-in uses OIDC authorization code flow with PKCE, signed state, nonce and verified RS256 ID tokens. Each callback provisions a user and applies configured IDP group roles to one configured organization. SSO sessions expire after five minutes; callbacks request a fresh IDP login. A callback with no mapped groups removes OIDC-managed roles; the membership is suspended only if no manual or SCIM grant remains, and that login is rejected. Organization creation inserts the creator's `OrgAdmin` membership in the same transaction. The current onboarding response computes active member count, whether any member has an active wallet, whether a treasury exists, and whether its module address has been recorded from persisted data. Onboarding checklist: members → wallet linked → treasury → module enabled → mandate Active → payee Active → first invoice; computed from data, not stored flags.

## 8. Algorithms

- **Step-up (FR-016):** `require_role(..., step_up=True)` also rejects with 403 `STEP_UP_REQUIRED` unless `sessions.step_up_at` is less than 10 minutes old. It guards invoice approval, governance transaction and module-deploy creation (which carry exception grants and mandate activation), and mandate draft create, clone and discard. A user with no enrolled factor cannot pass it. Adding, removing or resetting factors needs a fresh step-up once any factor is enrolled; confirming the first TOTP code or key stamps the session. TOTP is RFC 6238 (SHA-1, 6 digits, 30 s, plus or minus one step) and a time step is accepted once. WebAuthn challenges are HMAC-signed with a 5-minute expiry (not stored, see the `shortcut:` note in `mfa.py`) and a signature counter that does not advance is rejected.

- **RBAC:** FastAPI dependencies `require_member(org)` (non-member → **404**) and `require_role(*roles)` (member without role → 403); repositories always filter by `org_id`. An automated test enumerates every org-scoped route and calls it as a non-member.
- **Maker-checker:** `assert_maker_checker(request, user_id=..., organization=...)` rejects `approver ∈ {created_by, last_edited_by}` with 409 `MAKER_CHECKER` unless persisted `solo_mode` is enabled. It returns `solo_mode = true` only when solo mode actually allowed self-approval. The Owner-only setting API verifies current Safe T ownership. Invoice approval handlers in dependent #123/#124 must call the helper and persist its decision on the approval and audit event; handler wiring is not part of IDN-008.
- **Owner check:** compare the user's linked addresses with Safe T owners at link/unlink time, before every Owner-only write (solo mode, or `autoMatch` by an Owner who is not OrgAdmin) with no cache, and on `/me` at most hourly as a best-effort display refresh (an RPC outage keeps the cached value). Mismatch leaves the role label in place but sets `ownerIsOnchain = false`; Owner-only settings fail with `OWNER_NOT_ONCHAIN`. A membership without the Owner role always has `ownerIsOnchain = false`.

## 9. Configuration

Session idle 30 min / absolute 12 h; magic link 15 min; invite 7 days; SIWE nonce 10 min; rate limits per §6.

Deployed API instances require `DATABASE_URL`, a high-entropy `TP_SESSION_SECRET`
(at least 32 bytes), an HTTPS `TP_MAGIC_LINK_BASE_URL`, and
`TP_RESEND_API_KEY` / `TP_RESEND_FROM_EMAIL`. OIDC is opt-in and requires `TP_OIDC_ISSUER`, `TP_OIDC_CLIENT_ID`, `TP_OIDC_CLIENT_SECRET`, `TP_OIDC_REDIRECT_URI`, and `TP_OIDC_ORGANIZATION_ID`; `TP_OIDC_GROUP_ROLE_MAP` is a JSON object from provider group names to arrays of `Operator`, `Finance`, or `Auditor` roles. Callback URI must exactly match the provider registration. The `local` environment uses the
console delivery adapter and prints the one-time URL intentionally; every other
`TP_ENVIRONMENT` value (including `test`) is treated as deployed and never falls
back to console delivery, the fixed local session secret or an in-process rate
limiter (`TP_REDIS_URL` is required).

SCIM is disabled unless both `TP_SCIM_BEARER_TOKEN` (at least 32 bytes) and
`TP_SCIM_ORGANIZATION_ID` (a UUID) are configured. The bearer token is compared
in constant time and is never logged or returned. Optional
`TP_SCIM_GROUP_ROLE_MAP` is a JSON object from exact SCIM group display names to
non-empty arrays containing only `Operator`, `Finance`, and `Auditor`; names are
unique ignoring case. Groups are disabled when this map is empty. Removing a
configured group name deletes its persisted SCIM group and assignment records
at API startup, then recomputes affected role grants. This integration supports
deprovisioning existing memberships and configured group membership only; it
does not create or reactivate users.

## 10. Security

SCIM is limited to one configured organization and does not disable a person's account in other organizations. Group mappings are server controlled and can grant only Operator, Finance, or Auditor; SCIM requests cannot change a mapping, assign a privileged role, create/reactivate an account, or nest another group.

Hashed tokens; single-use nonces; CSRF on mutations; 404 for non-members; audit for role and wallet changes; no passwords stored; email enumeration avoided (same response for unknown emails). OIDC trusts only the configured issuer, verified email claims, and mapped non-privileged roles. Discovery and key endpoints must use HTTPS except loopback local development; endpoint redirects are rejected.

## 11. Failure scenarios

Email provider down → the link is sent after the 202 response, so a failed send invalidates that link and is logged; the caller still gets 202 (no account enumeration) and requests a new link; Redis down → rate limiter fails closed for auth endpoints; nonce store down → linking refused.

## 12. Test plan

Unit: token lifecycle, SIWE verification (EOA + ERC-1271 mock), maker-checker matrix, SCIM bearer auth, user deactivation, group allowlist, and membership patch validation. Integration: cross-tenant route enumeration; last admin/owner guards; SCIM membership suspension, role-source union, group-removal session revocation and audit; rate limits. Security: CSRF, cookie flags.

## 13. Tickets

IDN-001 → IDN-002 → IDN-003 → IDN-004 → IDN-005 → IDN-006 → IDN-008 → IDN-007. Later IDN-L01…L03. The SCIM deprovisioning slice is partial IDN-L03 coverage; SAML and the remaining SCIM provisioning scope are still open.

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
| M01-D13 | Second factors are a step-up on sensitive routes, not a login gate; a step-up lasts 10 minutes per session. |
