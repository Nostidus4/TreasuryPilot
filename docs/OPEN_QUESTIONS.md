# TreasuryPilot: Open Questions

**Status:** Open · **Date:** 2026-10-10

Points that are not yet clear enough to specify without guessing. Each has a recommendation, and the recommendation is used as a **working assumption** until the team answers. Business questions must be resolved at **gate G1**. Questions tagged *(Phase 3)* will be resolved in architecture ADRs at **gate G2**.

O1–O8 from the source docs are **closed** by decision Q8: their proposed options are now BR defaults (BR-021, BR-032/033, BR-040, BR-052, BR-055, BR-080, BR-081).

| ID | Question | Why it matters | Affects | Options | BA recommendation |
|---|---|---|---|---|---|
| OQ-01 | What execution evidence does the published checklist require, and which network does our team use? | Keep the official requirement separate from team assumptions. | NFR-CMP-01, F-151, submission item 06 | Real on-chain transaction hashes; network is unspecified in the checklist. | Use Ethereum Sepolia under ADR-012/019 and NFR-CMP-01. Organizer clarification is optional and does not gate this work. See the source review below. |
| OQ-02 | Which **chain** for M1? *(Phase 3)* | Safe availability, testnet USDC faucet, EAS availability, RPC reliability, explorer. | F-010, F-013, F-074, F-151 | Base Sepolia; Ethereum Sepolia; Arbitrum Sepolia | **Resolved (PH-1, 2026-10-11): Ethereum Sepolia** (ADR-012); DOM-001 records the infrastructure verification. Base Sepolia is no longer the recommendation. |
| OQ-03 | Which **stablecoin** for M1: Circle testnet USDC or a team-deployed `tUSDC`? | Realism versus control (we can't mint Circle's token freely). | F-013, demo | (a) Circle testnet USDC; (b) tUSDC | (a) if the faucet gives enough for 40+ runs; otherwise (b), clearly labelled. |
| OQ-04 | **Cooling-period** duration for production and demo. | Security versus friction. | F-022, BR-017 | 24h / 48h / 72h; demo 5 min | 24h production (configurable 1h–7d); 5 min demo. |
| OQ-05 | Demo **limit values** (per request, daily, refill, buffer, target). | Demo narrative needs an over-cap invoice, and a buffer that matters. | F-020, F-023, F-024 | Use source YAML (2,000 / 10,000 / 2,500 / 12,000) | Use the source YAML values, scaled to the faucet budget. |
| OQ-06 | Default **lead time** for the execution window (how long before the deadline or the discount date the trigger fires). | Determines when the agent acts. Too late risks a miss; too early wastes liquidity. | F-060, F-052 | Fixed (e.g., 24h); per-vendor; computed from confirmation time | Global default of 24h before the deadline or the discount date, configurable per treasury. Demo: minutes. |
| OQ-07 | Allow **solo mode** (one person as creator and approver) for single-founder companies? | Maker-checker would block tiny teams. | F-005, BR-005 | (a) never; (b) Owner-enabled with flags; (c) always for orgs with one member | (b): Owner-enabled, visibly flagged, audited. |
| OQ-08 | If an Approver is **removed** after signing but before execution, is their approval still valid? | Security versus disruption. | F-038, FR-318 | (a) valid (point-in-time); (b) invalid (current set) | (b) invalid: the contract checks the current approver set, which is safer. |
| OQ-09 | **Auto-match** reconciliation when all evidence matches, or always require Finance to click? | Workload versus control. | F-072 | (a) always manual; (b) auto with an org setting | (b), default off. |
| OQ-10 | Do the AI vendor-history **anomaly thresholds** (amount outlier k·MAD) need per-org tuning? | False positives. | F-036 | Fixed k=3; per-org | Fixed k=3 in M1; per-org Later. |
| OQ-11 | **LLM provider** and data policy (no-retention, region). *(Phase 3)* | Privacy, cost and quality; China-market considerations. | F-094, NFR-PRIV-03 | Anthropic Claude; others behind the adapter | Decide in an ADR; design is provider-agnostic. |
| OQ-12 | **Chart-of-accounts** mapping for journal export. | Accounting usefulness. | F-073 | Generic (Expense / Wallet / Transfer / Fee); configurable mapping | Generic default plus a per-org mapping table. |
| OQ-13 | **Who can propose payees**: Operator only, or also OrgAdmin? | Workflow. | F-022 | Operator; OrgAdmin; both | Both may propose; only the Owner activates. |
| OQ-14 | What **auth mechanism** for app login? *(Phase 3)* | Security, effort. | F-001 | Managed (e.g., hosted auth); self-hosted library | Decide in an ADR. |
| OQ-15 | Is a **real swap** needed in the M1 demo at all, given a single stablecoin (swap only buys gas)? | Effort versus demo value; testnet DEX liquidity. | F-064 | (a) skip; (b) labelled test router; (c) testnet DEX | (b), P2, only if time allows. Executor gas is prefunded either way. |
| OQ-16 | **Invoice deadline semantics**: does the deadline mean "confirmed on-chain by" or "submitted by"? | Scheduling margin. | F-052, F-060 | Confirmed-by; submitted-by | Confirmed-by, using the chain's expected confirmation time as margin. |
| OQ-17 | Which **notification events** may include amounts or addresses on Telegram? | Privacy on third-party chat. | F-101 | None; opt-in; all | Opt-in per user; default minimal content. |
| OQ-18 | How many **customer interviews** can be done before submission (H1–H7)? | Validates the problem in the deck. | Overview, deck | 0 / 2–3 / 5 | Aim for 2–3 short interviews; report the true number. |

---

## Resolution log

### Gate G1 — 2026-10-10 (approved by project lead)

| ID | Resolution |
|---|---|
| OQ-04 | **Accepted.** Cooling period: 24h in production (configurable from 1h to 7d), 5 min in the demo. |
| OQ-05 | **Accepted.** Demo limits use the source YAML values (per-request 2,000; daily 10,000; refill 2,500/12,000), scaled to the faucet budget if needed. |
| OQ-06 | **Accepted.** Execution window opens 24h before the deadline or the discount date, configurable per treasury; minutes in the demo. |
| OQ-07 | **Accepted.** Solo mode is Owner-enabled, flagged and audited. |
| OQ-08 | **Accepted.** Approvals are checked against the *current* approver set at PAY time. |
| OQ-09 | **Accepted.** Auto-match is an org setting, default off. |
| OQ-10 | **Accepted.** Fixed k=3 MAD in M1; per-org tuning `Later`. |
| OQ-12 | **Accepted.** Generic account mapping plus a per-org mapping table. |
| OQ-13 | **Accepted.** Operator and OrgAdmin may propose payees; only the Owner activates. |
| OQ-15 | **Accepted.** Labelled test router, P2. Executor gas is prefunded either way. |
| OQ-16 | **Accepted.** A deadline means "confirmed on-chain by". |
| OQ-17 | **Accepted.** Telegram shows amounts and addresses only if the user opts in. |
| OQ-18 | **Accepted.** Aim for 2–3 interviews; report the true number. |
| OQ-01 | **Historical G1 uncertainty, superseded by the source review on 2026-10-14.** The published checklist requires real on-chain transaction hashes; there is no mandatory email gate. |
| OQ-02, OQ-03, OQ-11, OQ-14 | **Deferred to Phase 3 (gate G2).** |

### Phase 3 interview — 2026-10-11

| ID | Resolution |
|---|---|
| OQ-02 | **Accepted (anh Phúc, 2026-10-11).** Ethereum Sepolia (ADR-012). |
| OQ-03 | **Accepted (anh Phúc, 2026-10-11).** tUSDC for the main demo and automated runs; one evidence run with Circle USDC on Sepolia with limits ÷ 100 (faucet: 10 USDC/day public, 10×20 USDC/day developer console). |
| OQ-11 | **Resolved:** Anthropic Claude via the SDK, with an adapter (decision Q27). |
| OQ-14 | **Resolved:** in-house magic link + SIWE (decision Q33, ADR-009). |
| OQ-01 | **Team interpretation recorded by anh Phúc (2026-10-11):** use public testnet evidence. This is not an organizer reply. The source review below records the published wording and optional clarification. |

### OQ-01 / DOM-003 source review — 2026-10-14

Source: [PBCSF Appendix 2 — Problem Description and Competition Rules for
International Track](https://www.its.ac.id/international/wp-content/uploads/sites/66/2026/10/PBCSF-Appendix-2-Problem-Description-and-Competition-Rules-for-International-Track.pdf),
page 3, Submission checklist, item 06 (Execution evidence). This is the published
rules document redistributed by ITS Global Engagement, not our internal assessment.

- **Published requirement:** for the on-chain topic, “real on-chain transaction
  hashes”. The checklist does not specify testnet/mainnet and does not require an
  organizer email or written confirmation.
- **Team working choice:** Ethereum Sepolia per ADR-012/019; M1 remains testnet-only
  under NFR-CMP-01. The unspecified network wording is not an explicit guarantee
  that organizers accept testnet; no organizer reply is claimed here.
- **Implementation evidence:** produce actual on-chain actions and retain their
  genuine transaction hashes. The team's evidence bundle should include chain ID,
  explorer links and receipts/events linking the transaction to the demonstrated
  action. Those supporting checks are team traceability choices, not extra quoted
  submission requirements. An offline-computed hash or local simulation alone
  must not be presented as a publicly executed transaction.
- **Optional clarification:** the team may ask the organizer if it wants further
  certainty. Sending an email, waiting for a reply or recording a missing reply by
  14/10 is not a completion criterion for DOM-003 and does not block development
  or submission. No email was sent by this source-review work.
- **If requirements change:** record the actual organizer response and open a
  reviewed ADR/scope decision. Do not silently switch networks or override the
  testnet-only project requirement.

This resolves the documentation task by recording the actual requirement and
assumption boundary. Public deployment and transaction-evidence collection remain
separate work under DOM-001/002 and the relevant execution tickets.
