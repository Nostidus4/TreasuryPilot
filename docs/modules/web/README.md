# M16 · Web Application (`apps/web`)

**Status:** Detailed — decisions finalized by the tech lead under the project lead's delegation (2026-10-11) · **Path:** `docs/modules/web/` · **Code:** `apps/web` · **Epic:** `[EPIC] M16 · Web Application`
**ADRs:** ADR-010 (REST + OpenAPI client + SSE), ADR-013 (React + Vite + wagmi) · **Decisions:** M16-D1 … M16-D14 (§14)

---

## 1. Purpose and boundaries

The web app is where **people decide and sign**, and where they **see exactly what the agent is doing and why**. It holds no secrets and no business rules: every number and decision comes from the API; every signature is made in the user's own wallet over data the server built.

| In scope (M1) | Out of scope |
|---|---|
| All screens below, wallet connection, SIWE, EIP-712 signing (approvals, SafeTx), Safe `execTransaction` sending | Mobile apps; i18n beyond English (strings externalized for vi/zh Later) |
| Live updates via SSE | Admin console (Later) |
| Accessibility AA on core flows, 390 px layouts for approval and notifications | |

## 2. Features, requirements and rules

F-130 (FR-915), F-131 (FR-916, FR-313), F-132 (FR-917, BR-057), F-133 (FR-918), F-134 (FR-919), F-135 (FR-920); UI for F-001–F-005, F-010–F-026, F-030–F-038, F-066, F-090, F-100, F-140/141, F-058; NFR-UX-01…05.

## 3. Screen map

| Route | Screen | Roles | Ticket |
|---|---|---|---|
| `/login`, `/verify` | Magic link | public | WEB-002 |
| `/orgs`, `/o/:org/onboarding` | Org select/create, checklist | all | WEB-002 |
| `/me/wallets` | Wallet link (SIWE) | all | WEB-003 |
| `/o/:org/treasuries/new` | Setup wizard: chain/asset → Safes → module governance tx → coverage → Guardian Safe | OWN, ADM | WEB-004 |
| `/o/:org/t/:t` | Dashboard: balances vs buffer/target, budgets, coverage, mandate, queues, runway, activity, banners | all | WEB-010, WEB-019, WEB-021 |
| `/o/:org/t/:t/mandate` | Mandate editor: form, summary, diff (looser/stricter), create governance tx | OWN (edit), all (view) | WEB-005 |
| `/o/:org/t/:t/payees` | Vendors & payees: propose, screening, OOB verification, registration tx, cooling countdown | OPR, OWN | WEB-006 |
| `/o/:org/governance` | Governance signing inbox: decoded calls, summary, sign SafeTx, execute | OWN | WEB-025 |
| `/o/:org/requests`, `/new`, `/:r` | Requests list, manual form, detail (revisions, flags, approvals, timeline, cancel / cancel on-chain) | OPR, all | WEB-007 |
| `/o/:org/requests/upload`, `/import` | Upload + extraction review (side-by-side), CSV import | OPR | WEB-008, WEB-020 |
| `/o/:org/approvals` | Approval inbox: document, fields, vendor history diff, flags + ack, typed data, sign | APR | WEB-009 |
| `/o/:org/t/:t/plans/:p` | Plan card + Why panel + live timeline | all | WEB-011, WEB-012 |
| `/o/:org/review` | Review & exception console (routed actions, exception grant tx, fee acceptance) | per role | WEB-013, WEB-024 |
| `/o/:org/reconciliation` | Reconciliation table, match/discrepancy, exports, evidence download, EAS link | FIN | WEB-014 |
| `/o/:org/t/:t/settings/fees` | Fee policy proposal → Accept | OWN | WEB-024 |
| `/o/:org/members` | Members, roles, invites, solo mode | ADM, OWN | WEB-017 |
| `/o/:org/metrics` | Operations metrics and savings vs B1 | OWN, FIN | WEB-018 |
| Copilot panel (global) | Chat with citations, "AI explanation" label | all | WEB-016 |
| Notification bell (global) | Unread, deep links, live | all | WEB-015 |

## 4. Client architecture

React 18 + Vite + TypeScript; React Router; TanStack Query (server state; SSE events invalidate queries by entity); Tailwind + shadcn/ui; wagmi v2 + viem + RainbowKit (chain = Sepolia; local = Anvil); generated OpenAPI client (`make openapi`); Recharts; Playwright. No global client store beyond auth/org context and UI preferences.

## 5. State and status wording (NFR-UX-04)

| Backend state | UI wording |
|---|---|
| Submitted / Pending | "Sent — waiting for the network" |
| Confirmed (not yet verified) | "Confirmed on-chain — verifying" |
| Verified / Paid | "Paid · 3 confirmations" (+ "Final" when finalized) |
| Unknown | "Checking the chain — no new payment will be sent" |
| Pause requested / effective | "Pausing…" / "Paused on-chain" |
| Coverage PARTIAL ack | "Protected mode off — another module can move funds" |
| AI text | always inside a box labelled **AI explanation**; validator reasons labelled **Policy decision** |

Never "safe", "done" or "guaranteed" without a verified state. Amounts always show symbol + network; TEST assets have a badge.

## 6. Wallet interactions

| Action | Method | Data source |
|---|---|---|
| Link wallet | `signMessage` (SIWE) | server nonce |
| Approve request | `signTypedData` (PaymentApproval) | `GET approval-typed-data` (server-built; displayed fields = signed object) |
| Sign governance | `signTypedData` (SafeTx) | `GET governance-txs/{g}` |
| Execute governance | `sendTransaction` to the Safe (`execTransaction`) | `GET exec-call` |
| Cancel on-chain | `sendTransaction` `cancelRequest` | `GET cancel-tx` |
| Guardian pause (no sentinel) | `sendTransaction` to Guardian Safe | `/pause` response |

Wrong network → blocking prompt to switch. Wallet rejection → no state change, toast.

## 7. Key flows

Approval: inbox → detail → ack HIGH flags (note) → "Review what you sign" (typed data table) → sign → POST approve → Approved. Governance: notification → inbox item → decoded calls + diff → sign (n/threshold) → last owner Execute → status from SSE. Execution: plan card → timeline steps update live via SSE with explorer links.

## 8. Rules in the client

None authoritative. Client-side validation only mirrors API errors for UX (decimals, required fields). Amount input converts display ↔ base units with the asset's decimals using integer math (bigint), never floats.

## 9. Configuration

`VITE_API_URL`, `VITE_CHAIN_ID`, `VITE_WALLETCONNECT_ID`, explorer URL from `/chains`. CSP: `default-src 'self'`; connect-src API + RPC + WalletConnect; no inline scripts.

## 10. Security

Typed data displayed = object passed to the wallet (unit-tested); no secrets in the bundle; CSRF token header on mutations; cookies httpOnly; CSP; dependency audit in CI; untrusted invoice text rendered as text (no HTML).

## 11. Failure scenarios

API down → error state with retry; SSE drop → auto-reconnect with Last-Event-ID and 10 s org-wide polling; an open execution detail refreshes every 2 s whenever SSE is not connected (including before the first connect or without EventSource) to meet WEB-012's status-change target; while SSE is connected the detail relies on `plan` / `operation` events, so it can go stale if the backend does not emit them (tracked with the backend dependency below); wallet rejection → no change; stale ETag → "Someone changed this, reload".

**Execution API dependency:** the plan screen calls `GET /v1/orgs/{orgId}/plans/{planId}` and `GET /v1/orgs/{orgId}/treasuries/{treasuryId}/plans`; run-now calls `POST /v1/orgs/{orgId}/treasuries/{treasuryId}/run-now`. In this repository revision these routes exist only in the web MSW handlers: `services/api` has no plans/operations router or execution read model. The notifications SSE endpoint is implemented, and its `plan` / `operation` events can invalidate the detail query, but they do not supply plan-step state. The live screen therefore needs those API routes and durable `plan` / `operation` domain events from the execution backend before it can show real Anvil execution data.

## 12. Test plan

Component tests for typed-data display and amount conversion; Playwright happy path (WEB-023) with a mock wallet on Anvil; axe on approve/review/dashboard; 390 px checks; status wording checklist.

## 13. Tickets

WEB-001 → WEB-002 → WEB-003 → WEB-004 → WEB-025 → WEB-005 → WEB-006 → WEB-007 → WEB-008 → WEB-009 → WEB-010 → WEB-011 → WEB-012 → WEB-013 → WEB-019 → WEB-014 → WEB-024 → WEB-015 → WEB-016 → WEB-017 → WEB-018 → WEB-020 → WEB-021 → WEB-022 → WEB-023.

## 14. Decisions

| ID | Decision |
|---|---|
| M16-D1 | Server builds every signed object; the UI shows exactly that object. |
| M16-D2 | Governance signing happens in-app (WEB-025); Safe{Wallet} link optional. |
| M16-D3 | Exceptions are granted through governance txs, not EIP-712 (WEB-013 revised). |
| M16-D4 | Status wording table §5 is mandatory copy. |
| M16-D5 | AI text always labelled; validator reasons authoritative. |
| M16-D6 | bigint amount conversion; no floats. |
| M16-D7 | SSE invalidates TanStack Query caches; polling fallback 10 s. |
| M16-D8 | English only in M1, strings externalized. |
| M16-D9 | Chain Sepolia (Anvil locally); wrong-network blocking prompt. |
| M16-D10 | CSP strict, no inline scripts. |
| M16-D11 | Fee policy screen shows the system proposal; Owner accepts or picks a preset. |
| M16-D12 | Cancel on-chain banner persists until confirmed. |
| M16-D13 | Guardian pause falls back to a wallet transaction when no sentinel is configured. |
| M16-D14 | Recharts for metrics; no extra chart library. |

## 15. v0.3 changes (ADR-019)

- Dashboard **position card**: Safe USDC, aUSDC (Aave), pool liquidity, RequiredSafeReserve breakdown (PaymentReserve, floor, holds), AvailableForSupply, supply APY (labelled testnet).
- Approval inbox shows **early vs standard** options.
- **Borrow proposal view** (D6): withdraw vs borrow cost, health factor before/after, reason; "no transaction without owner authorization".
- **Tickets:** WEB-010, WEB-009 revised; WEB-026 position card, WEB-027 borrow proposal view (new).
