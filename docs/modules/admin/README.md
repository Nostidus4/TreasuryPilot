# M18 · Platform Admin & Billing (Later)

**Status:** Detailed — decisions finalized by the tech lead under the project lead's delegation (2026-10-11) · **Path:** `docs/modules/admin/` · **Epic:** `[EPIC] M18 · Platform Admin & Billing`
**Decisions:** M18-D1 … M18-D6 (§14)

---

## 1. Purpose and boundaries

M18 is how **TreasuryPilot the company** operates the platform: tenant management, support access with consent, usage metering and subscription billing. In M1 only platform configuration exists (files validated at startup, M02-D8); everything else is Later.

**Hard boundary (BR-094, BR-091):** PlatformAdmin can never sign, approve, move customer funds or deduct fees from a customer treasury.

| M1 | Later |
|---|---|
| Config + deployments manifest validated at startup (TRS-002) | Admin console (ADM-L01), usage metering (ADM-L02), subscriptions and invoicing (ADM-L03) |

## 2. Features

F-150 (FR-924), F-151 (FR-925, M1 via TRS-002), F-152 (FR-926).

## 3. Concepts

| Term | Definition |
|---|---|
| **PlatformAdmin** | Staff role outside any org; sees tenant metadata only. |
| **Support access** | Time-boxed, read-only access to one org, granted by an OrgAdmin, fully audited. |
| **Usage** | Paid requests count and paid volume per org per month (from events). |

## 4. Data model (Later)

`organizations.platform_status` (active/suspended), `platform_admin_events` (staff tenant operations), `support_grants` (org_id, staff_user, scope=read, expires_at, granted_by), `usage_monthly` (org_id, month, paid_count, paid_volume), `billing_*` (plans, subscriptions, invoices — paid by card/bank outside customer treasuries).

## 5. State

Tenant `Active ⇄ Suspended` (suspension stops planning; never touches funds). Support grant `Requested → Granted → Expired | Revoked`.

## 6. Interfaces (Later)

`/admin/tenants`, `/admin/tenants/{id}/health`, `/admin/tenants/{id}/suspend`, `/admin/tenants/{id}/support`, `/v1/orgs/{o}/support-grants`, `/admin/usage`, `/orgs/{o}/billing`. Admin API is a separate router with a staff bearer credential and socket-peer IP allowlist. It fails closed when any required credential or allowlist setting is missing. Tenant admins grant a named staff user read-only support access for 1–72 hours and can revoke it; staff can read only the tenant metadata and health summary while the grant is active. Grant and revoke consent is written to the tenant audit chain, and each support read is recorded in the append-only platform admin event log. No support session grants write access or impersonates a tenant member. The IP allowlist matches the TCP peer address, so behind a reverse proxy it sees the proxy address; run the admin API without a proxy hop or add a trusted-proxy setting first. `suspend` is idempotent (one event per transition); an unsuspend route is not yet implemented. The suspension status still needs to be enforced by planning routes and workers.

## 7–8. Flows and algorithms

Support access: OrgAdmin or Owner grants a named staff user 24 h read-only access (maximum 72 h) → staff reads the bounded support summary while the grant is active → grant consent is appended to the tenant audit chain and each support read is appended to `platform_admin_events`. Metering: `POST /admin/usage/{YYYY-MM}/recompute` rebuilds `usage_monthly` from `request_status_events` (each request counts once, in the UTC month of its first Paid event, at its integer base-unit amount); `GET /admin/usage?month=` reads it. Recompute is idempotent. `reconciliation_lines` (EXTERNAL_EXPENSE) is not metered yet.

## 9. Configuration

Pricing model to be decided (Later); suspension policy; support grant max 72 h.

## 10. Security

Admin router isolated; no signer access; support sessions read-only and audited; suspension cannot pause on-chain (only Owners/Guardians can).

## 11. Failure scenarios

Invalid platform config → services refuse to start (M1).

## 12. Test plan (Later)

Static route test confirms admin exposes no signer or fund-moving operations; support grant role/expiry/revocation and audit tests; usage reconciles with the event store.

## 13. Tickets

ADM-L01 → ADM-L02 → ADM-L03 (all Later). M1 config: TRS-002.

## 14. Decisions

| ID | Decision |
|---|---|
| M18-D1 | No admin console in M1; config files only. |
| M18-D2 | PlatformAdmin can never sign or move funds (BR-094). |
| M18-D3 | Support access only by OrgAdmin grant, read-only, ≤ 72 h, audited. |
| M18-D4 | Fees are never deducted from customer treasuries (BR-091). |
| M18-D5 | Suspension stops planning only; on-chain pause stays with Owners/Guardians. |
| M18-D6 | Pricing model is a Later business decision. |
