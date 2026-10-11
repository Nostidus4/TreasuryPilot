# TreasuryPilot: Feature Inventory & Specifications

**Status:** Draft for gate G1 · **Date:** 2026-10-10
**Read with:** `PROJECT_OVERVIEW.md`, `FUNCTIONAL_REQUIREMENTS.md`, `BUSINESS_RULES.md`, `OPEN_QUESTIONS.md`.

## Conventions

| Field | Meaning |
|---|---|
| **ID** | `F-NNN`. Stable; never reused. |
| **Phase** | `M1` = Milestone 1 (FinTechathon build). `Later` = full product, after M1. Nothing is dropped. |
| **Priority** | Applies only to M1: `P0` must have · `P1` should have · `P2` nice to have. Later features carry no priority yet. |
| **Source** | Traceability tag. `UC/R/AT/AD/D/O` = `TreasuryPilot.md` v0.2. `T/S/N` = the score-improvement plan. `GA` = mechanism adopted from GuardianAI. `FJ` = FigJam board. `Q` = planning decision (`docs/decisions-log.md`). `NEW` = added by BA analysis. |
| **Module** | Tentative owning module. Finalized in Phase 4. |
| **AI responsibility** | Which of **Observe / Recommend / Decide / Act / Verify / Recover** the AI performs. "Decide" always means *choosing among options already validated by deterministic code*. |

Roles used below (Q13): **Owner**, **Approver**, **Operator**, **Finance**, **Guardian**, **OrgAdmin**, **Auditor**, **PlatformAdmin**, plus the system actors **Agent** (AI planner), **PolicyEngine**, **Executor**, **Contract**.

---

## 1. Inventory

| ID | Feature | Group | Phase | Prio | Source |
|---|---|---|---|---|---|
| F-001 | Account sign-up & login | Identity | M1 | P0 | NEW, Q3 |
| F-002 | Wallet linking via Sign-In With Ethereum | Identity | M1 | P0 | NEW, UC-01 |
| F-003 | Organization creation & onboarding | Identity | M1 | P0 | Q3, Q21 |
| F-004 | Member invitation & role management | User mgmt | M1 | P1 | Q13 |
| F-005 | Maker-checker separation | User mgmt | M1 | P0 | Q13 |
| F-006 | MFA & session security | Identity | Later | – | NEW |
| F-007 | Enterprise SSO (OIDC/SAML) | Identity | Later | – | NEW |
| F-010 | Treasury creation | Treasury setup | M1 | P0 | D4, Q21 |
| F-011 | Safe smart-account connection | Treasury setup | M1 | P0 | Domain §6.2, FJ |
| F-012 | Module enablement & coverage verification | Treasury setup | M1 | P0 | GA p.20, AT35 |
| F-013 | Asset registry | Treasury setup | M1 | P0 | Domain §2 |
| F-014 | Multi-treasury & multi-chain | Treasury setup | Later | – | Q2, Q21 |
| F-015 | Multiple stablecoins per treasury | Treasury setup | Later | – | Q2 |
| F-020 | Mandate configuration | Mandate | M1 | P0 | Domain §4.1–4.2 |
| F-021 | Mandate activation, versioning & lifecycle | Mandate | M1 | P0 | Domain §6.2, UC-01 |
| F-022 | Payee registry with screening & cooling period | Mandate | M1 | P0 | R2, S2 |
| F-023 | Spending limits & treasury-wide UTC daily counters | Mandate | M1 | P0 | R3, Domain §5.1, O3 |
| F-024 | Minimum buffer & target balance protection | Mandate | M1 | P0 | R4, Domain §3 |
| F-025 | One-time exception | Mandate | M1 | P1 | D3, UC-06, Domain §6.1 |
| F-026 | Pause, resume & revoke | Mandate | M1 | P0 | UC-05, R9 |
| F-027 | Circuit breaker (auto-pause) | Security | M1 | P2 | S7 |
| F-028 | On-chain reserve & execution-hold enforcement | Mandate | Later | – | Domain §5.2, Q2 |
| F-029 | Threshold-based multi-level approval (n-of-m) | Mandate | Later | – | Q14 |
| F-030 | Manual invoice entry | Invoices | M1 | P0 | UC-01, Q15 |
| F-031 | PDF/image invoice upload & AI extraction | Invoices / AI | M1 | P0 | N1, Q15 |
| F-032 | CSV bulk import | Invoices | M1 | P1 | Q15 |
| F-033 | Email-forwarding inbox | Invoices | Later | – | Q15 |
| F-034 | Inbound API / webhook intake | Integration | Later | – | Q15 |
| F-035 | Payment-terms extraction | AI | M1 | P0 | N1 |
| F-036 | Anomaly & fraud-signal detection | AI / Security | M1 | P0 | N1, AT-09 |
| F-037 | Duplicate-invoice fingerprint | Invoices / Security | M1 | P0 | S3, UC-04 |
| F-038 | Invoice approval via EIP-712 signature | Invoices | M1 | P0 | R1, UC-01 |
| F-039 | Payment request lifecycle & state machine | Core | M1 | P0 | Use-Case §5 |
| F-040 | Recurring payment schedules | Invoices | Later | – | D5, Q2 |
| F-041 | Fiat-denominated invoices with FX & depeg checks | Financial | Later | – | Q20 |
| F-050 | Chain state reader & fresh snapshots | Data | M1 | P0 | UC-02, Autonomy §3 |
| F-051 | Liquidity calculator | Financial | M1 | P0 | Domain §3 |
| F-052 | Terms-aware deterministic scheduler | Financial | M1 | P0 | N2, O8 |
| F-053 | AI plan proposal & explanation | AI | M1 | P0 | N2, Autonomy §2 |
| F-054 | Rule-based fallback planner | AI | M1 | P0 | D6, AD-02 |
| F-055 | Policy validation (ALLOW / NEEDS_APPROVAL / BLOCK) | Core | M1 | P0 | Autonomy §4, FJ |
| F-056 | Plan attestation | Security | M1 | P1 | GA p.21–22 |
| F-057 | AI exception-request drafting | AI | M1 | P1 | N2 |
| F-058 | Liquidity forecast & runway | Financial | M1 | P2 | T8 |
| F-059 | Refill from other operational wallets | Financial | Later | – | D5, Q2 |
| F-060 | Deadline-driven autonomous trigger | Core | M1 | P0 | T1 |
| F-061 | Sequential executor & signer service | Execution | M1 | P0 | UC-02, S8 |
| F-062 | REFILL execution | Execution | M1 | P0 | D4, UC-02 |
| F-063 | PAY execution | Execution | M1 | P0 | D4, UC-02 |
| F-064 | SWAP via allowlisted adapter (labelled test router) | Execution | M1 | P2 | AT-04, R5 |
| F-065 | Real DEX/aggregator swap with verified quotes | Execution | Later | – | Domain §5.3, Q2 |
| F-066 | Gas management | Execution | M1 | P1 | R7, Domain §5.4, O6 |
| F-067 | Cross-chain bridge | Execution | Later | – | D5, Q2 |
| F-068 | Idle-cash management on Aave V3 (SUPPLY / WITHDRAW) | Liquidity | M1 | P0 | v0.3, ADR-019 |
| F-069 | Borrow proposal (cost vs withdraw, health factor) | Liquidity | M1 | P1 | v0.3, ADR-019 |
| F-079 | Owner-authorized BORROW / REPAY execution | Liquidity | M1 | P2 | v0.3, ADR-019 |
| F-070 | Transaction tracking & confirmation | Verification | M1 | P0 | UC-03 |
| F-071 | Post-condition verification | Verification | M1 | P0 | UC-02 step 4, GA p.14 |
| F-072 | Reconciliation (Paid vs Matched) | Verification | M1 | P0 | UC-03 |
| F-073 | Reconciliation export (CSV / journal) | Verification | M1 | P1 | T5 |
| F-074 | On-chain payment attestation | Verification | M1 | P2 | N6 |
| F-075 | ERP / accounting integrations | Integration | Later | – | D5, Q2 |
| F-080 | Unknown-state recovery (no double pay) | Recovery | M1 | P0 | R8, AT-06, T3 |
| F-081 | Partial-completion handling | Recovery | M1 | P0 | AT-07 |
| F-082 | Needs-review queue & exception routing | Recovery | M1 | P0 | UC-04, FJ |
| F-083 | Idempotent retry policy | Recovery | M1 | P0 | UC-04 step 3 |
| F-090 | Treasury Copilot (what-if) | AI | M1 | P1 | N4 |
| F-091 | Untrusted-data boundary & prompt-injection defense | AI / Security | M1 | P0 | AT-09, AD-01, S5 |
| F-092 | AI evaluation harness (B1 vs B2) | AI | M1 | P0 | N3, Autonomy §6 |
| F-093 | AI decision log | AI / Audit | M1 | P0 | Autonomy §5 |
| F-094 | Model adapter & routing | AI | M1 | P1 | NEW |
| F-100 | In-app notifications | Notification | M1 | P1 | Q16 |
| F-101 | Telegram notifications with deep links | Notification | M1 | P2 | N7, Q16 |
| F-102 | Email notifications | Notification | Later | – | Q16 |
| F-103 | Outbound webhooks | Integration | Later | – | Q16 |
| F-104 | Slack / Lark / WeCom notifications | Notification | Later | – | Q16 |
| F-105 | Notification preferences | Notification | Later | – | NEW |
| F-110 | Payee sanctions / blocklist screening | Compliance | M1 | P1 | S6, Q17 |
| F-111 | KYB onboarding | Compliance | Later | – | Q17 |
| F-112 | Travel Rule support | Compliance | Later | – | Q17 |
| F-113 | Data minimization | Compliance | M1 | P0 | Use-Case §2, S6 |
| F-114 | Data retention & residency policies | Compliance | Later | – | Q17 |
| F-120 | Hash-chained audit log & on-chain events | Audit | M1 | P0 | S6, GA p.14 |
| F-121 | Evidence bundle export | Audit | M1 | P0 | GA p.39, AT §6 |
| F-122 | Coverage & uncertainty labelling | Audit | M1 | P1 | GA p.5 |
| F-130 | Treasury dashboard | UX | M1 | P0 | N5 |
| F-131 | Approval inbox with diff & flags | UX | M1 | P0 | N5, N1 |
| F-132 | Plan cards & live execution timeline | UX | M1 | P0 | N5 |
| F-133 | Reconciliation view | UX | M1 | P0 | UC-03 |
| F-134 | Mandate & payee management UI | UX | M1 | P0 | UC-01 |
| F-135 | Exception & review console | UX | M1 | P0 | UC-04, UC-06 |
| F-140 | Operational metrics | Analytics | M1 | P1 | T6, AT §6 |
| F-141 | Savings report | Analytics | M1 | P1 | N3 |
| F-142 | System observability | Monitoring | M1 | P1 | NEW |
| F-150 | Platform admin: tenant management | Admin | Later | – | Q13 |
| F-151 | Platform configuration (chains, RPC, assets) | Admin | M1 | P1 | O5 |
| F-152 | Billing & subscriptions | Admin | Later | – | Q22 |
| F-160 | One-command local environment & seeded scenarios | DevEx | M1 | P1 | T7 |
| F-161 | CI pipeline | DevEx | M1 | P1 | T7 |
| F-162 | Scenario runner & demo runbook | DevEx | M1 | P1 | GA p.14, p.41 |
| F-163 | Security test suites | Security | M1 | P0 | S1, S5 |
| F-164 | Reliability run harness | Quality | M1 | P1 | T6 |

**Totals:** 99 features. M1: 76 (P0 51 · P1 20 · P2 5). Later: 23. Every feature in the inventory has a full specification in §3.

## 2. Non-goals (never in scope; enforced as Business Rules)

| ID | Non-goal | Rule |
|---|---|---|
| NG-1 | Speculative trading or market-making | BR-090 |
| NG-2 | Yield optimization, staking, lending/borrowing | BR-090 |
| NG-3 | Portfolio management or asset allocation advice | BR-090 |
| NG-4 | Custody of customer funds by TreasuryPilot | BR-091 |
| NG-5 | Paying any obligation without a valid human approval | BR-001 |
| NG-6 | The agent autonomously creating obligations or purchasing services | BR-002 |
| NG-7 | Reversing confirmed transactions, or promising to | BR-062 |

---

## 3. Feature specifications

### 3.1 Identity & User Management

#### F-001 · Account sign-up & login
`M1 · P0 · Source: NEW, Q3 · Module: identity`
- **Description:** Users create an account and sign in to the web app with an email address (magic link or password). The account is separate from any wallet.
- **Problem solved:** A multi-tenant product needs human identities that are independent of keys. Finance and Auditor users may not hold wallets at all.
- **Users:** All human roles.
- **Trigger:** First visit, or an invitation link.
- **Input:** Email, password or magic-link token, display name.
- **Business logic:** Verify email ownership → create the user → issue a session. Credentials are never stored in plaintext.
- **Output:** An authenticated session; a user record.
- **Happy path:** Enter email → receive link → click → signed in → land on org selection.
- **Alternative flows:** An invited user signs up through the invitation link and is auto-joined to the org (F-004).
- **Edge cases:** Expired link → resend. Email already registered → login instead. Too many attempts → rate-limit and lockout. Email provider down → show retry; no account is created half-way.
- **Permissions:** Public endpoint, rate-limited.
- **AI responsibility:** None.
- **Human responsibility:** The user proves ownership of the email.
- **Acceptance criteria:** A user can sign up, sign in and sign out. Sessions expire. Brute force is rate-limited. No plaintext secrets appear in the DB or logs.

#### F-002 · Wallet linking via Sign-In With Ethereum (SIWE)
`M1 · P0 · Source: NEW, UC-01 · Module: identity`
- **Description:** A user proves control of an EVM address by signing a SIWE (EIP-4361) message. The address is linked to their account and is needed for signer roles (Owner, Approver, Guardian).
- **Problem solved:** Approvals and exceptions must be signed by keys the contract recognizes. Logging in to the app is not the same as on-chain authority (GA p.11).
- **Users:** Owner, Approver, Guardian.
- **Trigger:** Role assignment that requires a key, or the user linking a wallet voluntarily.
- **Input:** Wallet address, SIWE signature, nonce, chainId.
- **Business logic:** Verify the signature, nonce freshness, domain and chainId → store the address against the user. One address maps to only one user.
- **Output:** A linked wallet record.
- **Happy path:** Connect wallet → sign the SIWE message → address shown as linked.
- **Alternative flows:** Unlink and relink (audited). Multiple addresses per user.
- **Edge cases:** Replayed nonce → reject. Address already linked to another user → reject. Contract-wallet signature → verify via ERC-1271.
- **Permissions:** The authenticated user, for their own account only.
- **AI responsibility:** None.
- **Human responsibility:** Sign with their own key. Keys never leave the user's wallet.
- **Acceptance criteria:** A linked address is required before a signer role can be used. Replay is rejected. ERC-1271 is supported. All link and unlink events are audited.

#### F-003 · Organization creation & onboarding
`M1 · P0 · Source: Q3, Q21 · Module: identity`
- **Description:** A user creates an organization (tenant) and becomes its first OrgAdmin. A guided onboarding covers members, treasury, mandate and payees.
- **Problem solved:** Multi-tenant isolation; a clear starting point for J1.
- **Users:** The first user, who becomes OrgAdmin.
- **Trigger:** After the first login with no organization.
- **Input:** Org name, legal entity name (optional in M1), country, base timezone (display only; limits use UTC).
- **Business logic:** Create the org → assign OrgAdmin → start a checklist (invite → treasury → mandate → payees → first invoice).
- **Output:** An org record and an onboarding checklist state.
- **Happy path:** Create the org → see the checklist → complete the steps.
- **Alternative flows:** Join an existing org through an invite instead.
- **Edge cases:** Duplicate org name (allowed; IDs are unique). The user abandons onboarding (state persists).
- **Permissions:** Any authenticated user can create an org.
- **AI responsibility:** None.
- **Human responsibility:** Provide accurate org data.
- **Acceptance criteria:** Data of org A is never visible to members of org B (tenant isolation is tested). Checklist progress persists.

#### F-004 · Member invitation & role management
`M1 · P1 · Source: Q13 · Module: identity`
- **Description:** OrgAdmin invites members by email and assigns one or more of the 8 roles.
- **Problem solved:** Separation of duties and least privilege.
- **Users:** OrgAdmin.
- **Trigger:** Admin action.
- **Input:** Email, roles.
- **Business logic:** Create the invite (expiring) → on acceptance, bind the roles. Signer roles stay inactive until a wallet is linked (F-002). Role changes are audited. Removing the last OrgAdmin or the last Owner is blocked.
- **Output:** Membership with roles.
- **Happy path:** Invite → accept → roles active.
- **Alternative flows:** Revoke an invite. Change roles. Remove a member.
- **Edge cases:** Invite to an existing member → update roles instead. Expired invite. Removing a member who has pending approvals → their approvals stay valid (signed), but new ones are blocked.
- **Permissions:** OrgAdmin only. Owner role assignment additionally requires the Owner to link the Safe owner address.
- **AI responsibility:** None.
- **Human responsibility:** OrgAdmin chooses the roles.
- **Acceptance criteria:** RBAC checks run on every API call. Role changes are audited. The last Admin or Owner cannot be removed.

#### F-005 · Maker-checker separation
`M1 · P0 · Source: Q13 · Module: identity / invoices`
- **Description:** The user who created or edited an invoice cannot approve it. A one-time exception cannot be granted by the person who requested it, when they are different roles.
- **Problem solved:** Prevents a single person from creating and approving a payment.
- **Users:** Operator, Approver, Owner.
- **Trigger:** An approval or exception attempt.
- **Input:** Invoice creator/editor history, approver identity.
- **Business logic:** If approver ∈ {creator, last editor} → reject. The rule is enforced in the backend; for M1 the contract additionally checks that the approval signer is in the approver set.
- **Output:** Allow or deny the approval.
- **Happy path:** The operator creates, and a different person approves.
- **Alternative flows:** In a single-person org (one founder), the owner may enable "solo mode". It is explicitly flagged in the UI and audit log as **no maker-checker** (see OQ-07).
- **Edge cases:** The creator gains the Approver role later → still blocked for invoices they created.
- **Permissions:** System-enforced.
- **AI responsibility:** None. AI-extracted drafts count as created by the operator who confirmed them.
- **Human responsibility:** Configure roles.
- **Acceptance criteria:** A test shows that a creator who tries to approve is rejected. Solo mode is visible on every affected record.

#### F-006 · MFA & session security
`Later · Source: NEW · Module: identity`
- **Description:** TOTP or WebAuthn second factor. Device and session list. Forced re-authentication for sensitive actions.
- **Problem solved:** Account takeover leading to approvals or policy changes.
- **Users:** All, and mandatory for signer roles.
- **Trigger:** Login, and sensitive actions (approve, grant exception, edit mandate).
- **Input:** Second-factor proof.
- **Business logic:** Step-up authentication within N minutes for sensitive actions.
- **Output:** A verified session.
- **Happy path:** Login → second factor → session.
- **Alternative flows:** Recovery codes.
- **Edge cases:** Lost device → admin-assisted reset with audit.
- **Permissions:** Self-service; admin can reset.
- **AI responsibility:** None.
- **Human responsibility:** Keep factors safe.
- **Acceptance criteria:** Sensitive endpoints reject sessions without a fresh second factor.

#### F-007 · Enterprise SSO (OIDC / SAML)
`Later · Source: NEW · Module: identity`
- **Description:** Login through the company identity provider, with optional SCIM provisioning.
- **Problem solved:** Enterprise onboarding and offboarding.
- **Users:** Enterprise organizations.
- **Trigger:** Login.
- **Input:** IdP assertion.
- **Business logic:** Map IdP groups to roles. Signer roles still require a wallet link.
- **Output:** Session.
- **Happy path:** Redirect → IdP → session.
- **Alternative flows:** Just-in-time provisioning.
- **Edge cases:** User deprovisioned in the IdP → sessions revoked.
- **Permissions:** OrgAdmin configures it.
- **AI responsibility:** None.
- **Human responsibility:** IdP administration.
- **Acceptance criteria:** Login works with at least one OIDC provider. Deprovisioning revokes access within 5 minutes.

### 3.2 Treasury & Wallet Setup

#### F-010 · Treasury creation
`M1 · P0 · Source: D4, Q21 · Module: treasury`
- **Description:** Within an org, create a treasury bound to one chain and one payment stablecoin, with one source wallet `T` and N operational wallets (M1: `O1`, `O2`).
- **Problem solved:** Defines the scope of the money the agent manages.
- **Users:** Owner, OrgAdmin.
- **Trigger:** Onboarding step, or Admin action.
- **Input:** Chain (from F-151), stablecoin asset (F-013), wallet addresses and their roles (T / operational), wallet labels.
- **Business logic:** Validate chain/asset support → validate that the addresses are Safes on that chain (F-011) → store. Wallet roles are immutable once a mandate references them (a new treasury version is required to change them).
- **Output:** Treasury record.
- **Happy path:** Choose chain and asset → add T, O1, O2 → saved.
- **Alternative flows:** Create the Safes from within the app (F-011).
- **Edge cases:** The same address used twice → reject. An address on the wrong chain → reject. An EOA instead of a Safe → reject in protected mode (BR-023).
- **Permissions:** Owner or OrgAdmin.
- **AI responsibility:** None.
- **Human responsibility:** Choose wallets correctly.
- **Acceptance criteria:** A treasury cannot be created with unsupported chains or assets, duplicate wallets, or non-Safe wallets.

#### F-011 · Safe smart-account connection / provisioning
`M1 · P0 · Source: Domain §6.2, FJ · Module: treasury / contracts`
- **Description:** Connect existing Safe accounts, or deploy new ones (owner = the Owner's address, threshold as configured). Read owners, threshold, modules and guard.
- **Problem solved:** Enforcement is only real if every wallet in scope supports the control path. A backend check in front of an EOA is not enforcement (Domain §6.2).
- **Users:** Owner.
- **Trigger:** Treasury setup.
- **Input:** Safe address, or deployment parameters.
- **Business logic:** Read the on-chain configuration → store a snapshot → flag any differences on later reads.
- **Output:** Safe records with a configuration snapshot.
- **Happy path:** Paste the Safe address → configuration read → confirmed.
- **Alternative flows:** Deploy a new Safe through a transaction the Owner signs.
- **Edge cases:** Owner set or threshold changes later → coverage warning (F-012). RPC failure → show "unknown", not "ok".
- **Permissions:** Owner.
- **AI responsibility:** None.
- **Human responsibility:** The Owner signs the deployment and configuration transactions.
- **Acceptance criteria:** The configuration snapshot matches the chain. Changes are detected within one polling interval.

#### F-012 · Module enablement & coverage verification
`M1 · P0 · Source: GA p.20, GA AT35 · Module: contracts / treasury`
- **Description:** The Owner enables `TreasuryPilotModule` on each Safe. The system verifies the full list of enabled modules and guards. If any other module could move funds outside the mandate, protected mode is marked **partial coverage** and autonomous execution is suspended until the Owner acknowledges it.
- **Problem solved:** A second module with arbitrary execution would bypass the mandate (GA p.20).
- **Users:** Owner.
- **Trigger:** Setup, and every configuration change detected.
- **Input:** Enabled modules list, guard address, module bytecode hash.
- **Business logic:** Compare the module list to an allowlist of known module hashes → compute coverage = COMPLETE / PARTIAL / UNKNOWN (F-122).
- **Output:** A coverage status per Safe.
- **Happy path:** Enable the module → coverage COMPLETE → execution enabled.
- **Alternative flows:** The Owner acknowledges PARTIAL coverage explicitly; this is audited and the UI shows a permanent banner.
- **Edge cases:** Module disabled by the Owner → execution stops. Module upgraded → requires re-verification.
- **Permissions:** Owner signs the enablement transaction.
- **AI responsibility:** None.
- **Human responsibility:** The Owner enables the module and acknowledges any partial coverage.
- **Acceptance criteria:** An extra unknown module turns coverage to PARTIAL and blocks the autonomous trigger (test).

#### F-013 · Asset registry
`M1 · P0 · Source: Domain §2 · Module: treasury`
- **Description:** A registry of assets identified by `(chainId, contractAddress)`, with verified decimals. Native gas has its own identifier. The name "USDC" is display-only.
- **Problem solved:** Prevents token impersonation and decimal errors.
- **Users:** PlatformAdmin (global), Owner (selects).
- **Trigger:** Configuration.
- **Input:** chainId, address, symbol, decimals, issuer label, "test asset" flag.
- **Business logic:** Decimals are read on-chain and must match. All amounts are integers in base units.
- **Output:** Asset entries.
- **Happy path:** Admin adds the asset → it is verified → selectable.
- **Alternative flows:** Test assets carry a visible "TEST" label everywhere.
- **Edge cases:** A fee-on-transfer or rebasing token → not supported (rejected by an adapter check).
- **Permissions:** PlatformAdmin writes; others read.
- **AI responsibility:** None.
- **Human responsibility:** PlatformAdmin verifies the issuer address.
- **Acceptance criteria:** No floating-point amounts anywhere in the code. Decimal mismatches are rejected. Test assets are always labelled.

#### F-014 · Multi-treasury & multi-chain
`Later · Source: Q2, Q21 · Module: treasury`
- **Description:** An org can run several treasuries, each on its own chain, with a consolidated view.
- **Problem solved:** Real businesses operate across chains.
- **Users:** Owner, Finance.
- **Trigger:** Treasury creation.
- **Input:** As for F-010, per chain.
- **Business logic:** Limits and counters stay per treasury. The consolidated view never sums different assets without a pricing source.
- **Output:** Multiple treasuries.
- **Happy path:** Add a second treasury on another chain.
- **Alternative flows:** —
- **Edge cases:** Same address on two chains = two distinct wallets.
- **Permissions:** Owner.
- **AI responsibility:** Observe and recommend across treasuries (Later).
- **Human responsibility:** Configure each mandate.
- **Acceptance criteria:** Two treasuries on two chains operate independently, and their counters are isolated.

#### F-015 · Multiple stablecoins per treasury
`Later · Source: Q2 · Module: treasury / financial`
- **Description:** A treasury holds more than one stablecoin (e.g., USDC and USDT), with limits per asset.
- **Problem solved:** Vendors may require different stablecoins.
- **Users:** Owner.
- **Trigger:** Configuration.
- **Input:** Additional assets.
- **Business logic:** Limits are per asset. Swaps between stablecoins require F-065. 1:1 parity is never assumed.
- **Output:** Multi-asset treasury.
- **Happy path:** Add USDT → set its limits.
- **Alternative flows:** —
- **Edge cases:** Depeg → swaps blocked if the quote deviates beyond the threshold.
- **Permissions:** Owner.
- **AI responsibility:** Recommend the asset to use (Later).
- **Human responsibility:** Approve the asset list.
- **Acceptance criteria:** Limits are enforced independently per asset.

### 3.3 Mandate & Policy

#### F-020 · Mandate configuration
`M1 · P0 · Source: Domain §4.1–4.2 · Module: mandate`
- **Description:** The Owner defines the agent's delegated authority: allowed actions (`REFILL`, `PAY`, `SWAP`), wallets, refill paths (`T→O1`, `T→O2`), payees, per-request and daily limits per action and asset, minimum buffer and target per wallet and asset, swap pairs, router, max slippage, quote max age, gas funding cap, and validity window.
- **Problem solved:** Turns "trust the agent" into an explicit, enforceable, auditable grant (P2).
- **Users:** Owner. Finance can view.
- **Trigger:** Setup, or a policy change.
- **Input:** Mandate fields (Domain §4.1). Amounts are integers in base units.
- **Business logic:** Validate completeness (BR-014). Validate consistency, e.g. `target ≥ buffer`, refill paths within treasury wallets, payees present in the registry. Render a human-readable summary ("Agent may pay up to 2,000 USDC per invoice…") before signing.
- **Output:** A Draft mandate version.
- **Happy path:** Fill the form → review the summary → proceed to activation (F-021).
- **Alternative flows:** Clone the previous version and edit.
- **Edge cases:** Missing gas cap or router while SWAP is enabled → invalid. Limits of 0 → the action is effectively disabled (allowed, with a warning). Decimal input → converted using registry decimals; sub-unit precision is rejected.
- **Permissions:** Owner only.
- **AI responsibility:** None for creation. The Copilot (F-090) may *explain* a mandate on request; it cannot edit one.
- **Human responsibility:** The Owner decides every value.
- **Acceptance criteria:** An incomplete mandate cannot proceed to activation. The summary reflects exact base-unit values. No API exists that lets a non-Owner write a mandate.

#### F-021 · Mandate activation, versioning & lifecycle
`M1 · P0 · Source: Domain §6.2, UC-01 · Module: mandate / contracts`
- **Description:** Activation writes the mandate on-chain through an Owner-signed Safe transaction. Lifecycle: `Draft → PendingActivation → Active → (Paused) → Expired | Revoked | Superseded`. Every change creates a new version.
- **Problem solved:** Policy must exist where it is enforced. A database copy is only a cache (GA p.11).
- **Users:** Owner.
- **Trigger:** Owner activates or updates a mandate.
- **Input:** Draft version.
- **Business logic:** Build the Safe transaction → Owner signs → the system waits for the configured confirmations → reads back on-chain state → marks Active only if it matches (BR-015). A new version invalidates outstanding one-time exceptions (BR-016) and does not reset counters (BR-022).
- **Output:** Active mandate version (id, version, hash, on-chain reference).
- **Happy path:** Sign → confirmed → Active.
- **Alternative flows:** Expiry reached → Expired automatically (contract rejects calls). Revoke → F-026.
- **Edge cases:** Transaction pending for a long time → status shows "activation pending", and the old version stays in force. On-chain state differs from the draft → `Discrepancy`, not Active.
- **Permissions:** Owner signs.
- **AI responsibility:** None.
- **Human responsibility:** The Owner signs activation.
- **Acceptance criteria:** Execution never uses a version that is not confirmed on-chain. Version history is immutable and viewable. Counters persist across versions (test).

#### F-022 · Payee registry with screening & cooling period
`M1 · P0 · Source: R2, S2 · Module: mandate / compliance`
- **Description:** Payees are registered `(label, chain, address)` entries on the on-chain allowlist. A new or changed address becomes usable only after a **cooling period** (configurable, e.g. 24h; 5 minutes in demo) and only after passing screening (F-110).
- **Problem solved:** Vendor/BEC fraud. An attacker who changes an address in an invoice cannot get paid quickly, and the Owner has time to notice (P3).
- **Users:** Owner adds or changes payees. Operator can request a payee. Approver views.
- **Trigger:** New vendor, or a vendor address change.
- **Input:** Label, address, optional vendor reference data (name, contact) kept off-chain.
- **Business logic:** Screening → Owner-signed registration transaction with `activeFrom = now + coolingPeriod` → the contract rejects PAY to the payee before `activeFrom`. An address change = new payee entry + the old entry deactivated.
- **Output:** Payee entry with status `Screening → Cooling → Active → Deactivated`.
- **Happy path:** Add → screened clean → cooling → Active.
- **Alternative flows:** An Operator proposes a payee → the Owner reviews and signs.
- **Edge cases:** Screening hit → BLOCK, not registrable (BR-085). Screening provider unavailable → registration paused (fail closed). Same address registered twice → reject. Payment due before cooling ends → invoice waits; the scheduler reports it as an infeasible deadline.
- **Permissions:** Only the Owner can make a payee Active.
- **AI responsibility:** Observe (compares invoice addresses to registry history, F-036). Recommend ("this looks like an address change").
- **Human responsibility:** The Owner verifies the address out-of-band and signs.
- **Acceptance criteria:** PAY to a payee in cooling reverts on-chain (test). An address change always restarts cooling. Every change is audited.

#### F-023 · Spending limits & treasury-wide UTC daily counters
`M1 · P0 · Source: R3, Domain §5.1, O3 · Module: contracts / mandate`
- **Description:** Per-request and daily limits per action family (PAY, REFILL, SWAP-input) and per asset, enforced in the contract. Counters are keyed by `(treasury, action, asset, UTC day)`.
- **Problem solved:** Bounds the maximum loss and blocks split-to-evade attacks.
- **Users:** Owner configures. System enforces.
- **Trigger:** Every executed step.
- **Input:** Amount, action, asset, block timestamp.
- **Business logic:** `Day = floor(block.timestamp / 86400)`. Require `used + amount ≤ dailyLimit` and `amount ≤ perRequestLimit` (unless a valid exception exists, F-025). Increment only on success. Refill and pay budgets are separate (BR-023).
- **Output:** Allow or revert. Updated counters.
- **Happy path:** Within limits → executes → counter updated.
- **Alternative flows:** Over the per-request limit with an exception → allowed once.
- **Edge cases:** Pending across midnight → evaluated against the execution day (BR-026). Revert → no increment (BR-025). Splitting across O1/O2 or versions → still the same counter (BR-022).
- **Permissions:** System.
- **AI responsibility:** Observe the remaining budget (read-only) for planning.
- **Human responsibility:** The Owner sets the limits.
- **Acceptance criteria:** Fuzz/invariant test: the sum of successful PAY amounts per UTC day never exceeds the daily limit. Splitting across wallets or versions fails to evade the limits.

#### F-024 · Minimum buffer & target balance protection
`M1 · P0 · Source: R4, Domain §3 · Module: contracts / financial`
- **Description:** Each operational wallet keeps a minimum buffer that the agent must never breach. The target balance is a soft refill goal.
- **Problem solved:** Keeps a wallet able to operate and protects funds set aside for other uses.
- **Users:** Owner sets the values. System enforces.
- **Trigger:** Planning and execution of each PAY or REFILL.
- **Input:** Balance, buffer `F`, target `H` (`H ≥ F`).
- **Business logic:** The contract checks `balanceAfter ≥ F` for the paying wallet on PAY, and for the source T on REFILL (`F_T`). The planner refills toward `H` when possible, otherwise exactly the Shortage (BR-032, BR-033).
- **Output:** Allow or revert. Planner notices such as "target not reached".
- **Happy path:** Refill to target → pay → wallet at target.
- **Alternative flows:** Source can only cover the minimum → refill Shortage → pay → report that the target was not reached.
- **Edge cases:** Owner withdraws funds outside the module → state re-read before each step; the agent stops if a shortfall appears (BR-051). The native-token buffer is not guaranteed if that wallet pays gas directly (documented limitation).
- **Permissions:** Owner sets.
- **AI responsibility:** None in computing. It explains the outcome.
- **Human responsibility:** Set sensible buffers.
- **Acceptance criteria:** Invariant: no agent-path transaction leaves a wallet below its buffer. Domain §3.4 worked examples pass as unit tests.

#### F-025 · One-time exception
`M1 · P1 · Source: D3, UC-06, Domain §6.1 · Module: mandate / contracts`
- **Description:** For an approved invoice above the per-request cap, the Owner grants an exception bound to that exact request. It lifts only the per-request cap.
- **Problem solved:** Occasional large payments without loosening the general mandate.
- **Users:** Owner grants. Agent requests (F-057).
- **Trigger:** The validator returns `NEEDS_APPROVAL` because the per-request cap is exceeded and every other rule passes.
- **Input:** request_id, amount, payee, asset, paying wallet, chain, contract, mandate version, expiry, nonce.
- **Business logic:** EIP-712 grant by the Owner → verified by the contract at PAY → consumed atomically with the payment. Full amount counts toward the daily cap (BR-042). It cannot lift the daily cap, buffer, payee, asset, chain or expiry rules (BR-040).
- **Output:** Exception record (`Granted → Consumed | Expired | Invalidated`).
- **Happy path:** NEEDS_APPROVAL → drafted request → Owner signs → PAY succeeds once.
- **Alternative flows:** Owner rejects → the invoice stays `AwaitingAuthority` → Operator may cancel it.
- **Edge cases:** Replay against another request → revert. Mandate version changed → invalid. Daily cap would be exceeded → still BLOCK. Expired → invalid.
- **Permissions:** Owner only.
- **AI responsibility:** Recommend (drafts the justification). Never grants.
- **Human responsibility:** The Owner decides.
- **Acceptance criteria:** AT-11 passes: correct use once; replay, wrong version and over-daily cases are blocked.

#### F-026 · Pause, resume & revoke
`M1 · P0 · Source: UC-05, R9 · Module: mandate / contracts`
- **Description:** The Owner or Guardian pauses the agent (backend stops immediately; the contract rejects after confirmation). Only the Owner resumes. The Owner can revoke a mandate permanently.
- **Problem solved:** Emergency stop.
- **Users:** Owner, Guardian (pause only).
- **Trigger:** Manual action, or the circuit breaker (F-027).
- **Input:** Reason. Signed transaction.
- **Business logic:** On request, the backend sets a pause flag and stops submitting (BR-063). An on-chain pause transaction follows. The UI distinguishes "pause requested" from "pause effective". Pending transactions are shown; nothing is reversed (BR-062).
- **Output:** Mandate state Paused or Revoked.
- **Happy path:** Pause → backend halts → on-chain confirmed → PAY attempts revert.
- **Alternative flows:** Resume (Owner) → re-validates all queued requests before continuing.
- **Edge cases:** A transaction broadcast before the pause confirms may still execute → reported. Guardian tries to resume → rejected (BR-064).
- **Permissions:** Pause: Owner, Guardian. Resume and revoke: Owner.
- **AI responsibility:** None. The Agent stops planning.
- **Human responsibility:** Decide to pause or resume.
- **Acceptance criteria:** AT-08 passes. A Guardian resume reverts. A plan created before revoke cannot execute after it.

#### F-027 · Circuit breaker (auto-pause)
`M1 · P2 · Source: S7 · Module: execution / security`
- **Description:** Automatic backend pause when anomaly thresholds are crossed: e.g., at least 3 contract rejections in 10 minutes, the AI proposing out-of-mandate plans, a configuration-coverage drop, or unexpected balance changes.
- **Problem solved:** Limits damage from bugs or compromise between human checks.
- **Users:** System. Owner is notified.
- **Trigger:** Threshold crossed.
- **Input:** Event stream.
- **Business logic:** Evaluate rules → set the backend pause → notify (F-100/F-101) → optionally submit an on-chain pause via the Guardian key, if configured.
- **Output:** Paused state with reason codes.
- **Happy path:** Anomaly → auto-pause → Owner investigates → resumes.
- **Alternative flows:** Rule configured as "alert only".
- **Edge cases:** Flapping → cool-down before alerting again. False positive → Owner resumes; the event is recorded.
- **Permissions:** Owner configures thresholds and resumes.
- **AI responsibility:** None (deterministic rules).
- **Human responsibility:** Resume decision.
- **Acceptance criteria:** A test that injects 3 rejections causes a pause within one evaluation cycle.

#### F-028 · On-chain reserve & execution-hold enforcement
`Later · Source: Domain §5.2, Q2 · Module: contracts / financial`
- **Description:** Reservations (`R`) and execution holds (`L`) for registered obligations are stored and enforced on-chain, so other plans cannot spend money already committed.
- **Problem solved:** Concurrent obligations competing for the same funds (database holds are not hard protection).
- **Users:** System.
- **Trigger:** Approval (reserve) and execution start (hold).
- **Input:** Request, amount, wallet.
- **Business logic:** Domain §3.1 formulas on-chain. R→L transfer without double counting. Holds are released only on a known outcome.
- **Output:** On-chain reservation state.
- **Happy path:** Approve → reserve → execute → release.
- **Alternative flows:** Cancel → release the reserve.
- **Edge cases:** Timeout does not release a hold. Funding deficit → reported.
- **Permissions:** System via the module. The Owner can override by editing obligations.
- **AI responsibility:** Observe.
- **Human responsibility:** None beyond approvals.
- **Acceptance criteria:** Invariant: the sum of reservations and holds never exceeds the balance minus buffer on the agent path.

#### F-029 · Threshold-based multi-level approval (n-of-m)
`Later · Source: Q14 · Module: invoices / mandate`
- **Description:** The approval policy requires k-of-n approvers depending on amount bands (e.g., <1k: 1; 1–10k: 2; >10k: 2 + Owner).
- **Problem solved:** Enterprise internal controls.
- **Users:** Approvers, Owner.
- **Trigger:** Invoice approval.
- **Input:** Approval policy, signatures.
- **Business logic:** The contract verifies k distinct authorized signatures over the same typed data.
- **Output:** Approved once the threshold is met.
- **Happy path:** Two approvers sign → Approved.
- **Alternative flows:** One approver rejects → policy decides (veto or majority).
- **Edge cases:** Same signer twice → counted once. Approver removed mid-flow → their signature becomes invalid if the policy says so.
- **Permissions:** Owner configures the policy.
- **AI responsibility:** None.
- **Human responsibility:** Sign.
- **Acceptance criteria:** Amount band rules are enforced on-chain (tests per band).

### 3.4 Invoices & Obligations

#### F-030 · Manual invoice entry
`M1 · P0 · Source: UC-01, Q15 · Module: invoices`
- **Description:** The Operator creates a payment request with the fields: invoice reference, vendor/payee, asset, amount, paying wallet, due date, optional payment terms, and attachments.
- **Problem solved:** The baseline intake channel.
- **Users:** Operator.
- **Trigger:** A new invoice is received.
- **Input:** The fields above (base-unit amount computed from the display amount).
- **Business logic:** Validate schema → payee must exist (Active or Cooling) → asset must equal the treasury stablecoin (BR-073) → compute the fingerprint (F-037) → state `Draft`.
- **Output:** Draft request.
- **Happy path:** Fill the form → save → submit for approval (`AwaitingApproval`).
- **Alternative flows:** Unknown payee → "request payee" (F-022). Save as draft.
- **Edge cases:** Due date in the past → allowed but flagged. Duplicate fingerprint → warning that blocks submission until resolved (BR-071). Amount with too many decimals → rejected.
- **Permissions:** Operator, OrgAdmin.
- **AI responsibility:** None (manual channel). Anomaly checks (F-036) still run.
- **Human responsibility:** Enter accurate data.
- **Acceptance criteria:** Invalid inputs are rejected with field errors. Submitting moves the request to AwaitingApproval. The creator is recorded for maker-checker.

#### F-031 · PDF/image invoice upload & AI extraction
`M1 · P0 · Source: N1, Q15 · Module: invoices / agent`
- **Description:** Upload a PDF or image. The AI extracts structured fields and payment terms (F-035) and runs anomaly checks (F-036). The Operator reviews a side-by-side view (document ↔ extracted fields) and confirms.
- **Problem solved:** Manual data entry and missed terms.
- **Users:** Operator.
- **Trigger:** Upload.
- **Input:** File (≤ 10 MB; PDF, PNG, JPG).
- **Business logic:** Store the file privately → text extraction (OCR if needed) → LLM structured output into a strict schema → schema validation → each field carries a source span/page reference → injected instructions are ignored and flagged (F-091) → Draft.
- **Output:** Draft request with per-field provenance and flags.
- **Happy path:** Upload → fields prefilled → Operator corrects anything wrong → submit.
- **Alternative flows:** Extraction fails → fall back to manual entry with the document shown alongside.
- **Edge cases:** Multi-invoice PDF → split or reject (M1: reject with a message). Unreadable scan → manual. LLM timeout → manual, never a guess. Address in the document ≠ registered payee → flag (never auto-register).
- **Permissions:** Operator.
- **AI responsibility:** Observe and Recommend (extract and flag). It never decides payee or approval.
- **Human responsibility:** The Operator confirms every field. The Approver approves.
- **Acceptance criteria:** On a labelled set of 30 invoices, field accuracy is reported. No extraction can change a registered payee address. The document is never sent to the LLM together with secrets.

#### F-032 · CSV bulk import
`M1 · P1 · Source: Q15 · Module: invoices`
- **Description:** Import many invoices from a CSV template.
- **Problem solved:** Batch payouts (e.g., 40+ contractors).
- **Users:** Operator.
- **Trigger:** Upload CSV.
- **Input:** CSV per template (header validated).
- **Business logic:** Validate each row independently → valid rows become Drafts → invalid rows produce a downloadable error report → fingerprints checked within the file and against history.
- **Output:** N drafts plus an error report.
- **Happy path:** Upload → preview → confirm → drafts created.
- **Alternative flows:** Partial import (valid rows only).
- **Edge cases:** Duplicate rows within the file. Wrong delimiter or encoding. Spreadsheet formula-injection cells (`=`, `+`, `-`, `@`) are neutralized.
- **Permissions:** Operator.
- **AI responsibility:** None (anomaly checks run per row).
- **Human responsibility:** Review the preview.
- **Acceptance criteria:** 500 rows import in under 10 seconds. Errors are reported per row. Formula injection is neutralized.

#### F-033 · Email-forwarding inbox
`Later · Source: Q15 · Module: invoices / integration`
- **Description:** A unique inbox address per org. Forwarded invoice emails become drafts through F-031.
- **Problem solved:** Removes the upload step entirely.
- **Users:** Operator.
- **Trigger:** An inbound email.
- **Input:** Email with attachment.
- **Business logic:** Verify sender domain (SPF/DKIM) → extract attachments → F-031 pipeline. The email body is treated as untrusted.
- **Output:** Drafts.
- **Happy path:** Vendor emails an invoice → draft appears.
- **Alternative flows:** No attachment → body parsed.
- **Edge cases:** Spoofed sender → flagged. Large attachments → rejected.
- **Permissions:** OrgAdmin enables it.
- **AI responsibility:** Observe and Recommend.
- **Human responsibility:** Confirm drafts.
- **Acceptance criteria:** Spoofed emails are flagged. Drafts are never auto-approved.

#### F-034 · Inbound API / webhook intake
`Later · Source: Q15 · Module: integration`
- **Description:** An authenticated API for other systems (ERP, AP tools) to create draft requests.
- **Problem solved:** Integration with existing AP flows.
- **Users:** Integrations (API keys scoped per org).
- **Trigger:** API call.
- **Input:** JSON per schema, with an idempotency key.
- **Business logic:** Same validation as F-030. Idempotent.
- **Output:** Draft id.
- **Happy path:** POST → 201.
- **Alternative flows:** Bulk endpoint.
- **Edge cases:** Retries with the same idempotency key → same result.
- **Permissions:** API key with the `invoices:create` scope.
- **AI responsibility:** None.
- **Human responsibility:** Approve.
- **Acceptance criteria:** Idempotency is verified. Scoped keys cannot approve.

#### F-035 · Payment-terms extraction
`M1 · P0 · Source: N1 · Module: agent / invoices`
- **Description:** Extract machine-readable payment terms from invoice text: due date, early-payment discount (e.g., "2/10 net 30"), late-fee schedule, and vendor criticality notes.
- **Problem solved:** Terms drive the value of the scheduler (P4).
- **Users:** Operator confirms. The scheduler consumes.
- **Trigger:** F-031, or a free-text terms field in F-030/F-032.
- **Input:** Invoice text.
- **Business logic:** LLM structured output → `{discountPct, discountDeadline, netDueDate, lateFee: {type, rate, period}, priorityNote}` → deterministic validation (dates are valid, percentages are within bounds) → shown for human confirmation. **Only confirmed terms are used by the scheduler.**
- **Output:** Confirmed terms on the request.
- **Happy path:** "2/10 net 30" → discount 2% until D+10, due D+30 → confirmed.
- **Alternative flows:** No terms → defaults (net due date only).
- **Edge cases:** Ambiguous terms → `uncertain` flag; the operator must choose. Conflicting terms → flag.
- **Permissions:** Operator confirms. Approver sees the terms as part of the approved record.
- **AI responsibility:** Observe and Recommend.
- **Human responsibility:** Confirm the terms (they become part of the approved data).
- **Acceptance criteria:** Extraction accuracy is reported on the labelled set. Unconfirmed terms are never used in scheduling.

#### F-036 · Anomaly & fraud-signal detection
`M1 · P0 · Source: N1, AT-09 · Module: agent / invoices`
- **Description:** Flags on each draft: payee address differs from vendor history; amount is an outlier against vendor history; duplicate fingerprint; injected instructions found in the document; mismatched currency or chain; due date anomaly.
- **Problem solved:** BEC fraud, duplicate payment, prompt injection (P3).
- **Users:** Operator, Approver.
- **Trigger:** Draft creation or update.
- **Input:** Draft, vendor history, registry.
- **Business logic:** Deterministic checks (address, fingerprint, currency, statistical outlier using median ± k·MAD) plus LLM-based detection of instruction-like text. Each flag has a severity, evidence and a reason code. **Flags never auto-approve or auto-reject. High-severity flags require explicit acknowledgment by the Approver.**
- **Output:** Flags list.
- **Happy path:** Clean → no flags.
- **Alternative flows:** Flagged → the Approver acknowledges or rejects.
- **Edge cases:** New vendor with no history → "no baseline" (not "clean"). LLM unavailable → deterministic flags only, plus a coverage note (F-122).
- **Permissions:** System.
- **AI responsibility:** Observe and Recommend.
- **Human responsibility:** The Approver acknowledges or rejects.
- **Acceptance criteria:** The red-team set (20 injected invoices) produces flags. No flag can alter fields.

#### F-037 · Duplicate-invoice fingerprint
`M1 · P0 · Source: S3, UC-04 · Module: invoices / contracts`
- **Description:** `fingerprint = keccak256(normalize(vendorId), normalize(invoiceNo), amount, asset)`. The backend warns at intake, and the contract registry blocks a second PAY with the same fingerprint.
- **Problem solved:** The same invoice entered under two request IDs (a gap the source admits in UC-04).
- **Users:** System.
- **Trigger:** Intake (warning) and PAY (enforcement).
- **Input:** Normalized fields.
- **Business logic:** Normalization (trim, case, strip separators) → hash → check the registry. A legitimate repeat (e.g., recurring same amount) needs a distinct invoice number, or an Owner-approved override flag included in the approval.
- **Output:** Warning or revert.
- **Happy path:** Unique → proceed.
- **Alternative flows:** Override with the Owner's signature.
- **Edge cases:** Vendor re-issues a corrected invoice (new number) → allowed, and the old one is cancelled.
- **Permissions:** Override: Owner only.
- **AI responsibility:** None.
- **Human responsibility:** Resolve duplicates.
- **Acceptance criteria:** A second PAY with the same fingerprint reverts on-chain (test).

#### F-038 · Invoice approval via EIP-712 signature
`M1 · P0 · Source: R1, UC-01 · Module: invoices / contracts`
- **Description:** The Approver signs typed data that binds request_id, invoice hash, fingerprint, chain, contract, treasury, paying wallet, asset, payee, standard amount, optional early amount and early-pay-by date (ADR-019), deadline, confirmed terms hash and expiry. The contract verifies the signature at PAY and pays exactly the early amount before early-pay-by, otherwise exactly the standard amount.
- **Problem solved:** Approval is cryptographic and bound to exact fields, not a backend flag.
- **Users:** Approver.
- **Trigger:** Request in AwaitingApproval.
- **Input:** Request, Approver wallet signature.
- **Business logic:** Maker-checker check (F-005) → show the diff and flags (F-131) → the wallet signs → backend verifies → state `Approved`. Any edit invalidates the approval (BR-003).
- **Output:** Approval record with signature.
- **Happy path:** Review → sign → Approved.
- **Alternative flows:** Reject with a reason → `Rejected`. Request changes → back to Draft.
- **Edge cases:** Signature for the wrong chain or contract → invalid. Approver removed before execution → the contract checks the current approver set (OQ-08). Approval expired → re-approval needed.
- **Permissions:** Approver role with a linked wallet.
- **AI responsibility:** None.
- **Human responsibility:** **Decide whether to pay.**
- **Acceptance criteria:** A PAY with a tampered field reverts (test). Edits invalidate approvals (test).

#### F-039 · Payment request lifecycle & state machine
`M1 · P0 · Source: Use-Case §5 · Module: invoices / core`
- **Description:** Request states: `Draft → AwaitingApproval → Approved → Scheduled → Planning → Preparing → Paying → Paid`. Branches: `Rejected`, `AwaitingAuthority`, `NeedsReview`, `Expired`, `Cancelled`. Transaction states and reconciliation states are separate.
- **Problem solved:** Unambiguous status. No single "Failed" state that erases history.
- **Users:** All.
- **Trigger:** Any transition.
- **Input:** Events.
- **Business logic:** Explicit transition table. Illegal transitions are rejected. Every transition is audited. `Cancelled` is not allowed while a PAY transaction is pending or unknown.
- **Output:** Current state and history.
- **Happy path:** As above.
- **Alternative flows:** Branches as listed.
- **Edge cases:** Concurrent transitions → optimistic locking.
- **Permissions:** Transitions are bound to roles (e.g., only an Approver moves AwaitingApproval → Approved).
- **AI responsibility:** None (it reads states).
- **Human responsibility:** Per role.
- **Acceptance criteria:** Transition-table unit tests. Illegal transitions are rejected.

#### F-040 · Recurring payment schedules
`Later · Source: D5, Q2 · Module: invoices`
- **Description:** Define recurring obligations (e.g., a monthly contractor fee). Each period generates a **draft** that still requires approval.
- **Problem solved:** Repetitive entry.
- **Users:** Operator.
- **Trigger:** Schedule tick.
- **Input:** Template, cadence, end date.
- **Business logic:** Generate drafts only. Never auto-approve (BR-002).
- **Output:** Periodic drafts.
- **Happy path:** Each month a draft appears and is approved.
- **Alternative flows:** Skip a period.
- **Edge cases:** Template payee changed → new drafts use the new payee, subject to cooling.
- **Permissions:** Operator creates. Approver approves each period.
- **AI responsibility:** None.
- **Human responsibility:** Approve each period.
- **Acceptance criteria:** No generated draft is payable without approval.

#### F-041 · Fiat-denominated invoices with FX & depeg checks
`Later · Source: Q20 · Module: financial`
- **Description:** Invoices in fiat (USD, EUR, …) converted to a stablecoin amount through a configured FX source. Payment is blocked if the stablecoin depegs beyond a threshold.
- **Problem solved:** Real invoices are usually fiat-denominated.
- **Users:** Operator, Approver.
- **Trigger:** Intake of a fiat invoice.
- **Input:** Fiat amount, currency, FX source.
- **Business logic:** The approval binds the fiat amount and a maximum stablecoin amount. The rate is fixed at execution within a tolerance. A depeg check runs before PAY.
- **Output:** Converted payment.
- **Happy path:** €1,000 → USDC amount within tolerance → paid.
- **Alternative flows:** Out of tolerance → NeedsReview.
- **Edge cases:** FX source stale → block.
- **Permissions:** Owner configures the FX source.
- **AI responsibility:** None.
- **Human responsibility:** Approve the tolerance.
- **Acceptance criteria:** Never pays above the approved maximum stablecoin amount.

### 3.5 Liquidity & Planning

#### F-050 · Chain state reader & fresh snapshots
`M1 · P0 · Source: UC-02, Autonomy §3 · Module: chain-reader`
- **Description:** Reads balances (stablecoin and native), mandate state, counters, payee status and module configuration at a specific block. Snapshots record `blockNumber`, `blockHash`, `observedAt` and coverage.
- **Problem solved:** Plans must use fresh, provable state, never an earlier snapshot after the state has changed.
- **Users:** System (planner, validator, executor).
- **Trigger:** Before planning, before each step, and on a polling schedule.
- **Input:** Treasury config.
- **Business logic:** Batched reads at one block → snapshot. Freshness threshold N blocks. Stale or partial → coverage `PARTIAL/UNKNOWN` → no execution.
- **Output:** Snapshot object.
- **Happy path:** Read → COMPLETE snapshot.
- **Alternative flows:** Fallback RPC provider.
- **Edge cases:** RPC disagreement or lag → mark UNKNOWN. Reorg → re-read.
- **Permissions:** System.
- **AI responsibility:** Observe (read-only tools).
- **Human responsibility:** None.
- **Acceptance criteria:** No step executes on a snapshot older than the threshold. RPC failure never yields "ok".

#### F-051 · Liquidity calculator
`M1 · P0 · Source: Domain §3 · Module: financial-engine`
- **Description:** Deterministic computation of `Available`, `FundingDeficit`, `Shortage`, `PreferredRefill`, `SourceCapacity` and `Cap`, plus the decision table (refill preferred / refill shortage / stop).
- **Problem solved:** Amounts are never computed by the LLM (BR-034).
- **Users:** System.
- **Trigger:** Planning.
- **Input:** Snapshot, request(s), buffers, targets, budgets.
- **Business logic:** Exactly the formulas in Domain §3.1–3.3, using integers in base units.
- **Output:** Per-request funding plan numbers plus a reason.
- **Happy path:** B=20, P=100, F=H=10 → Shortage=PreferredRefill=90.
- **Alternative flows:** Cap between Shortage and Preferred → refill Shortage and report "target not reached".
- **Edge cases:** Cap < Shortage → STOP (BR-033). `H < F` config → invalid upstream.
- **Permissions:** System.
- **AI responsibility:** None.
- **Human responsibility:** None.
- **Acceptance criteria:** The Domain §3.4 and UC-02 examples pass as tests. Property tests: no output breaches the buffer.

#### F-052 · Terms-aware deterministic scheduler
`M1 · P0 · Source: N2, O8 · Module: financial-engine`
- **Description:** Given approved requests with confirmed terms, available liquidity and budgets, compute the feasible payment schedule that maximizes value: (1) no hard-rule violation, (2) meet every feasible deadline, (3) maximize discounts captured minus late fees, (4) minimize transaction count (BR-052). The baseline B1 = earliest-deadline-first.
- **Problem solved:** P4: rules like "earliest due first" leave money on the table.
- **Users:** System. Results are shown to Finance and the Owner.
- **Trigger:** Planning cycle.
- **Input:** Requests, terms, snapshot, budgets, current date.
- **Business logic:** Exact search for small N (≤ 12) or greedy with an exchange-improvement step. Outputs the schedule plus binding constraints. Infeasible items get reasons (cooling payee, over daily cap → next day, needs exception).
- **Output:** Ranked schedule with expected value per item.
- **Happy path:** Pays the discount invoice early, and the late-fee invoice before its fee date.
- **Alternative flows:** The AI proposes an alternative ordering → evaluated by the same objective → the better feasible one wins (F-053).
- **Edge cases:** Ties → approval order. Every item infeasible → NeedsReview with reasons.
- **Permissions:** System.
- **AI responsibility:** None (deterministic). The AI consumes and explains its output.
- **Human responsibility:** Confirm terms upstream.
- **Acceptance criteria:** Unit tests on hand-computed cases. The objective never violates hard rules (property test).

#### F-053 · AI plan proposal & explanation
`M1 · P0 · Source: N2, Autonomy §2 · Module: agent`
- **Description:** The LLM agent, using read-only tools, proposes the plan structure and order: which requests now, which to defer, which need exceptions, which wallet to use. It writes a human-readable explanation citing evidence (terms, balances, limits). Amounts come from F-051 and F-052.
- **Problem solved:** Handles judgment cases (vendor criticality notes, ambiguous priorities, multi-constraint trade-offs) and explains them.
- **Users:** System. Explanations are shown to users.
- **Trigger:** Planning cycle.
- **Input:** Scheduler output, snapshot, requests and terms, policy summary.
- **Business logic:** Structured output schema `{requestOrder[], deferrals[], exceptionRequests[], rationale[], evidenceIds[]}` → schema validation → scored by F-052's objective → policy validation (F-055). Plans that are invalid or dangerous are discarded → NeedsReview (BR-056). `plannerSource=AI`.
- **Output:** Candidate plan plus explanation.
- **Happy path:** The AI proposes → validated → chosen.
- **Alternative flows:** AI timeout → F-054. The AI's plan scores below the deterministic plan → the deterministic plan is chosen, and the comparison is logged.
- **Edge cases:** The AI references a non-existent request or invents amounts → rejected. Low confidence is not a signal; validation decides (BR-058).
- **Permissions:** The Agent has read-only tools only.
- **AI responsibility:** Observe, Recommend, Decide (among validated options).
- **Human responsibility:** None per plan within the mandate. Exceptions go to the Owner.
- **Acceptance criteria:** No AI output reaches the executor without passing F-055. Every plan logs its plannerSource and evidence IDs.

#### F-054 · Rule-based fallback planner
`M1 · P0 · Source: D6, AD-02 · Module: agent / financial-engine`
- **Description:** When the AI is unavailable, the system uses tested templates (pay direct; refill then pay; swap via the fixed route then pay) with deterministic ordering (F-052).
- **Problem solved:** Availability without granting extra authority.
- **Users:** System.
- **Trigger:** AI timeout or error.
- **Input:** Same as F-053.
- **Business logic:** Allowed only if data is complete, a template matches, and there is no Unknown transaction or safety alert (BR-055). `plannerSource=RULE_BASED`.
- **Output:** Plan.
- **Happy path:** AI down → template → executes.
- **Alternative flows:** No template matches → NeedsReview.
- **Edge cases:** Unknown transaction outstanding → no fallback (AD-03).
- **Permissions:** System.
- **AI responsibility:** None.
- **Human responsibility:** None.
- **Acceptance criteria:** AD-02 and AD-03 pass.

#### F-055 · Policy validation (ALLOW / NEEDS_APPROVAL / BLOCK)
`M1 · P0 · Source: Autonomy §4, FJ · Module: policy-engine`
- **Description:** A deterministic validator checks the whole plan and each step: approval validity, mandate active, payee active, limits, buffer, quotes, deadlines, coverage, Unknown transactions. It outputs a decision plus reason codes.
- **Problem solved:** A single, auditable gate that mirrors the contract checks.
- **Users:** System.
- **Trigger:** Before attestation and before each step.
- **Input:** Plan, snapshot, mandate, approvals.
- **Business logic:** The decision table in Autonomy §4. Multiple issues → the most restrictive wins. An exception never masks a hard-rule failure.
- **Output:** `{decision, reasonCodes[], checks[]}`.
- **Happy path:** ALLOW.
- **Alternative flows:** NEEDS_APPROVAL → F-025/F-057. BLOCK → F-082.
- **Edge cases:** Missing data → never ALLOW.
- **Permissions:** System.
- **AI responsibility:** None.
- **Human responsibility:** None.
- **Acceptance criteria:** Each reason code has a unit test. The validator and contract agree on all AT-05 cases (differential test).

#### F-056 · Plan attestation
`M1 · P1 · Source: GA p.21–22 · Module: policy-engine / contracts`
- **Description:** After an ALLOW, the review signer signs EIP-712 data that binds `planHash`, requestId, step ids, policyVersion, executor, validUntil, nonce and evidenceDigest. The executor submits only attested steps.
- **Problem solved:** Prevents the payload being altered between validation and execution (plan drift).
- **Users:** System.
- **Trigger:** ALLOW decision.
- **Input:** Validated plan.
- **Business logic:** Canonical encoding (not JSON) → hash → sign. The contract or executor verifies the attestation, its expiry and its nonce.
- **Output:** Attestation.
- **Happy path:** Attest → submit → verify.
- **Alternative flows:** Expired → re-validate → re-attest.
- **Edge cases:** Signer key compromise → damage bounded by the mandate (documented risk).
- **Permissions:** Signer service only.
- **AI responsibility:** None.
- **Human responsibility:** None.
- **Acceptance criteria:** A modified step with an old attestation is rejected (test).

#### F-057 · AI exception-request drafting
`M1 · P1 · Source: N2 · Module: agent`
- **Description:** When the decision is NEEDS_APPROVAL, the agent drafts a request for the Owner: what is needed, why (terms, deadline, consequences), the impact on the daily budget, and alternatives (wait until tomorrow, split approval is not allowed, etc.).
- **Problem solved:** Speeds up Owner decisions and makes them informed.
- **Users:** Owner.
- **Trigger:** NEEDS_APPROVAL.
- **Input:** Request, validator output, scheduler context.
- **Business logic:** LLM text plus a structured summary. The numbers come from the engine. The Owner signs via F-025.
- **Output:** Exception request card.
- **Happy path:** Draft → Owner signs.
- **Alternative flows:** The Owner rejects.
- **Edge cases:** LLM down → template text.
- **Permissions:** Owner acts.
- **AI responsibility:** Recommend.
- **Human responsibility:** Decide.
- **Acceptance criteria:** Numbers in the draft match the engine output exactly (test).

#### F-058 · Liquidity forecast & runway
`M1 · P2 · Source: T8 · Module: financial-engine`
- **Description:** A 7-day forward view per wallet: approved obligations by date versus balances, showing when each wallet will hit its buffer, plus suggested pre-emptive refills.
- **Problem solved:** Proactive rather than last-minute refills.
- **Users:** Owner, Finance, Operator.
- **Trigger:** Dashboard load and the daily job.
- **Input:** Approved requests, balances, limits.
- **Business logic:** Deterministic projection. It does not include unapproved drafts unless toggled on ("what-if").
- **Output:** Runway chart and alerts.
- **Happy path:** "O1 hits buffer on Thu; refill 1,200 Wed."
- **Alternative flows:** Include drafts.
- **Edge cases:** Unknown transactions → shown as uncertainty.
- **Permissions:** Read for all roles.
- **AI responsibility:** Recommend (narrative).
- **Human responsibility:** None.
- **Acceptance criteria:** Projection math is tested. Suggested refills respect the limits.

#### F-059 · Refill from other operational wallets
`Later · Source: D5, Q2 · Module: financial-engine / contracts`
- **Description:** Allow `Oi→Oj` refills when T is short, within the paths and limits in the mandate.
- **Problem solved:** Funds stranded in one operational wallet.
- **Users:** System.
- **Trigger:** Planning, when T's capacity is insufficient.
- **Input:** Snapshot, mandate paths.
- **Business logic:** The source wallet's own buffer and its upcoming obligations are protected.
- **Output:** Additional refill options.
- **Happy path:** O2 surplus → O1.
- **Alternative flows:** —
- **Edge cases:** Circular refills are prevented.
- **Permissions:** The mandate must list the path.
- **AI responsibility:** Recommend.
- **Human responsibility:** Configure the paths.
- **Acceptance criteria:** The source wallet's obligations are never underfunded (property test).

### 3.6 Execution

#### F-060 · Deadline-driven autonomous trigger
`M1 · P0 · Source: T1 · Module: orchestrator`
- **Description:** A scheduler wakes up periodically and when relevant events happen (approval, balance change) and starts planning for requests entering their execution window (deadline minus lead time, or the discount window). No human clicks "execute".
- **Problem solved:** Makes the agent a financial participant, not a button.
- **Users:** System.
- **Trigger:** Timer (e.g., every 1 minute in the demo) or events.
- **Input:** Approved requests, windows.
- **Business logic:** Selects eligible requests → planning → execution. Skips if paused, coverage is not COMPLETE, or an Unknown transaction exists.
- **Output:** Planning job.
- **Happy path:** Window opens → plan → pay.
- **Alternative flows:** A manual "run now" exists for the Operator, with the same checks.
- **Edge cases:** Overlapping triggers → a single-flight lock per treasury (BR-050).
- **Permissions:** System. The manual run needs the Operator role.
- **AI responsibility:** Act (initiation is automatic; actions are still validated).
- **Human responsibility:** None.
- **Acceptance criteria:** A log shows an automatic trigger leading to a tx hash with no user action. The lock prevents concurrent runs.

#### F-061 · Sequential executor & signer service
`M1 · P0 · Source: UC-02, S8 · Module: execution / signer`
- **Description:** The executor turns attested steps into the module's typed calls and submits them through a separate signer service that holds the executor key. One step and one request at a time per treasury.
- **Problem solved:** Key isolation from the LLM and the API process. Ordering safety.
- **Users:** System.
- **Trigger:** An attested plan.
- **Input:** Step, attestation.
- **Business logic:** Re-check before submit → simulate (eth_call) the exact call → sign → persist (nonce, txHash) before broadcast (outbox) → broadcast → hand off to F-070.
- **Output:** Submitted transaction.
- **Happy path:** Simulate ok → submit → tracked.
- **Alternative flows:** Simulation revert → no broadcast → NeedsReview (GA AT37).
- **Edge cases:** Nonce gap or stuck transaction → replacement with the same nonce is tracked as a replacement, never as a new payment.
- **Permissions:** The signer accepts only validator-attested payloads.
- **AI responsibility:** None.
- **Human responsibility:** None.
- **Acceptance criteria:** The LLM process has no network path to the signer except through the validator (architecture test). The outbox survives a crash.

#### F-062 · REFILL execution
`M1 · P0 · Source: D4, UC-02 · Module: contracts / execution`
- **Description:** Move the stablecoin (or native gas within the gas cap) from T to an operational wallet along an allowed path, for a specific request and step.
- **Problem solved:** P1.
- **Users:** System.
- **Trigger:** A plan step.
- **Input:** Request id, step id, amount.
- **Business logic:** The contract checks: mandate active, path allowed, refill limits, `F_T` buffer, step id unused, request approved → executes via the Safe module call → marks the step used.
- **Output:** Transaction plus event `RefillExecuted`.
- **Happy path:** Refill 90 → confirmed.
- **Alternative flows:** —
- **Edge cases:** A retry after success → step id already used → revert (AT-07).
- **Permissions:** Executor via the module.
- **AI responsibility:** None (executes the validated plan).
- **Human responsibility:** None.
- **Acceptance criteria:** AT-02 and AT-07 pass. The event carries request/step ids.

#### F-063 · PAY execution
`M1 · P0 · Source: D4, UC-02 · Module: contracts / execution`
- **Description:** Pay the approved amount to the approved payee from the paying wallet.
- **Problem solved:** The core job.
- **Users:** System.
- **Trigger:** A plan step.
- **Input:** Request data, approval signature, optional exception, attestation.
- **Business logic:** The contract verifies the approval signature (fields bound), fingerprint unused, request unused, payee Active, per-request/daily limits (or exception), buffer after payment, not paused → transfer → mark used and update counters atomically.
- **Output:** Transaction plus event `PaymentExecuted(requestId, fingerprint, payee, amount)`.
- **Happy path:** Pay 100 → confirmed → Paid after confirmations.
- **Alternative flows:** With an exception → the exception is consumed.
- **Edge cases:** Token returns false → treated as failure. Any check fails → revert with an error code.
- **Permissions:** Executor via the module.
- **AI responsibility:** None.
- **Human responsibility:** The approval was given upstream.
- **Acceptance criteria:** AT-01, AT-05, AT-06 and AT-11 pass. Invariants S1 hold.

#### F-064 · SWAP via allowlisted adapter (labelled test router)
`M1 · P2 · Source: AT-04, R5 · Module: contracts / execution`
- **Description:** Swap stablecoin to native gas (in M1) through an allowlisted adapter and router. The quote comes from the configured source; `minOut` is computed from the quote; the allowance is set to exactly the input amount and reset to 0 in the same transaction. In M1 the router is a team-deployed test router, clearly labelled.
- **Problem solved:** Gas shortages (AT-03/04).
- **Users:** System.
- **Trigger:** A plan step when gas is short.
- **Input:** Quote, amountIn.
- **Business logic:** Check the swap limits, quote freshness and pair → approve(exact) → swap → approve(0) → verify `out ≥ minOut`.
- **Output:** Transaction.
- **Happy path:** Swap 5 USDC → gas → continue.
- **Alternative flows:** No valid quote → STOP.
- **Edge cases:** The agent tries to lower minOut → impossible (computed by the engine). Stale quote → reject.
- **Permissions:** Executor via the module.
- **AI responsibility:** None.
- **Human responsibility:** Configure the router and slippage.
- **Acceptance criteria:** AT-04 and AT-13 pass. Allowance is 0 after every swap (test). The UI and docs label it a "test router".

#### F-065 · Real DEX / aggregator swap with verified quotes
`Later · Source: Domain §5.3, Q2 · Module: contracts / integration`
- **Description:** Production swaps through a real DEX or aggregator, with quotes signed by a trusted quote source and verified on-chain.
- **Problem solved:** Real liquidity and real price protection.
- **Users:** System.
- **Trigger:** A plan step.
- **Input:** Signed quote.
- **Business logic:** The adapter verifies the quote signature, expiry, pair and recipient.
- **Output:** Transaction.
- **Happy path:** Quote → swap.
- **Alternative flows:** Fallback quote source.
- **Edge cases:** Depeg or quote deviation → block.
- **Permissions:** Owner allowlists sources.
- **AI responsibility:** None.
- **Human responsibility:** Choose providers.
- **Acceptance criteria:** A forged quote is rejected on-chain.

#### F-066 · Gas management
`M1 · P1 · Source: R7, Domain §5.4, O6 · Module: execution`
- **Description:** The executor infrastructure wallet is prefunded with gas. A gas funding cap (native) applies separately. Actual fees are tracked per transaction. Low-gas alerts are sent.
- **Problem solved:** "USDC but no gas" failures (E3).
- **Users:** System, Owner.
- **Trigger:** Each transaction, and thresholds.
- **Input:** Fee data.
- **Business logic:** Fee envelope checks before submission. Actual fees are recorded (including on reverts). Alert below the threshold. Native gas is never PAY-able to vendors (BR-080).
- **Output:** Fee records and alerts.
- **Happy path:** Enough gas → submit.
- **Alternative flows:** Low gas → alert → Owner tops up, or the plan includes a gas refill/swap.
- **Edge cases:** No gas anywhere → STOP with a clear message (R7).
- **Permissions:** System.
- **AI responsibility:** Observe.
- **Human responsibility:** Top up when alerted.
- **Acceptance criteria:** Fees are recorded for 100% of transactions. AT-03 passes.

#### F-068 · Idle-cash management on Aave V3 (SUPPLY / WITHDRAW)
`M1 · P0 · Source: v0.3 §4, §6, ADR-019 · Module: contracts / financial / execution`
- **Description:** USDC in Safe T above `RequiredSafeReserve` is supplied to the allowlisted Aave V3 Pool; when approved obligations grow, the agent withdraws to restore the reserve. aTokens stay in Safe T.
- **Problem solved:** idle cash earns nothing, while over-supplying risks missing a due payment.
- **Business logic:** `AvailableForSupply = max(0, SafeUSDC − RequiredSafeReserve)`; supply only if ≥ `minSupply`; withdraw deficit + 5 %; on-chain checks: fixed Pool/aToken, Safe floor, supply caps, pause, expiry.
- **AI responsibility:** explain; never decides amounts.
- **Acceptance criteria:** D2 (supply exactly the surplus, reserve intact) and D3 (new approved invoice triggers a withdraw) pass on Sepolia; supply never leaves Safe T below the floor (invariant).

#### F-069 · Borrow proposal
`M1 · P1 · Source: v0.3 §7 · Module: financial / agent / web`
- **Description:** when withdraw is limited (pool liquidity) or the owner wants to keep a position, the optimizer produces a borrow proposal: amount, deadline, borrow cost to repayment, withdraw cost, health factor before/after, policy thresholds, reason. No transaction (demo D6).
- **Acceptance criteria:** the proposal is shown with numbers from the engine and never enters an executable plan without an owner authorization.

#### F-079 · Owner-authorized BORROW / REPAY execution
`M1 · P2 · Source: v0.3 §5 · Module: contracts / execution`
- **Description:** the Owner signs a one-time authorization bound to planId, snapshot hash, amount, pool, expiry, max cost, minimum health factor and repayment plan; the module borrows/repays exactly that, checking health factor just before the call (demo D7).

#### F-067 · Cross-chain bridge
`Later · Source: D5, Q2 · Module: execution / integration`
- **Description:** Move funds between treasuries on different chains through an allowlisted bridge.
- **Problem solved:** Liquidity stranded on another chain.
- **Users:** System, Owner.
- **Trigger:** Planning (multi-chain).
- **Input:** Bridge route.
- **Business logic:** In-flight funds are not counted as balance. Separate limits. Timeouts are tracked.
- **Output:** Bridge transactions.
- **Happy path:** Bridge → arrival verified.
- **Alternative flows:** —
- **Edge cases:** Stuck bridge → Unknown state, with no re-send.
- **Permissions:** The mandate must allow it.
- **AI responsibility:** Recommend.
- **Human responsibility:** Allowlist bridges.
- **Acceptance criteria:** No double-bridging on timeout (test).

### 3.7 Verification & Reconciliation

#### F-070 · Transaction tracking & confirmation
`M1 · P0 · Source: UC-03 · Module: verification`
- **Description:** Track every transaction through `NotSubmitted → Submitted → Pending → Confirmed | Reverted | Unknown`, with chain-specific confirmation depth.
- **Problem solved:** "Broadcast" is not "done". Paid only after confirmation (BR-053).
- **Users:** System. Visible to all.
- **Trigger:** After broadcast; on a polling or subscription schedule.
- **Input:** txHash, nonce.
- **Business logic:** Poll receipts. Reorg detection by blockHash. Timeout → Unknown (never Failed).
- **Output:** Transaction status plus receipt.
- **Happy path:** Pending → Confirmed after N blocks.
- **Alternative flows:** Replacement transaction (same nonce) is linked.
- **Edge cases:** Reorg → back to Pending.
- **Permissions:** System.
- **AI responsibility:** None.
- **Human responsibility:** None.
- **Acceptance criteria:** Reorg simulation on Anvil re-evaluates the status. No transaction is marked Paid before N confirmations.

#### F-071 · Post-condition verification
`M1 · P0 · Source: UC-02 step 4, GA p.14 · Module: verification`
- **Description:** After each confirmed step, verify the expected effects: balances changed by the expected deltas, request marked used on-chain, allowance 0 after a swap, counters incremented.
- **Problem solved:** "Not reverted" is not proof of correctness (GA p.2).
- **Users:** System.
- **Trigger:** Confirmation.
- **Input:** Expected deltas from the plan, post-state reads.
- **Business logic:** Compare → `PASSED | DISCREPANCY | UNKNOWN`. A discrepancy → NeedsReview, and the circuit-breaker signal fires.
- **Output:** Verification record.
- **Happy path:** PASSED.
- **Alternative flows:** —
- **Edge cases:** Concurrent external transfer (Owner) → explain the discrepancy as "external change detected".
- **Permissions:** System.
- **AI responsibility:** Recommend (explains discrepancies).
- **Human responsibility:** Resolve discrepancies.
- **Acceptance criteria:** Every confirmed step has a verification record.

#### F-072 · Reconciliation (Paid vs Matched)
`M1 · P0 · Source: UC-03 · Module: reconciliation`
- **Description:** Link each request to all its transactions (refill, swap, pay), fees and classification: refill = internal transfer, swap = conversion, pay = external expense. Reconciliation states: `NotReady → Pending → Matched | Discrepancy`.
- **Problem solved:** P5.
- **Users:** Finance.
- **Trigger:** Request Paid.
- **Input:** Request, transactions, receipts, invoice data.
- **Business logic:** Auto-match amount, payee, fingerprint and tx. Finance confirms Matched (or the system auto-matches when all evidence matches, if the org config allows it).
- **Output:** Reconciliation record.
- **Happy path:** Paid → auto evidence ok → Finance marks Matched.
- **Alternative flows:** Discrepancy → note → resolution.
- **Edge cases:** Refill done but pay blocked → refill shown as an internal transfer with no expense.
- **Permissions:** Finance.
- **AI responsibility:** Recommend (summarizes discrepancies).
- **Human responsibility:** Mark Matched.
- **Acceptance criteria:** Refills are never booked as vendor expense (test). One request ↔ many transactions supported.

#### F-073 · Reconciliation export (CSV / journal)
`M1 · P1 · Source: T5 · Module: reconciliation`
- **Description:** Export a period's records as CSV, plus simple double-entry journal lines (Dr Vendor expense / Cr Stablecoin wallet; refills as transfers between wallet accounts; gas as a fee expense).
- **Problem solved:** Accounting handoff.
- **Users:** Finance, Auditor.
- **Trigger:** Manual export.
- **Input:** Period, treasury.
- **Business logic:** Deterministic mapping with a configurable chart-of-accounts mapping (OQ-12).
- **Output:** CSV files.
- **Happy path:** Choose the period → download.
- **Alternative flows:** —
- **Edge cases:** Unmatched items are included with a status column.
- **Permissions:** Finance, Auditor.
- **AI responsibility:** None.
- **Human responsibility:** Configure account mapping.
- **Acceptance criteria:** Export totals equal on-chain totals for the period (test).

#### F-074 · On-chain payment attestation
`M1 · P2 · Source: N6 · Module: reconciliation / contracts`
- **Description:** Publish an attestation (e.g., EAS, subject to chain availability) per paid request: `{fingerprint hash, requestId, payTxHash, amount, payee, timestamp}`. No personal data.
- **Problem solved:** Third-party-verifiable proof of payment (helps the on-chain bonus).
- **Users:** Finance, Auditor, vendors (verification).
- **Trigger:** Matched (or Paid, per config).
- **Input:** Reconciliation record.
- **Business logic:** Schema registered once. Attestation tx tracked like other transactions.
- **Output:** Attestation UID.
- **Happy path:** Matched → attestation.
- **Alternative flows:** Disabled per org.
- **Edge cases:** Attestation fails → retry without affecting the payment status.
- **Permissions:** System.
- **AI responsibility:** None.
- **Human responsibility:** Enable it.
- **Acceptance criteria:** The UID is resolvable on an explorer. It contains no PII.

#### F-075 · ERP / accounting integrations
`Later · Source: D5, Q2 · Module: integration`
- **Description:** Sync vendors, bills and payments with Xero / QuickBooks / NetSuite.
- **Problem solved:** Removes double entry.
- **Users:** Finance.
- **Trigger:** Sync schedule or webhooks.
- **Input:** OAuth connection.
- **Business logic:** Bills import as drafts (never approved). Payments sync back as paid, with tx reference.
- **Output:** Synced records.
- **Happy path:** Bill in ERP → draft → paid → marked paid in ERP.
- **Alternative flows:** —
- **Edge cases:** Conflicting edits → ERP is the source for bill data; TreasuryPilot is the source for payment status.
- **Permissions:** OrgAdmin connects.
- **AI responsibility:** None.
- **Human responsibility:** Approve.
- **Acceptance criteria:** No ERP sync can approve a payment.

### 3.8 Recovery & Exception Handling

#### F-080 · Unknown-state recovery (no double pay)
`M1 · P0 · Source: R8, AT-06, T3 · Module: recovery`
- **Description:** After a timeout, crash or lost connection, resolve each in-flight operation by looking up its txHash and nonce, plus on-chain `requestUsed` and `stepUsed`, before any new action.
- **Problem solved:** Double payment risk.
- **Users:** System.
- **Trigger:** Worker restart, transaction Unknown, RPC errors.
- **Input:** Outbox records.
- **Business logic:** For each operation: if on-chain says it is used → mark Confirmed/Paid. If pending → wait. If never broadcast → safe to submit with the **same identifiers**. Treasury execution is blocked while any operation is Unknown.
- **Output:** Resolved operation states.
- **Happy path:** Kill the executor after broadcast → restart → finds the transaction → no second payment.
- **Alternative flows:** Dropped transaction → re-submit with the same request/step ids (the contract dedups).
- **Edge cases:** Ambiguous for more than a threshold → NeedsReview.
- **Permissions:** System.
- **AI responsibility:** None (no AI in recovery decisions).
- **Human responsibility:** Resolve NeedsReview.
- **Acceptance criteria:** The crash test (T3) shows exactly one PAY on-chain over 20 repetitions.

#### F-081 · Partial-completion handling
`M1 · P0 · Source: AT-07 · Module: recovery`
- **Description:** If a refill succeeded but the payment is blocked or failed, keep the refill, record "partially completed", and never auto-reverse. A retry continues from the unfinished step.
- **Problem solved:** Non-atomic multi-transaction plans (BR-054).
- **Users:** System, Operator.
- **Trigger:** A step fails after earlier steps succeeded.
- **Input:** Plan state.
- **Business logic:** Mark the completed steps. The request goes to NeedsReview or a retry. A retry re-validates and skips the done steps.
- **Output:** Partial state, visible.
- **Happy path:** Refill ok, pay blocked (payee paused) → partial → resolved later → pay only.
- **Alternative flows:** Request cancelled → refilled funds remain in O1 (reported).
- **Edge cases:** —
- **Permissions:** Operator can retry or cancel.
- **AI responsibility:** Recommend next steps.
- **Human responsibility:** Decide whether to retry or cancel.
- **Acceptance criteria:** AT-07: no duplicate refill on retry.

#### F-082 · Needs-review queue & exception routing
`M1 · P0 · Source: UC-04, FJ · Module: recovery`
- **Description:** All stops go into a review queue with a classification: policy/data error, retryable error, uncertain outcome, needs authority, infrastructure error. Each item carries reason codes, completed steps, and the options available for each role.
- **Problem solved:** Exceptions never disappear and are never "auto-fixed" by loosening policy.
- **Users:** Operator, Owner, Finance.
- **Trigger:** BLOCK, NEEDS_APPROVAL, discrepancy, Unknown, AI rejection.
- **Input:** Event plus context.
- **Business logic:** Route to roles. Over-cap → Owner (F-025). Payee or budget changes → Owner policy edit. Amount or payee changes → re-approval.
- **Output:** Queue items with SLA timers.
- **Happy path:** Item → resolved by the right role.
- **Alternative flows:** Escalation on SLA breach (notification).
- **Edge cases:** Multiple issues on one request → listed together; the hard rule shown first.
- **Permissions:** Per item type.
- **AI responsibility:** Recommend (explanation).
- **Human responsibility:** Resolve.
- **Acceptance criteria:** Every non-ALLOW outcome creates exactly one open item, which is closed only by an explicit action.

#### F-083 · Idempotent retry policy
`M1 · P0 · Source: UC-04 step 3 · Module: recovery / execution`
- **Description:** Retries keep the same request_id, step_id, operation id and idempotency key. Retryable errors (RPC, nonce, gas price) back off exponentially, up to N attempts.
- **Problem solved:** Retries that create new obligations or evade dedup.
- **Users:** System.
- **Trigger:** Retryable error.
- **Input:** Operation.
- **Business logic:** Classify the error → retry or stop. Never generate new ids on retry (BR-061).
- **Output:** Retried operation.
- **Happy path:** RPC 503 → retry → success.
- **Alternative flows:** Max attempts reached → NeedsReview.
- **Edge cases:** Retry after a pause → blocked.
- **Permissions:** System.
- **AI responsibility:** None.
- **Human responsibility:** None.
- **Acceptance criteria:** An id-stability test across retries passes.

### 3.9 AI Platform

#### F-090 · Treasury Copilot (what-if)
`M1 · P1 · Source: N4 · Module: agent`
- **Description:** A chat interface where Owner, Finance and Operator ask treasury questions ("Can we pay everything due this week without breaching the buffer?", "What if we defer invoice C?"). The agent answers using read-only tools and the deterministic engine in **simulation mode**.
- **Problem solved:** Fast, explainable decision support. Interaction quality.
- **Users:** Owner, Finance, Operator, Auditor (read).
- **Trigger:** User question.
- **Input:** Question, org context (scoped by role).
- **Business logic:** Tools: `get_snapshot`, `list_requests`, `simulate_schedule(params)`, `get_policy_summary`, `explain_decision(id)`. Every number in an answer comes from tool outputs, and answers cite them. **No write tools**. It may *offer* to open a draft or exception form, and the human completes it.
- **Output:** Answer with numbers, a plan and citations.
- **Happy path:** Ask → simulation → answer.
- **Alternative flows:** The question is out of scope → it says so.
- **Edge cases:** Prompt injection via stored invoice text → treated as data (F-091). The user asks it to pay → it refuses and points to the approval flow.
- **Permissions:** Data is scoped to the user's roles.
- **AI responsibility:** Observe, Recommend.
- **Human responsibility:** Any action.
- **Acceptance criteria:** A test suite of 20 questions: the numbers match the engine. Zero write side effects (verified by audit log).

#### F-091 · Untrusted-data boundary & prompt-injection defense
`M1 · P0 · Source: AT-09, AD-01, S5 · Module: agent / security`
- **Description:** All external content (invoices, emails, vendor notes, token metadata) is wrapped as data with source labels. Inputs are length-limited and normalized. Strict output schemas. Tool allowlists. A validator runs after the LLM. No secrets in prompts.
- **Problem solved:** Injected instructions changing payees or limits.
- **Users:** System.
- **Trigger:** Every LLM call.
- **Input:** Content.
- **Business logic:** OWASP LLM guidance: separate data from instructions, limit tools, validate before acting. A prompt alone is never the control.
- **Output:** Sanitized calls. Injection flags.
- **Happy path:** An injected invoice is flagged and has no effect.
- **Alternative flows:** —
- **Edge cases:** Unicode homoglyph addresses → address checks are deterministic (checksum compared to the registry).
- **Permissions:** —
- **AI responsibility:** —
- **Human responsibility:** —
- **Acceptance criteria:** The red-team suite (20 invoices) has 0 successful field or policy changes. AT-09 and AD-01 pass.

#### F-092 · AI evaluation harness (B1 vs B2)
`M1 · P0 · Source: N3, Autonomy §6 · Module: agent / quality`
- **Description:** A reproducible benchmark of 30 or more scenarios (requests, terms, balances, limits). B1 = deterministic rule baseline (EDF + templates). B2 = AI-assisted planning. Metrics: stablecoin saved (discounts minus late fees), on-time %, exceptions needed, tx count, fees, violations (must be 0), latency, model cost.
- **Problem solved:** Answers "why AI?" with data, honestly.
- **Users:** Team, judges.
- **Trigger:** CI / manual.
- **Input:** Scenario files with ground truth.
- **Business logic:** Same data, permissions and checks for B1 and B2. Dev and held-out sets are separated. Ground truth never appears in prompts.
- **Output:** Report (markdown + CSV).
- **Happy path:** Run → report.
- **Alternative flows:** —
- **Edge cases:** Non-determinism → N runs, report mean and spread.
- **Permissions:** —
- **AI responsibility:** Subject under test.
- **Human responsibility:** Write the scenarios and ground truth.
- **Acceptance criteria:** One-command run. The report includes cases where B2 is worse.

#### F-093 · AI decision log
`M1 · P0 · Source: Autonomy §5 · Module: agent / audit`
- **Description:** For every AI call: purpose, model and version, prompt template version, input references (not raw secrets), tool calls, output, validation result, plannerSource, latency and cost.
- **Problem solved:** Traceability. "Why did the agent do this?"
- **Users:** Auditor, team.
- **Trigger:** Every LLM call.
- **Input:** —
- **Business logic:** Append-only. Linked to request and plan ids. PII redaction.
- **Output:** Log records.
- **Happy path:** —
- **Alternative flows:** —
- **Edge cases:** Logging failure → the planning call fails closed (no unlogged AI decisions).
- **Permissions:** Auditor and OrgAdmin read.
- **AI responsibility:** —
- **Human responsibility:** —
- **Acceptance criteria:** 100% of plans link to an AI or RULE_BASED log record.

#### F-094 · Model adapter & routing
`M1 · P1 · Source: NEW · Module: agent`
- **Description:** A provider-agnostic interface for LLM calls (structured output, tool calling, timeouts), with per-task model selection (e.g., a cheaper model for extraction, a stronger one for planning explanations) and a provider fallback.
- **Problem solved:** Vendor lock-in, cost, availability.
- **Users:** System.
- **Trigger:** Every LLM call.
- **Input:** Task type.
- **Business logic:** Routing table in config. Timeout → F-054 / manual path.
- **Output:** Model response.
- **Happy path:** —
- **Alternative flows:** Provider outage → secondary provider.
- **Edge cases:** Schema drift between providers → validation catches it.
- **Permissions:** —
- **AI responsibility:** —
- **Human responsibility:** —
- **Acceptance criteria:** Switching the provider requires only config changes. Contract tests run per provider.

### 3.10 Notifications

#### F-100 · In-app notifications
`M1 · P1 · Source: Q16 · Module: notification`
- **Description:** A notification center: approval needed, exception needed, payment done, needs review, pause, anomaly, low gas.
- **Problem solved:** Users act on time.
- **Users:** All, by role.
- **Trigger:** Domain events.
- **Input:** Event.
- **Business logic:** Event-to-recipient routing by role. Read/unread state.
- **Output:** Notifications.
- **Happy path:** Event → bell badge → click → deep link.
- **Alternative flows:** —
- **Edge cases:** Duplicate events → dedup by event id.
- **Permissions:** Role-scoped.
- **AI responsibility:** None.
- **Human responsibility:** Act.
- **Acceptance criteria:** Every routed event type has a test. No cross-tenant leakage.

#### F-101 · Telegram notifications with deep links
`M1 · P2 · Source: N7, Q16 · Module: notification`
- **Description:** A Telegram bot linked per user. It sends the same events with a deep link to the web app. **No signing in Telegram.**
- **Problem solved:** Fast reaction away from the desk.
- **Users:** Opt-in users.
- **Trigger:** Domain events.
- **Input:** Linked chat id.
- **Business logic:** One-time code linking. Minimal content (no full addresses or amounts unless the user opts in).
- **Output:** Telegram messages.
- **Happy path:** "Invoice B needs an exception → open."
- **Alternative flows:** Unlink.
- **Edge cases:** Bot blocked → mark the channel inactive.
- **Permissions:** Self.
- **AI responsibility:** None.
- **Human responsibility:** Act in the app.
- **Acceptance criteria:** A message arrives within 10 seconds of the event in the demo. No action can be completed from Telegram.

#### F-102 · Email notifications
`Later · Source: Q16 · Module: notification`
- **Description:** Email channel for the same events, plus digests.
- **Problem solved:** Reach users without the app open.
- **Users:** All.
- **Trigger:** Events or daily digest.
- **Input:** Email.
- **Business logic:** Templates; unsubscribe per category (except security events).
- **Output:** Emails.
- **Happy path:** —
- **Alternative flows:** Digest mode.
- **Edge cases:** Bounces.
- **Permissions:** Self.
- **AI responsibility:** None.
- **Human responsibility:** —
- **Acceptance criteria:** Security events cannot be unsubscribed.

#### F-103 · Outbound webhooks
`Later · Source: Q16 · Module: integration`
- **Description:** Signed webhooks for events to customer systems.
- **Problem solved:** Integration.
- **Users:** Integrators.
- **Trigger:** Events.
- **Input:** Endpoint, secret.
- **Business logic:** HMAC signature, retries with backoff, event ids.
- **Output:** POSTs.
- **Happy path:** —
- **Alternative flows:** Replay from the dashboard.
- **Edge cases:** Endpoint down → retry → dead-letter.
- **Permissions:** OrgAdmin.
- **AI responsibility:** None.
- **Human responsibility:** —
- **Acceptance criteria:** Signature verification documented and tested.

#### F-104 · Slack / Lark / WeCom notifications
`Later · Source: Q16 · Module: notification`
- **Description:** Chat-platform channels with deep links.
- **Problem solved:** Team workflows (including China-market chat tools).
- **Users:** Teams.
- **Trigger:** Events.
- **Input:** Workspace connection.
- **Business logic:** Same as F-101.
- **Output:** Messages.
- **Happy path:** —
- **Alternative flows:** —
- **Edge cases:** —
- **Permissions:** OrgAdmin connects.
- **AI responsibility:** None.
- **Human responsibility:** —
- **Acceptance criteria:** Parity with the Telegram event set.

#### F-105 · Notification preferences
`Later · Source: NEW · Module: notification`
- **Description:** Per-user channel and category preferences, and quiet hours.
- **Problem solved:** Noise.
- **Users:** All.
- **Trigger:** Settings.
- **Input:** Preferences.
- **Business logic:** Security and approval-SLA events always go to at least one channel.
- **Output:** Preferences.
- **Happy path:** —
- **Alternative flows:** —
- **Edge cases:** —
- **Permissions:** Self.
- **AI responsibility:** None.
- **Human responsibility:** —
- **Acceptance criteria:** Mandatory categories cannot be fully muted.

### 3.11 Compliance

#### F-110 · Payee sanctions / blocklist screening
`M1 · P1 · Source: S6, Q17 · Module: compliance`
- **Description:** Screen payee addresses at registration and before each PAY against a screening provider. M1 uses a labelled fixture built from a public sanctions list sample plus a custom blocklist.
- **Problem solved:** Paying sanctioned or known-malicious addresses.
- **Users:** System, Owner.
- **Trigger:** Payee registration. Pre-PAY.
- **Input:** Address.
- **Business logic:** Provider adapter interface `screen(address) → {result, source, checkedAt}`. A hit → BLOCK (BR-085). Provider down → fail closed for registration; for PAY, use a recent cached result within its TTL, otherwise block.
- **Output:** Screening record.
- **Happy path:** Clean → continue.
- **Alternative flows:** Hit → BLOCK, and the Owner is notified.
- **Edge cases:** A false positive needs manual override with justification (Later; M1 is block only).
- **Permissions:** System.
- **AI responsibility:** None.
- **Human responsibility:** Review hits.
- **Acceptance criteria:** A test with a blocklisted address cannot be registered or paid. The fixture is labelled "TEST DATA".

#### F-111 · KYB onboarding
`Later · Source: Q17 · Module: compliance`
- **Description:** Business verification of the organization through a provider before activating a mainnet treasury.
- **Problem solved:** Regulatory onboarding.
- **Users:** OrgAdmin.
- **Trigger:** Activating mainnet.
- **Input:** Company documents.
- **Business logic:** Provider adapter. Status gates mainnet activation.
- **Output:** KYB status.
- **Happy path:** Submit → approved.
- **Alternative flows:** Manual review.
- **Edge cases:** Expiry and re-verification.
- **Permissions:** OrgAdmin.
- **AI responsibility:** None.
- **Human responsibility:** Provide documents.
- **Acceptance criteria:** A mainnet treasury cannot activate without KYB approval.

#### F-112 · Travel Rule support
`Later · Source: Q17 · Module: compliance`
- **Description:** Exchange originator and beneficiary information for qualifying transfers through a Travel Rule protocol provider, where applicable.
- **Problem solved:** Regulatory requirement in some jurisdictions.
- **Users:** System.
- **Trigger:** PAY above the threshold to a VASP-hosted address.
- **Input:** Party data.
- **Business logic:** Provider adapter. Threshold rules per jurisdiction.
- **Output:** Travel Rule record.
- **Happy path:** —
- **Alternative flows:** Self-hosted wallet → attestation path.
- **Edge cases:** Counterparty VASP unreachable → hold.
- **Permissions:** —
- **AI responsibility:** None.
- **Human responsibility:** —
- **Acceptance criteria:** Defined with the chosen provider.

#### F-113 · Data minimization
`M1 · P0 · Source: Use-Case §2, S6 · Module: compliance / platform`
- **Description:** Only hashes and commitments (invoice hash, fingerprint) go on-chain. Invoice files and vendor personal data stay in private storage. LLM calls send the minimum content needed, with provider settings that do not retain data where available.
- **Problem solved:** Privacy, and immutability risks on-chain.
- **Users:** System.
- **Trigger:** Always.
- **Input:** —
- **Business logic:** Field-level classification (Public / Internal / Confidential / Secret). Encryption at rest for Confidential data. Logs are redacted.
- **Output:** —
- **Happy path:** —
- **Alternative flows:** —
- **Edge cases:** —
- **Permissions:** —
- **AI responsibility:** —
- **Human responsibility:** —
- **Acceptance criteria:** A review of contract events and calldata finds no PII. A log redaction test passes.

#### F-114 · Data retention & residency policies
`Later · Source: Q17 · Module: compliance / platform`
- **Description:** Configurable retention periods, deletion workflows, and region pinning for data storage.
- **Problem solved:** GDPR/PDPL-type obligations.
- **Users:** OrgAdmin, PlatformAdmin.
- **Trigger:** Policy, or a deletion request.
- **Input:** Policy.
- **Business logic:** Audit evidence is retained per legal minimum. Deletion leaves on-chain hashes (non-reversible, no PII).
- **Output:** —
- **Happy path:** —
- **Alternative flows:** —
- **Edge cases:** A legal hold overrides deletion.
- **Permissions:** OrgAdmin.
- **AI responsibility:** None.
- **Human responsibility:** —
- **Acceptance criteria:** Deletion workflow is tested. Region pinning is enforced at the storage layer.

### 3.12 Audit & Evidence

#### F-120 · Hash-chained audit log & on-chain events
`M1 · P0 · Source: S6, GA p.14 · Module: audit`
- **Description:** An append-only audit log of every user action, state transition, validation decision, AI decision and transaction. Each record includes the hash of the previous record. Contracts emit events for every authority change and execution.
- **Problem solved:** Tamper-evident traceability.
- **Users:** Auditor, OrgAdmin.
- **Trigger:** Every action.
- **Input:** Event.
- **Business logic:** `hash_i = H(record_i ‖ hash_{i-1})`. Daily anchor (optional, Later: publish the root on-chain).
- **Output:** Audit records.
- **Happy path:** —
- **Alternative flows:** —
- **Edge cases:** A write failure fails the action closed for financial actions.
- **Permissions:** Read: Auditor, OrgAdmin. No one can update or delete.
- **AI responsibility:** —
- **Human responsibility:** —
- **Acceptance criteria:** A verification script detects any modified record.

#### F-121 · Evidence bundle export
`M1 · P0 · Source: GA p.39, AT §6 · Module: audit`
- **Description:** Per request or scenario, a JSON bundle: environment, chainId, contracts, approval, policy version, plan, planHash, snapshot refs, validator decisions, plannerSource, attestation, txHashes, receipts, post-state, verification and remaining limitations.
- **Problem solved:** Competition "execution evidence" and enterprise audit.
- **Users:** Auditor, Finance, team.
- **Trigger:** Manual export, or scenario runner.
- **Input:** Request id.
- **Business logic:** Assemble from stored records. Fixtures are labelled. **Never** includes fabricated hashes.
- **Output:** JSON (+ README).
- **Happy path:** Export → file.
- **Alternative flows:** Bulk export per period.
- **Edge cases:** A pre-broadcast block has no tx hash → include the validator log and the contract test reference instead.
- **Permissions:** Auditor, Finance, OrgAdmin.
- **AI responsibility:** —
- **Human responsibility:** —
- **Acceptance criteria:** The bundle validates against its JSON schema. Every hash resolves on the explorer.

#### F-122 · Coverage & uncertainty labelling
`M1 · P1 · Source: GA p.5 · Module: audit / UX`
- **Description:** Every assessment, snapshot and status carries `coverage: COMPLETE_WITHIN_SCOPE | PARTIAL | UNKNOWN` plus the missing data. The UI uses precise wording: "Pay requested; awaiting confirmation", not "Paid".
- **Problem solved:** Prevents false "safe" or "done" signals.
- **Users:** All.
- **Trigger:** Everywhere.
- **Input:** —
- **Business logic:** Missing required data → never ALLOW. UI copy rules (GA p.32).
- **Output:** Labels.
- **Happy path:** —
- **Alternative flows:** —
- **Edge cases:** —
- **Permissions:** —
- **AI responsibility:** —
- **Human responsibility:** —
- **Acceptance criteria:** A UI copy checklist is reviewed. No "safe"/"done" label appears without a verified state.

### 3.13 User Experience

#### F-130 · Treasury dashboard
`M1 · P0 · Source: N5 · Module: web`
- **Description:** Per-treasury overview: balances per wallet versus buffer and target, today's budget used versus limit, coverage status, mandate state (Active/Paused), queue counts (awaiting approval, scheduled, needs review), runway (F-058) and recent activity.
- **Problem solved:** One glance at treasury health.
- **Users:** All roles.
- **Trigger:** Open the app.
- **Input:** API state.
- **Business logic:** Amounts are rendered from base units. Test assets are labelled. Uncertain values are marked.
- **Output:** Dashboard.
- **Happy path:** —
- **Alternative flows:** Empty state → onboarding checklist.
- **Edge cases:** Data stale → banner.
- **Permissions:** Role-scoped views.
- **AI responsibility:** None (may show the Copilot entry point).
- **Human responsibility:** —
- **Acceptance criteria:** Usable at 1280 px and 390 px widths. Every value matches the API.

#### F-131 · Approval inbox with diff & flags
`M1 · P0 · Source: N5, N1 · Module: web`
- **Description:** A list of requests awaiting approval. The detail view shows the document next to the extracted fields, the diff against vendor history, flags with evidence, the confirmed terms, and a "Sign approval" button (wallet EIP-712).
- **Problem solved:** Fast, informed approvals (P3).
- **Users:** Approver.
- **Trigger:** Requests in AwaitingApproval.
- **Input:** Request plus flags.
- **Business logic:** High-severity flags need a checkbox acknowledgment before signing. Maker-checker is enforced.
- **Output:** Signed approval or rejection.
- **Happy path:** Open → review → sign.
- **Alternative flows:** Reject with a reason.
- **Edge cases:** Wallet on the wrong chain → prompt to switch. Signature rejected in the wallet → nothing changes.
- **Permissions:** Approver.
- **AI responsibility:** Recommend (flags).
- **Human responsibility:** Decide.
- **Acceptance criteria:** Cannot sign with unacknowledged high flags. The typed data displayed equals the typed data signed.

#### F-132 · Plan cards & live execution timeline
`M1 · P0 · Source: N5 · Module: web`
- **Description:** For each planning cycle: plan cards (order, amounts, refills, expected savings, planner source AI/RULE) and a "Why?" panel (reason codes from the validator plus the AI explanation, clearly separated). A live timeline per step: submitted → pending → confirmed, with explorer links and verification results.
- **Problem solved:** Explainability and real-time feedback.
- **Users:** All.
- **Trigger:** Planning or execution events (push via SSE/WebSocket).
- **Input:** Plan and operation events.
- **Business logic:** Validator reasons are shown as authoritative. AI text is labelled "AI explanation".
- **Output:** UI.
- **Happy path:** Watch the payment happen live.
- **Alternative flows:** —
- **Edge cases:** Unknown status → explicit "checking chain…".
- **Permissions:** Read for all roles.
- **AI responsibility:** Recommend (explanation).
- **Human responsibility:** —
- **Acceptance criteria:** Events appear within 2 seconds of backend state changes. Explorer links are correct per chain.

#### F-133 · Reconciliation view
`M1 · P0 · Source: UC-03 · Module: web`
- **Description:** A table of requests ↔ transactions ↔ fees ↔ classification ↔ reconciliation status, with filters, a "Mark matched" action, discrepancy notes and export (F-073).
- **Problem solved:** P5.
- **Users:** Finance, Auditor.
- **Trigger:** Navigation.
- **Input:** Reconciliation records.
- **Business logic:** —
- **Output:** UI and actions.
- **Happy path:** Filter "Paid, not matched" → verify → mark.
- **Alternative flows:** —
- **Edge cases:** —
- **Permissions:** Finance marks. Auditor reads.
- **AI responsibility:** None.
- **Human responsibility:** Mark matched.
- **Acceptance criteria:** Totals per period equal the export.

#### F-134 · Mandate & payee management UI
`M1 · P0 · Source: UC-01 · Module: web`
- **Description:** Forms for the mandate (with a human-readable summary and diff against the active version), and a payee registry UI (status, cooling countdown, screening result). Owner signing flows.
- **Problem solved:** Safe configuration by non-developers.
- **Users:** Owner. Others read.
- **Trigger:** Navigation.
- **Input:** —
- **Business logic:** F-020, F-021, F-022.
- **Output:** Signed transactions.
- **Happy path:** Edit → see the diff → sign.
- **Alternative flows:** —
- **Edge cases:** Pending activation shown clearly.
- **Permissions:** Owner writes.
- **AI responsibility:** None.
- **Human responsibility:** Decide.
- **Acceptance criteria:** The diff shows every changed field in base units and in display units.

#### F-135 · Exception & review console
`M1 · P0 · Source: UC-04, UC-06 · Module: web`
- **Description:** A UI for F-082 items and F-025 exception requests: reason codes, completed steps, the AI-drafted rationale, and role-specific actions (grant exception, retry, cancel, edit and re-approve).
- **Problem solved:** Humans resolve exceptions quickly and correctly.
- **Users:** Owner, Operator, Finance.
- **Trigger:** Open items.
- **Input:** Queue items.
- **Business logic:** Actions call the corresponding APIs. Nothing loosens policy implicitly.
- **Output:** Resolved items.
- **Happy path:** Over-cap → Owner signs the exception → item closes after execution.
- **Alternative flows:** —
- **Edge cases:** Item becomes stale (state changed) → refresh required before acting.
- **Permissions:** Per item type.
- **AI responsibility:** Recommend.
- **Human responsibility:** Resolve.
- **Acceptance criteria:** Each item type has its action wired and tested end-to-end.

### 3.14 Analytics & Monitoring

#### F-140 · Operational metrics
`M1 · P1 · Source: T6, AT §6 · Module: analytics`
- **Description:** Metrics: completion rate of valid requests, % paid before deadline, human interventions per request, operator minutes (self-reported or estimated), fees and transaction count, time from trigger to Paid (split into analysis / queue / chain / verification), and rejected requests by reason.
- **Problem solved:** Measurable value. Honest reporting.
- **Users:** Owner, Finance, team.
- **Trigger:** Continuous, plus a report page.
- **Input:** Event store.
- **Business logic:** Rejected and blocked requests are reported, never hidden.
- **Output:** Dashboard and CSV.
- **Happy path:** —
- **Alternative flows:** —
- **Edge cases:** —
- **Permissions:** Owner, Finance, Auditor.
- **AI responsibility:** None.
- **Human responsibility:** —
- **Acceptance criteria:** Metric definitions are documented and computed from raw events (reproducible).

#### F-141 · Savings report
`M1 · P1 · Source: N3 · Module: analytics`
- **Description:** Discounts captured and late fees avoided versus the B1 counterfactual for executed batches, plus the benchmark results.
- **Problem solved:** Shows the AI's value in money.
- **Users:** Owner, Finance, judges.
- **Trigger:** After batches; report page.
- **Input:** Executed schedules, terms, B1 simulation.
- **Business logic:** Counterfactual computed with the same constraints. The methodology is displayed.
- **Output:** Report.
- **Happy path:** "This month: +X USDC vs baseline."
- **Alternative flows:** —
- **Edge cases:** Negative savings → shown honestly.
- **Permissions:** Owner, Finance.
- **AI responsibility:** None.
- **Human responsibility:** —
- **Acceptance criteria:** The numbers are reproducible from stored data.

#### F-142 · System observability
`M1 · P1 · Source: NEW · Module: platform`
- **Description:** Structured logs with correlation ids (request/plan/operation), metrics (queue depth, RPC errors, LLM latency and cost, transaction states), traces across API → worker → signer → chain, error tracking, and alerts.
- **Problem solved:** Operating and debugging the system.
- **Users:** Team, PlatformAdmin.
- **Trigger:** Always.
- **Input:** —
- **Business logic:** Logs are redacted (F-113).
- **Output:** Dashboards and alerts.
- **Happy path:** —
- **Alternative flows:** —
- **Edge cases:** —
- **Permissions:** Team.
- **AI responsibility:** —
- **Human responsibility:** —
- **Acceptance criteria:** One request can be traced end-to-end by its id.

### 3.15 Admin & Platform

#### F-150 · Platform admin: tenant management
`Later · Source: Q13 · Module: admin`
- **Description:** PlatformAdmin console: list and suspend tenants, view health, support impersonation (read-only, audited, consent-based).
- **Problem solved:** Operating a multi-tenant SaaS.
- **Users:** PlatformAdmin.
- **Trigger:** —
- **Input:** —
- **Business logic:** PlatformAdmin can never sign or move customer funds (no keys).
- **Output:** —
- **Happy path:** —
- **Alternative flows:** —
- **Edge cases:** —
- **Permissions:** PlatformAdmin.
- **AI responsibility:** None.
- **Human responsibility:** —
- **Acceptance criteria:** Every admin action is audited. No fund-moving capability exists.

#### F-151 · Platform configuration (chains, RPC, assets)
`M1 · P1 · Source: O5 · Module: admin / platform`
- **Description:** Configuration of supported chains (chainId, RPC endpoints with fallbacks, confirmation depth, explorer URL), contract deployment addresses per chain, the global asset registry, and test/production flags.
- **Problem solved:** Removes hard-coded network values.
- **Users:** PlatformAdmin (M1: config files + a seed script).
- **Trigger:** Deploy.
- **Input:** Config.
- **Business logic:** Validated at startup. Deployment manifest checked into the repo.
- **Output:** Config.
- **Happy path:** —
- **Alternative flows:** —
- **Edge cases:** A misconfigured chainId → refuse to start.
- **Permissions:** PlatformAdmin.
- **AI responsibility:** None.
- **Human responsibility:** —
- **Acceptance criteria:** Startup fails fast on invalid config.

#### F-152 · Billing & subscriptions
`Later · Source: Q22 · Module: admin`
- **Description:** Plans, usage metering (requests paid, volume), invoicing to customers, payment collection.
- **Problem solved:** Commercialization.
- **Users:** OrgAdmin, PlatformAdmin.
- **Trigger:** Billing cycle.
- **Input:** Usage.
- **Business logic:** Metering from the event store. Never deducts fees from customer treasuries automatically.
- **Output:** Customer invoices.
- **Happy path:** —
- **Alternative flows:** —
- **Edge cases:** —
- **Permissions:** —
- **AI responsibility:** None.
- **Human responsibility:** —
- **Acceptance criteria:** Usage numbers reconcile with the event store.

### 3.16 Delivery & Quality

#### F-160 · One-command local environment & seeded scenarios
`M1 · P1 · Source: T7 · Module: devex`
- **Description:** `docker compose up` (or a `make dev` equivalent) starts the database, API, worker, web, an Anvil chain with deployed contracts and Safes, and seeded orgs, payees and invoices.
- **Problem solved:** Reproducibility for judges and developers.
- **Users:** Developers, judges.
- **Trigger:** —
- **Input:** —
- **Business logic:** —
- **Output:** Running stack.
- **Happy path:** One command → UI at localhost.
- **Alternative flows:** Testnet profile.
- **Edge cases:** —
- **Permissions:** —
- **AI responsibility:** —
- **Human responsibility:** —
- **Acceptance criteria:** A fresh clone reaches a working demo in 15 minutes or less by following the README.

#### F-161 · CI pipeline
`M1 · P1 · Source: T7 · Module: devex`
- **Description:** On PR: lint, typecheck, unit tests, Foundry tests (including fuzz/invariant), static analysis, integration tests against Anvil, and build.
- **Problem solved:** Quality gate.
- **Users:** Developers.
- **Trigger:** PR / push.
- **Input:** —
- **Business logic:** Required checks on `main`.
- **Output:** Status checks.
- **Happy path:** —
- **Alternative flows:** —
- **Edge cases:** —
- **Permissions:** —
- **AI responsibility:** —
- **Human responsibility:** —
- **Acceptance criteria:** Branch protection requires green CI.

#### F-162 · Scenario runner & demo runbook
`M1 · P1 · Source: GA p.14, p.41 · Module: devex`
- **Description:** A CLI that resets the environment and runs named scenarios (happy path, over-cap, injected invoice, crash recovery, pause), emitting evidence bundles. Plus a step-by-step demo runbook.
- **Problem solved:** Reliable demos and evidence.
- **Users:** Team.
- **Trigger:** Manual.
- **Input:** Scenario name.
- **Business logic:** Runs only on allowlisted test chains (BR-095).
- **Output:** Logs and bundles.
- **Happy path:** `scenario run demo-main` → bundle.
- **Alternative flows:** —
- **Edge cases:** Mainnet chainId → refuse.
- **Permissions:** —
- **AI responsibility:** —
- **Human responsibility:** —
- **Acceptance criteria:** Each demo scene in the runbook maps to a scenario.

#### F-163 · Security test suites
`M1 · P0 · Source: S1, S5 · Module: quality`
- **Description:** Foundry unit, fuzz and invariant tests (at least 8 invariants: BR-001, BR-013, BR-022, BR-024, BR-030, BR-041, BR-062, and replay), a static-analysis report, contract-bypass tests (direct module calls), and a prompt-injection red-team set.
- **Problem solved:** Evidence for the Security criterion.
- **Users:** Team.
- **Trigger:** CI.
- **Input:** —
- **Business logic:** —
- **Output:** Reports.
- **Happy path:** —
- **Alternative flows:** —
- **Edge cases:** —
- **Permissions:** —
- **AI responsibility:** Subject under test (red-team).
- **Human responsibility:** —
- **Acceptance criteria:** All invariants hold over 10k fuzz runs. No high-severity static-analysis findings are left unaddressed or undocumented.

#### F-164 · Reliability run harness
`M1 · P1 · Source: T6 · Module: quality`
- **Description:** Runs the main scenario 30 times on Anvil and 10 or more times on testnet, and reports completion %, median latency, fees and failures.
- **Problem solved:** Evidence for the "stable, repeatable" part of Task Completion.
- **Users:** Team.
- **Trigger:** Manual / nightly.
- **Input:** —
- **Business logic:** Failures are categorized, never dropped.
- **Output:** Report.
- **Happy path:** —
- **Alternative flows:** —
- **Edge cases:** —
- **Permissions:** —
- **AI responsibility:** —
- **Human responsibility:** —
- **Acceptance criteria:** The report is committed to `docs/evidence/`.
