# Master Backlog

Generated from `planning/tools/data` by `planning/tools/gen_issues.py`. Do not edit by hand.

**Status legend:** Draft → Needs Discussion → Ready for Review → Accepted → Ready for Assignment → Assigned → In Progress → Review → Done.
Gate G3 accepted by the project lead on 2026-10-11: M1 tickets are **Ready for Assignment**, Later tickets are **Accepted** (not scheduled). Nobody is assigned yet.

## Totals

| Phase | P0 | P1 | P2 | Total |
|---|---:|---:|---:|---:|
| M1 | 144 | 52 | 10 | 206 |
| Later | – | – | – | 38 |
| **All** | | | | **244** |

## Epics

| Epic | Module | Tickets (M1) | Tickets (Later) | Folder |
|---|---|---:|---:|---|
| M19 · Developer Experience & Quality | `devex` | 12 | 0 | [`issues/devex/`](issues/devex/) |
| M04 · Smart Contracts | `contracts` | 26 | 6 | [`issues/contracts/`](issues/contracts/) |
| M07 · Financial Engine (py-core) | `financial-engine` | 14 | 3 | [`issues/financial-engine/`](issues/financial-engine/) |
| M08 · Policy Engine & Attestation | `policy-engine` | 7 | 0 | [`issues/policy-engine/`](issues/policy-engine/) |
| M01 · Identity & Access | `identity` | 8 | 3 | [`issues/identity/`](issues/identity/) |
| M02 · Treasury & Chain Configuration | `treasury` | 8 | 2 | [`issues/treasury/`](issues/treasury/) |
| M03 · Mandate, Payees, Exceptions & Pause | `mandate` | 11 | 1 | [`issues/mandate/`](issues/mandate/) |
| M05 · Invoices & Payment Requests | `invoices` | 12 | 4 | [`issues/invoices/`](issues/invoices/) |
| M06 · Chain Reader & Tx Tracking | `chain-reader` | 6 | 0 | [`issues/chain-reader/`](issues/chain-reader/) |
| M09 · AI Agent | `agent` | 17 | 0 | [`issues/agent/`](issues/agent/) |
| M10 · Orchestration & Execution | `execution` | 14 | 4 | [`issues/execution/`](issues/execution/) |
| M11 · Verification & Reconciliation | `reconciliation` | 5 | 3 | [`issues/reconciliation/`](issues/reconciliation/) |
| M12 · Recovery & Exceptions | `recovery` | 7 | 0 | [`issues/recovery/`](issues/recovery/) |
| M13 · Notifications | `notifications` | 3 | 4 | [`issues/notifications/`](issues/notifications/) |
| M14 · Compliance | `compliance` | 3 | 4 | [`issues/compliance/`](issues/compliance/) |
| M15 · Audit & Evidence | `audit` | 4 | 1 | [`issues/audit/`](issues/audit/) |
| M16 · Web Application | `web` | 27 | 0 | [`issues/web/`](issues/web/) |
| M17 · Observability & Analytics | `observability` | 5 | 0 | [`issues/observability/`](issues/observability/) |
| M18 · Platform Admin & Billing | `admin` | 0 | 3 | [`issues/admin/`](issues/admin/) |
| M20 · Domain & Evidence (non-code) | `domain-evidence` | 17 | 0 | [`issues/domain-evidence/`](issues/domain-evidence/) |

## All tickets

| ID | Module | Epic | Issue | Features | Phase | Prio | Size | Cut | Dependency | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| DEV-001 | devex | M19 | [Initialize monorepo skeleton](issues/devex/001-initialize-monorepo-skeleton.md) | F-160 | M1 | P0 | M | A | — | Ready for Assignment |
| DEV-002 | devex | M19 | [Create Docker Compose stack (local profile)](issues/devex/002-create-docker-compose-stack-local-profile.md) | F-160 | M1 | P0 | M | A | DEV-001 | Ready for Assignment |
| DEV-003 | devex | M19 | [Add CI workflow for Python](issues/devex/003-add-ci-workflow-for-python.md) | F-161 | M1 | P1 | S | A | DEV-001 | Ready for Assignment |
| DEV-004 | devex | M19 | [Add CI workflow for contracts](issues/devex/004-add-ci-workflow-for-contracts.md) | F-161, F-163 | M1 | P1 | S | B | SC-001 | Ready for Assignment |
| DEV-005 | devex | M19 | [Add CI workflow for web and OpenAPI client drift](issues/devex/005-add-ci-workflow-for-web-and-openapi-client-drift.md) | F-161 | M1 | P1 | S | After submission | WEB-001 | Ready for Assignment |
| DEV-006 | devex | M19 | [Write seed script for the local environment](issues/devex/006-write-seed-script-for-the-local-environment.md) | F-160 | M1 | P1 | M | A | SC-016, TRS-004, MDT-003, INV-003 | Ready for Assignment |
| DEV-007 | devex | M19 | [Build scenario runner CLI](issues/devex/007-build-scenario-runner-cli.md) | F-162 | M1 | P1 | M | A | DEV-006, AUD-003 | Ready for Assignment |
| DEV-008 | devex | M19 | [Write the demo runbook](issues/devex/008-write-the-demo-runbook.md) | F-162 | M1 | P1 | S | A | DEV-007 | Ready for Assignment |
| DEV-009 | devex | M19 | [Build the reliability run harness](issues/devex/009-build-the-reliability-run-harness.md) | F-164 | M1 | P1 | S | After submission | DEV-007 | Ready for Assignment |
| DEV-010 | devex | M19 | [Add testnet profile and VM deployment](issues/devex/010-add-testnet-profile-and-vm-deployment.md) | F-160, F-151 | M1 | P1 | M | A | DEV-002, DOM-001, SC-016 | Ready for Assignment |
| DEV-011 | devex | M19 | [Enforce module boundaries with import-linter](issues/devex/011-enforce-module-boundaries-with-import-linter.md) | F-161 | M1 | P1 | S | After submission | DEV-001 | Ready for Assignment |
| SC-001 | contracts | M04 | [Set up the Foundry project with pinned dependencies](issues/contracts/001-set-up-the-foundry-project-with-pinned-dependencies.md) | F-163 | M1 | P0 | S | A | DEV-001 | Ready for Assignment |
| SC-002 | contracts | M04 | [Define module storage, structs, EIP-712 domain, errors and events](issues/contracts/002-define-module-storage-structs-eip-712-domain-errors-and-even.md) | F-021, F-038 | M1 | P0 | M | A | SC-001 | Ready for Assignment |
| SC-003 | contracts | M04 | [Implement mandate governance and versioning](issues/contracts/003-implement-mandate-governance-and-versioning.md) | F-021 | M1 | P0 | M | A | SC-021 | Ready for Assignment |
| SC-004 | contracts | M04 | [Implement the payee registry with cooling period](issues/contracts/004-implement-the-payee-registry-with-cooling-period.md) | F-022 | M1 | P0 | S | A | SC-003 | Ready for Assignment |
| SC-005 | contracts | M04 | [Implement approval signature verification](issues/contracts/005-implement-approval-signature-verification.md) | F-038 | M1 | P0 | M | A | SC-002 | Ready for Assignment |
| SC-006 | contracts | M04 | [Implement pay() core flow](issues/contracts/006-implement-pay-core-flow.md) | F-063 | M1 | P0 | M | A | SC-004, SC-005 | Ready for Assignment |
| SC-007 | contracts | M04 | [Implement per-request limits and UTC daily counters](issues/contracts/007-implement-per-request-limits-and-utc-daily-counters.md) | F-023 | M1 | P0 | M | A | SC-006 | Ready for Assignment |
| SC-008 | contracts | M04 | [Enforce minimum buffers on pay and refill](issues/contracts/008-enforce-minimum-buffers-on-pay-and-refill.md) | F-024 | M1 | P0 | S | A | SC-006 | Ready for Assignment |
| SC-009 | contracts | M04 | [Implement refill() bound to an approved request](issues/contracts/009-implement-refill-bound-to-an-approved-request.md) | F-062 | M1 | P0 | M | A | SC-005, SC-007, SC-008 | Ready for Assignment |
| SC-010 | contracts | M04 | [Implement pause, resume, revoke and guardian](issues/contracts/010-implement-pause-resume-revoke-and-guardian.md) | F-026 | M1 | P0 | S | A | SC-003 | Ready for Assignment |
| SC-011 | contracts | M04 | [Implement one-time exceptions via owner governance](issues/contracts/011-implement-one-time-exceptions-via-owner-governance.md) | F-025 | M1 | P1 | M | B | SC-007 | Ready for Assignment |
| SC-012 | contracts | M04 | [Add the duplicate-invoice fingerprint registry and owner override](issues/contracts/012-add-the-duplicate-invoice-fingerprint-registry-and-owner-ove.md) | F-037 | M1 | P0 | S | A | SC-006 | Ready for Assignment |
| SC-013 | contracts | M04 | [Write the contract acceptance test suite (AT cases)](issues/contracts/013-write-the-contract-acceptance-test-suite-at-cases.md) | F-163 | M1 | P0 | M | A | SC-009, SC-010, SC-012 | Ready for Assignment |
| SC-014 | contracts | M04 | [Write the invariant and fuzz suite](issues/contracts/014-write-the-invariant-and-fuzz-suite.md) | F-163 | M1 | P0 | M | A | SC-013, SC-022 | Ready for Assignment |
| SC-015 | contracts | M04 | [Run static analysis and write the findings report](issues/contracts/015-run-static-analysis-and-write-the-findings-report.md) | F-163 | M1 | P0 | S | A | SC-013 | Ready for Assignment |
| SC-016 | contracts | M04 | [Write deployment scripts and the deployments manifest](issues/contracts/016-write-deployment-scripts-and-the-deployments-manifest.md) | F-151 | M1 | P0 | M | A | SC-010, SC-021, DOM-001 | Ready for Assignment |
| SC-017 | contracts | M04 | [Publish EIP-712 golden vectors](issues/contracts/017-publish-eip-712-golden-vectors.md) | F-038, F-056 | M1 | P0 | S | A | SC-005 | Ready for Assignment |
| SC-018 | contracts | M04 | [Add the test router and swapForGas](issues/contracts/018-add-the-test-router-and-swapforgas.md) | F-064 | M1 | P2 | M | After submission | SC-009 | Ready for Assignment |
| SC-019 | contracts | M04 | [Register the attestation schema and add an attest helper](issues/contracts/019-register-the-attestation-schema-and-add-an-attest-helper.md) | F-074 | M1 | P1 | S | A | DOM-001 | Ready for Assignment |
| SC-020 | contracts | M04 | [Write direct-call bypass tests](issues/contracts/020-write-direct-call-bypass-tests.md) | F-163 | M1 | P0 | S | A | SC-013 | Ready for Assignment |
| SC-L01 | contracts | M04 | [Enforce reserves and execution holds on-chain](issues/contracts/l01-enforce-reserves-and-execution-holds-on-chain.md) | F-028 | Later | - | L | After submission | SC-014 | Accepted |
| SC-L02 | contracts | M04 | [Enforce n-of-m approval thresholds by amount band](issues/contracts/l02-enforce-n-of-m-approval-thresholds-by-amount-band.md) | F-029 | Later | - | L | After submission | SC-005 | Accepted |
| SC-L03 | contracts | M04 | [Add a production swap adapter with signed quotes](issues/contracts/l03-add-a-production-swap-adapter-with-signed-quotes.md) | F-065 | Later | - | L | After submission | SC-018 | Accepted |
| SC-L04 | contracts | M04 | [Verify plan attestations on-chain](issues/contracts/l04-verify-plan-attestations-on-chain.md) | F-056 | Later | - | M | After submission | SC-017 | Accepted |
| SC-L05 | contracts | M04 | [Support multiple stablecoins with per-asset limits](issues/contracts/l05-support-multiple-stablecoins-with-per-asset-limits.md) | F-015 | Later | - | M | After submission | SC-007 | Accepted |
| SC-L06 | contracts | M04 | [Allow refill paths between operational wallets](issues/contracts/l06-allow-refill-paths-between-operational-wallets.md) | F-059 | Later | - | M | After submission | SC-009 | Accepted |
| ENG-001 | financial-engine | M07 | [Create py-core money types and domain models](issues/financial-engine/001-create-py-core-money-types-and-domain-models.md) | F-013, F-051 | M1 | P0 | M | A | DEV-001 | Ready for Assignment |
| ENG-002 | financial-engine | M07 | [Implement the liquidity calculator](issues/financial-engine/002-implement-the-liquidity-calculator.md) | F-051 | M1 | P0 | M | A | ENG-001 | Ready for Assignment |
| ENG-003 | financial-engine | M07 | [Implement the refill decision table](issues/financial-engine/003-implement-the-refill-decision-table.md) | F-051 | M1 | P0 | S | A | ENG-002 | Ready for Assignment |
| ENG-004 | financial-engine | M07 | [Add property tests for buffer and limit safety](issues/financial-engine/004-add-property-tests-for-buffer-and-limit-safety.md) | F-051 | M1 | P0 | S | After submission | ENG-003 | Ready for Assignment |
| ENG-005 | financial-engine | M07 | [Model payment terms and their value function](issues/financial-engine/005-model-payment-terms-and-their-value-function.md) | F-035, F-052 | M1 | P0 | S | A | ENG-001 | Ready for Assignment |
| ENG-006 | financial-engine | M07 | [Implement the baseline scheduler B1 (earliest deadline first)](issues/financial-engine/006-implement-the-baseline-scheduler-b1-earliest-deadline-first.md) | F-052, F-092 | M1 | P0 | S | A | ENG-003, ENG-005 | Ready for Assignment |
| ENG-007 | financial-engine | M07 | [Implement the terms-aware scheduler with OR-Tools CP-SAT](issues/financial-engine/007-implement-the-terms-aware-scheduler-with-or-tools-cp-sat.md) | F-052 | M1 | P0 | L | A | ENG-006, ENG-012 | Ready for Assignment |
| ENG-008 | financial-engine | M07 | [Expose plan scoring and binding-constraint reporting](issues/financial-engine/008-expose-plan-scoring-and-binding-constraint-reporting.md) | F-052, F-053 | M1 | P0 | S | A | ENG-007 | Ready for Assignment |
| ENG-009 | financial-engine | M07 | [Implement invoice fingerprint normalization and hashing](issues/financial-engine/009-implement-invoice-fingerprint-normalization-and-hashing.md) | F-037 | M1 | P0 | S | A | ENG-001 | Ready for Assignment |
| ENG-010 | financial-engine | M07 | [Build EIP-712 typed data for payment approvals and attestations](issues/financial-engine/010-build-eip-712-typed-data-for-payment-approvals-and-attestati.md) | F-038, F-025, F-056 | M1 | P0 | M | A | SC-017, ENG-001 | Ready for Assignment |
| ENG-011 | financial-engine | M07 | [Implement the 7-day liquidity forecast](issues/financial-engine/011-implement-the-7-day-liquidity-forecast.md) | F-058 | M1 | P2 | S | After submission | ENG-003 | Ready for Assignment |
| ENG-L01 | financial-engine | M07 | [Plan refills from other operational wallets](issues/financial-engine/l01-plan-refills-from-other-operational-wallets.md) | F-059 | Later | - | M | After submission | ENG-007, SC-L06 | Accepted |
| ENG-L02 | financial-engine | M07 | [Add FX conversion and depeg checks for fiat invoices](issues/financial-engine/l02-add-fx-conversion-and-depeg-checks-for-fiat-invoices.md) | F-041 | Later | - | M | After submission | ENG-005 | Accepted |
| ENG-L03 | financial-engine | M07 | [Extend the scheduler to multiple assets](issues/financial-engine/l03-extend-the-scheduler-to-multiple-assets.md) | F-015 | Later | - | M | After submission | ENG-007 | Accepted |
| POL-001 | policy-engine | M08 | [Define the reason-code catalogue and decision model](issues/policy-engine/001-define-the-reason-code-catalogue-and-decision-model.md) | F-055 | M1 | P0 | S | A | ENG-001 | Ready for Assignment |
| POL-002 | policy-engine | M08 | [Validate approval, mandate and payee conditions](issues/policy-engine/002-validate-approval-mandate-and-payee-conditions.md) | F-055 | M1 | P0 | M | A | POL-001, ENG-010 | Ready for Assignment |
| POL-003 | policy-engine | M08 | [Validate limits, buffers, deadlines, coverage and unknown operations](issues/policy-engine/003-validate-limits-buffers-deadlines-coverage-and-unknown-opera.md) | F-055 | M1 | P0 | M | A | POL-002 | Ready for Assignment |
| POL-004 | policy-engine | M08 | [Add differential tests between validator and contract](issues/policy-engine/004-add-differential-tests-between-validator-and-contract.md) | F-055, F-163 | M1 | P0 | M | After submission | POL-003, SC-013 | Ready for Assignment |
| POL-005 | policy-engine | M08 | [Define canonical plan encoding and planHash](issues/policy-engine/005-define-canonical-plan-encoding-and-planhash.md) | F-056 | M1 | P1 | S | A | ENG-010 | Ready for Assignment |
| POL-006 | policy-engine | M08 | [Sign and verify EIP-712 plan attestations with the policy key](issues/policy-engine/006-sign-and-verify-eip-712-plan-attestations-with-the-policy-ke.md) | F-056 | M1 | P1 | S | A | POL-005 | Ready for Assignment |
| IDN-001 | identity | M01 | [Create identity database schema and migrations](issues/identity/001-create-identity-database-schema-and-migrations.md) | F-001–F-005 | M1 | P0 | S | A | DEV-002 | Ready for Assignment |
| IDN-002 | identity | M01 | [Implement magic-link login, sessions and CSRF](issues/identity/002-implement-magic-link-login-sessions-and-csrf.md) | F-001 | M1 | P0 | M | A | IDN-001 | Ready for Assignment |
| IDN-003 | identity | M01 | [Rate-limit authentication endpoints](issues/identity/003-rate-limit-authentication-endpoints.md) | F-001 | M1 | P0 | S | B | IDN-002 | Ready for Assignment |
| IDN-004 | identity | M01 | [Implement SIWE wallet linking](issues/identity/004-implement-siwe-wallet-linking.md) | F-002 | M1 | P0 | M | A | IDN-002 | Ready for Assignment |
| IDN-005 | identity | M01 | [Implement organization creation and onboarding checklist](issues/identity/005-implement-organization-creation-and-onboarding-checklist.md) | F-003 | M1 | P0 | S | A | IDN-002 | Ready for Assignment |
| IDN-006 | identity | M01 | [Implement RBAC dependencies and tenant isolation](issues/identity/006-implement-rbac-dependencies-and-tenant-isolation.md) | F-004 | M1 | P0 | M | A | IDN-005 | Ready for Assignment |
| IDN-007 | identity | M01 | [Implement invites and membership management](issues/identity/007-implement-invites-and-membership-management.md) | F-004 | M1 | P1 | M | After submission | IDN-006 | Ready for Assignment |
| IDN-008 | identity | M01 | [Implement the maker-checker service and solo mode](issues/identity/008-implement-the-maker-checker-service-and-solo-mode.md) | F-005 | M1 | P0 | S | A | IDN-006 | Ready for Assignment |
| IDN-L01 | identity | M01 | [Add MFA and step-up authentication](issues/identity/l01-add-mfa-and-step-up-authentication.md) | F-006 | Later | - | L | After submission | IDN-002 | Accepted |
| IDN-L02 | identity | M01 | [Add OIDC single sign-on](issues/identity/l02-add-oidc-single-sign-on.md) | F-007 | Later | - | L | After submission | IDN-006 | Accepted |
| IDN-L03 | identity | M01 | [Add SAML and SCIM provisioning](issues/identity/l03-add-saml-and-scim-provisioning.md) | F-007 | Later | - | L | After submission | IDN-L02 | Accepted |
| TRS-001 | treasury | M02 | [Create treasury and chain schema](issues/treasury/001-create-treasury-and-chain-schema.md) | F-010, F-013 | M1 | P0 | S | A | IDN-001 | Ready for Assignment |
| TRS-002 | treasury | M02 | [Load and validate platform chain configuration](issues/treasury/002-load-and-validate-platform-chain-configuration.md) | F-151 | M1 | P0 | S | A | TRS-001 | Ready for Assignment |
| TRS-003 | treasury | M02 | [Implement the asset registry with on-chain decimals check](issues/treasury/003-implement-the-asset-registry-with-on-chain-decimals-check.md) | F-013 | M1 | P0 | S | A | TRS-002, CHR-001 | Ready for Assignment |
| TRS-004 | treasury | M02 | [Implement treasury creation with Safe verification](issues/treasury/004-implement-treasury-creation-with-safe-verification.md) | F-010, F-011 | M1 | P0 | M | A | TRS-003, IDN-006 | Ready for Assignment |
| TRS-005 | treasury | M02 | [Read and snapshot Safe configuration](issues/treasury/005-read-and-snapshot-safe-configuration.md) | F-011 | M1 | P0 | S | A | TRS-004 | Ready for Assignment |
| TRS-006 | treasury | M02 | [Build the module deploy-and-enable Safe transaction](issues/treasury/006-build-the-module-deploy-and-enable-safe-transaction.md) | F-012 | M1 | P0 | M | A | TRS-004, SC-016, SC-021, MDT-009 | Ready for Assignment |
| TRS-007 | treasury | M02 | [Compute coverage and handle acknowledgment](issues/treasury/007-compute-coverage-and-handle-acknowledgment.md) | F-012 | M1 | P0 | M | A | TRS-005, TRS-006 | Ready for Assignment |
| TRS-008 | treasury | M02 | [Build a Safe deployment transaction from the UI](issues/treasury/008-build-a-safe-deployment-transaction-from-the-ui.md) | F-011 | M1 | P2 | S | After submission | TRS-004 | Ready for Assignment |
| TRS-L01 | treasury | M02 | [Support multiple treasuries with a consolidated view](issues/treasury/l01-support-multiple-treasuries-with-a-consolidated-view.md) | F-014 | Later | - | M | After submission | TRS-004 | Accepted |
| TRS-L02 | treasury | M02 | [Support multiple stablecoins per treasury](issues/treasury/l02-support-multiple-stablecoins-per-treasury.md) | F-015 | Later | - | M | After submission | TRS-L01, SC-L05 | Accepted |
| MDT-001 | mandate | M03 | [Create mandate, payee and exception schema](issues/mandate/001-create-mandate-payee-and-exception-schema.md) | F-020–F-026 | M1 | P0 | S | A | TRS-001 | Ready for Assignment |
| MDT-002 | mandate | M03 | [Validate mandate drafts and generate summary and diff](issues/mandate/002-validate-mandate-drafts-and-generate-summary-and-diff.md) | F-020 | M1 | P0 | M | A | MDT-001, ENG-001 | Ready for Assignment |
| MDT-003 | mandate | M03 | [Implement mandate activation and read-back](issues/mandate/003-implement-mandate-activation-and-read-back.md) | F-021 | M1 | P0 | M | A | MDT-002, MDT-009, TRS-006, CHR-003 | Ready for Assignment |
| MDT-004 | mandate | M03 | [Implement vendor and payee proposals with screening](issues/mandate/004-implement-vendor-and-payee-proposals-with-screening.md) | F-022 | M1 | P0 | M | A | MDT-001, CMP-001 | Ready for Assignment |
| MDT-005 | mandate | M03 | [Build payee registration and deactivation transactions and sync status](issues/mandate/005-build-payee-registration-and-deactivation-transactions-and-s.md) | F-022 | M1 | P0 | M | B | MDT-004, MDT-009, CHR-005 | Ready for Assignment |
| MDT-006 | mandate | M03 | [Implement one-time exception requests and owner grant transactions](issues/mandate/006-implement-one-time-exception-requests-and-owner-grant-transa.md) | F-025 | M1 | P1 | M | B | MDT-003, MDT-009, INV-010 | Ready for Assignment |
| MDT-007 | mandate | M03 | [Implement pause and resume (backend and transactions)](issues/mandate/007-implement-pause-and-resume-backend-and-transactions.md) | F-026 | M1 | P0 | M | A | MDT-003, MDT-009, EXE-013 | Ready for Assignment |
| MDT-008 | mandate | M03 | [Sync mandate expiry and status](issues/mandate/008-sync-mandate-expiry-and-status.md) | F-021 | M1 | P1 | S | After submission | MDT-003 | Ready for Assignment |
| MDT-L01 | mandate | M03 | [Configure threshold-based approval policies](issues/mandate/l01-configure-threshold-based-approval-policies.md) | F-029 | Later | - | M | After submission | MDT-002, SC-L02 | Accepted |
| INV-001 | invoices | M05 | [Create invoice and request schema](issues/invoices/001-create-invoice-and-request-schema.md) | F-030–F-039 | M1 | P0 | S | A | MDT-001 | Ready for Assignment |
| INV-002 | invoices | M05 | [Implement the request state machine](issues/invoices/002-implement-the-request-state-machine.md) | F-039 | M1 | P0 | M | A | INV-001 | Ready for Assignment |
| INV-003 | invoices | M05 | [Implement manual request creation and editing](issues/invoices/003-implement-manual-request-creation-and-editing.md) | F-030 | M1 | P0 | M | A | INV-002, MDT-004 | Ready for Assignment |
| INV-004 | invoices | M05 | [Implement document upload to private storage](issues/invoices/004-implement-document-upload-to-private-storage.md) | F-031 | M1 | P0 | S | A | INV-003 | Ready for Assignment |
| INV-005 | invoices | M05 | [Implement CSV bulk import](issues/invoices/005-implement-csv-bulk-import.md) | F-032 | M1 | P1 | M | After submission | INV-003 | Ready for Assignment |
| INV-006 | invoices | M05 | [Compute fingerprints at intake and block duplicates](issues/invoices/006-compute-fingerprints-at-intake-and-block-duplicates.md) | F-037 | M1 | P0 | S | A | INV-003, ENG-009 | Ready for Assignment |
| INV-007 | invoices | M05 | [Implement deterministic anomaly checks](issues/invoices/007-implement-deterministic-anomaly-checks.md) | F-036 | M1 | P0 | M | A | INV-006 | Ready for Assignment |
| INV-008 | invoices | M05 | [Implement payment-terms confirmation](issues/invoices/008-implement-payment-terms-confirmation.md) | F-035 | M1 | P0 | S | A | INV-003, ENG-005 | Ready for Assignment |
| INV-009 | invoices | M05 | [Implement submit-for-approval and flag acknowledgment](issues/invoices/009-implement-submit-for-approval-and-flag-acknowledgment.md) | F-036, F-038 | M1 | P0 | S | A | INV-007, INV-008 | Ready for Assignment |
| INV-010 | invoices | M05 | [Implement approval typed data and signature verification](issues/invoices/010-implement-approval-typed-data-and-signature-verification.md) | F-038 | M1 | P0 | M | A | INV-009, ENG-010, IDN-008 | Ready for Assignment |
| INV-011 | invoices | M05 | [Implement reject, cancel, invalidation and expiry](issues/invoices/011-implement-reject-cancel-invalidation-and-expiry.md) | F-038, F-039 | M1 | P0 | S | B | INV-010, SC-022, MDT-009 | Ready for Assignment |
| INV-L01 | invoices | M05 | [Add the email-forwarding invoice inbox](issues/invoices/l01-add-the-email-forwarding-invoice-inbox.md) | F-033 | Later | - | L | After submission | INV-004, AGT-004 | Accepted |
| INV-L02 | invoices | M05 | [Add the inbound invoice API with scoped keys](issues/invoices/l02-add-the-inbound-invoice-api-with-scoped-keys.md) | F-034 | Later | - | L | After submission | INV-003 | Accepted |
| INV-L03 | invoices | M05 | [Add recurring payment schedules](issues/invoices/l03-add-recurring-payment-schedules.md) | F-040 | Later | - | M | After submission | INV-003 | Accepted |
| INV-L04 | invoices | M05 | [Support fiat-denominated invoices](issues/invoices/l04-support-fiat-denominated-invoices.md) | F-041 | Later | - | L | After submission | INV-003, ENG-L02 | Accepted |
| CHR-001 | chain-reader | M06 | [Build the RPC client with failover](issues/chain-reader/001-build-the-rpc-client-with-failover.md) | F-050 | M1 | P0 | M | A | TRS-002 | Ready for Assignment |
| CHR-002 | chain-reader | M06 | [Implement block-consistent snapshots](issues/chain-reader/002-implement-block-consistent-snapshots.md) | F-050 | M1 | P0 | M | A | CHR-001, TRS-004 | Ready for Assignment |
| CHR-003 | chain-reader | M06 | [Implement the transaction tracker](issues/chain-reader/003-implement-the-transaction-tracker.md) | F-070 | M1 | P0 | M | A | CHR-001, EXE-001 | Ready for Assignment |
| CHR-004 | chain-reader | M06 | [Detect reorgs and re-evaluate status](issues/chain-reader/004-detect-reorgs-and-re-evaluate-status.md) | F-070 | M1 | P1 | S | After submission | CHR-003 | Ready for Assignment |
| CHR-005 | chain-reader | M06 | [Index module and Safe events](issues/chain-reader/005-index-module-and-safe-events.md) | F-050, F-120 | M1 | P1 | M | A | CHR-001, SC-016 | Ready for Assignment |
| EXE-001 | execution | M10 | [Create operations (outbox), transactions and gas ledger schema](issues/execution/001-create-operations-outbox-transactions-and-gas-ledger-schema.md) | F-061 | M1 | P0 | S | A | INV-001 | Ready for Assignment |
| EXE-002 | execution | M10 | [Set up Celery with core and ai queues](issues/execution/002-set-up-celery-with-core-and-ai-queues.md) | F-060, F-061 | M1 | P0 | M | A | DEV-002 | Ready for Assignment |
| EXE-003 | execution | M10 | [Implement the deadline trigger](issues/execution/003-implement-the-deadline-trigger.md) | F-060 | M1 | P0 | M | A | EXE-002, INV-010, MDT-007, TRS-007 | Ready for Assignment |
| EXE-004 | execution | M10 | [Implement the planning pipeline task](issues/execution/004-implement-the-planning-pipeline-task.md) | F-052–F-056 | M1 | P0 | L | A | EXE-003, CHR-002, ENG-008, POL-006, AGT-009, EXE-012 | Ready for Assignment |
| EXE-005 | execution | M10 | [Build the signer service](issues/execution/005-build-the-signer-service.md) | F-061 | M1 | P0 | L | A | POL-006, POL-007, SC-016 | Ready for Assignment |
| EXE-006 | execution | M10 | [Load the executor key from an encrypted keystore](issues/execution/006-load-the-executor-key-from-an-encrypted-keystore.md) | F-061 | M1 | P0 | S | A | EXE-005 | Ready for Assignment |
| EXE-007 | execution | M10 | [Implement the executor with outbox semantics](issues/execution/007-implement-the-executor-with-outbox-semantics.md) | F-061–F-063 | M1 | P0 | M | A | EXE-005, EXE-001 | Ready for Assignment |
| EXE-008 | execution | M10 | [Sequence steps with re-read and re-validation](issues/execution/008-sequence-steps-with-re-read-and-re-validation.md) | F-061 | M1 | P0 | M | A | EXE-007, CHR-003, POL-003, POL-007 | Ready for Assignment |
| EXE-009 | execution | M10 | [Add the operator run-now endpoint](issues/execution/009-add-the-operator-run-now-endpoint.md) | F-060 | M1 | P1 | S | After submission | EXE-003 | Ready for Assignment |
| EXE-010 | execution | M10 | [Track gas fees and alert on low executor gas](issues/execution/010-track-gas-fees-and-alert-on-low-executor-gas.md) | F-066 | M1 | P1 | S | After submission | EXE-007 | Ready for Assignment |
| EXE-011 | execution | M10 | [Execute the swap-for-gas step on the test router](issues/execution/011-execute-the-swap-for-gas-step-on-the-test-router.md) | F-064 | M1 | P2 | S | After submission | EXE-008, SC-018 | Ready for Assignment |
| EXE-L01 | execution | M10 | [Add a KMS-backed signer](issues/execution/l01-add-a-kms-backed-signer.md) | F-061 | Later | - | M | After submission | EXE-005 | Accepted |
| EXE-L02 | execution | M10 | [Integrate the production swap adapter](issues/execution/l02-integrate-the-production-swap-adapter.md) | F-065 | Later | - | M | After submission | EXE-011, SC-L03 | Accepted |
| EXE-L03 | execution | M10 | [Add cross-chain bridging](issues/execution/l03-add-cross-chain-bridging.md) | F-067 | Later | - | L | After submission | TRS-L01 | Accepted |
| EXE-L04 | execution | M10 | [Partition workers by treasury for scale](issues/execution/l04-partition-workers-by-treasury-for-scale.md) | F-061 | Later | - | M | After submission | EXE-002 | Accepted |
| REC-001 | reconciliation | M11 | [Verify post-conditions after each confirmed step](issues/reconciliation/001-verify-post-conditions-after-each-confirmed-step.md) | F-071 | M1 | P0 | M | A | EXE-008 | Ready for Assignment |
| REC-002 | reconciliation | M11 | [Build reconciliation records with classification](issues/reconciliation/002-build-reconciliation-records-with-classification.md) | F-072 | M1 | P0 | M | A | REC-001 | Ready for Assignment |
| REC-003 | reconciliation | M11 | [Implement match, discrepancy and auto-match](issues/reconciliation/003-implement-match-discrepancy-and-auto-match.md) | F-072 | M1 | P0 | S | B | REC-002 | Ready for Assignment |
| REC-004 | reconciliation | M11 | [Export reconciliation CSV and journal lines](issues/reconciliation/004-export-reconciliation-csv-and-journal-lines.md) | F-073 | M1 | P1 | M | B | REC-003 | Ready for Assignment |
| REC-005 | reconciliation | M11 | [Publish on-chain payment attestations](issues/reconciliation/005-publish-on-chain-payment-attestations.md) | F-074 | M1 | P1 | S | A | REC-002, SC-019 | Ready for Assignment |
| REC-L01 | reconciliation | M11 | [Build the ERP integration framework with Xero](issues/reconciliation/l01-build-the-erp-integration-framework-with-xero.md) | F-075 | Later | - | L | After submission | REC-004 | Accepted |
| REC-L02 | reconciliation | M11 | [Add the QuickBooks connector](issues/reconciliation/l02-add-the-quickbooks-connector.md) | F-075 | Later | - | M | After submission | REC-L01 | Accepted |
| REC-L03 | reconciliation | M11 | [Add the NetSuite connector](issues/reconciliation/l03-add-the-netsuite-connector.md) | F-075 | Later | - | M | After submission | REC-L01 | Accepted |
| RCV-001 | recovery | M12 | [Scan in-flight operations at startup](issues/recovery/001-scan-in-flight-operations-at-startup.md) | F-080 | M1 | P0 | S | A | EXE-007 | Ready for Assignment |
| RCV-002 | recovery | M12 | [Resolve unknown operations from chain evidence](issues/recovery/002-resolve-unknown-operations-from-chain-evidence.md) | F-080 | M1 | P0 | M | A | RCV-001, CHR-003 | Ready for Assignment |
| RCV-003 | recovery | M12 | [Handle partial completion and resume](issues/recovery/003-handle-partial-completion-and-resume.md) | F-081 | M1 | P0 | S | After submission | EXE-008 | Ready for Assignment |
| RCV-004 | recovery | M12 | [Implement the review queue and routing](issues/recovery/004-implement-the-review-queue-and-routing.md) | F-082 | M1 | P0 | M | B | INV-002 | Ready for Assignment |
| RCV-005 | recovery | M12 | [Implement retry policy and error classification](issues/recovery/005-implement-retry-policy-and-error-classification.md) | F-083 | M1 | P0 | S | B | EXE-007 | Ready for Assignment |
| RCV-006 | recovery | M12 | [Implement circuit-breaker rules and auto-pause](issues/recovery/006-implement-circuit-breaker-rules-and-auto-pause.md) | F-027 | M1 | P2 | M | After submission | REC-001, MDT-007, EXE-013, CHR-006 | Ready for Assignment |
| RCV-007 | recovery | M12 | [Automate the crash-recovery test](issues/recovery/007-automate-the-crash-recovery-test.md) | F-080 | M1 | P0 | S | A | RCV-002 | Ready for Assignment |
| AGT-001 | agent | M09 | [Build the LLM adapter with routing and timeouts](issues/agent/001-build-the-llm-adapter-with-routing-and-timeouts.md) | F-094 | M1 | P0 | M | A | EXE-002 | Ready for Assignment |
| AGT-002 | agent | M09 | [Log every AI call and fail closed](issues/agent/002-log-every-ai-call-and-fail-closed.md) | F-093 | M1 | P0 | S | A | AGT-001 | Ready for Assignment |
| AGT-003 | agent | M09 | [Implement untrusted-content wrapping and sanitization](issues/agent/003-implement-untrusted-content-wrapping-and-sanitization.md) | F-091 | M1 | P0 | S | A | AGT-001 | Ready for Assignment |
| AGT-004 | agent | M09 | [Implement invoice extraction](issues/agent/004-implement-invoice-extraction.md) | F-031 | M1 | P0 | M | A | AGT-003, AGT-002, INV-004 | Ready for Assignment |
| AGT-005 | agent | M09 | [Extract and validate payment terms](issues/agent/005-extract-and-validate-payment-terms.md) | F-035 | M1 | P0 | S | A | AGT-004, ENG-005 | Ready for Assignment |
| AGT-006 | agent | M09 | [Detect instruction-like text in documents](issues/agent/006-detect-instruction-like-text-in-documents.md) | F-036, F-091 | M1 | P0 | S | A | AGT-004 | Ready for Assignment |
| AGT-007 | agent | M09 | [Implement the read-only tool layer](issues/agent/007-implement-the-read-only-tool-layer.md) | F-053, F-090 | M1 | P0 | M | A | CHR-002, ENG-008, POL-003 | Ready for Assignment |
| AGT-008 | agent | M09 | [Implement the plan proposer](issues/agent/008-implement-the-plan-proposer.md) | F-053 | M1 | P0 | M | A | AGT-007 | Ready for Assignment |
| AGT-009 | agent | M09 | [Score AI proposals and select the plan](issues/agent/009-score-ai-proposals-and-select-the-plan.md) | F-053 | M1 | P0 | S | A | AGT-008, ENG-008 | Ready for Assignment |
| AGT-010 | agent | M09 | [Implement rule-based fallback templates](issues/agent/010-implement-rule-based-fallback-templates.md) | F-054 | M1 | P0 | S | A | ENG-007, POL-003 | Ready for Assignment |
| AGT-011 | agent | M09 | [Draft exception requests with a numeric post-check](issues/agent/011-draft-exception-requests-with-a-numeric-post-check.md) | F-057 | M1 | P1 | S | B | AGT-001, MDT-006 | Ready for Assignment |
| AGT-012 | agent | M09 | [Build the Copilot backend](issues/agent/012-build-the-copilot-backend.md) | F-090 | M1 | P1 | L | After submission | AGT-007 | Ready for Assignment |
| AGT-013 | agent | M09 | [Build the extraction accuracy eval](issues/agent/013-build-the-extraction-accuracy-eval.md) | F-092 | M1 | P0 | S | B | AGT-005, DOM-004 | Ready for Assignment |
| AGT-014 | agent | M09 | [Build the planner benchmark (B1 vs B2)](issues/agent/014-build-the-planner-benchmark-b1-vs-b2.md) | F-092 | M1 | P0 | M | A | AGT-009, ENG-006, DOM-005 | Ready for Assignment |
| AGT-015 | agent | M09 | [Build the red-team suite runner](issues/agent/015-build-the-red-team-suite-runner.md) | F-091, F-163 | M1 | P0 | S | A | AGT-006, DOM-006 | Ready for Assignment |
| AGT-016 | agent | M09 | [Build the Copilot numeric-fidelity suite](issues/agent/016-build-the-copilot-numeric-fidelity-suite.md) | F-092 | M1 | P1 | S | After submission | AGT-012, DOM-007 | Ready for Assignment |
| AGT-017 | agent | M09 | [Add a secondary LLM provider fallback](issues/agent/017-add-a-secondary-llm-provider-fallback.md) | F-094 | M1 | P1 | M | After submission | AGT-001 | Ready for Assignment |
| NTF-001 | notifications | M13 | [Create the domain event bus and notification routing](issues/notifications/001-create-the-domain-event-bus-and-notification-routing.md) | F-100 | M1 | P1 | M | A | INV-002 | Ready for Assignment |
| NTF-002 | notifications | M13 | [Expose in-app notifications and the SSE stream](issues/notifications/002-expose-in-app-notifications-and-the-sse-stream.md) | F-100, F-132 | M1 | P1 | M | A | NTF-001 | Ready for Assignment |
| NTF-003 | notifications | M13 | [Add Telegram linking and delivery](issues/notifications/003-add-telegram-linking-and-delivery.md) | F-101 | M1 | P2 | M | After submission | NTF-001 | Ready for Assignment |
| NTF-L01 | notifications | M13 | [Add email notifications and digests](issues/notifications/l01-add-email-notifications-and-digests.md) | F-102 | Later | - | M | After submission | NTF-001 | Accepted |
| NTF-L02 | notifications | M13 | [Add outbound webhooks](issues/notifications/l02-add-outbound-webhooks.md) | F-103 | Later | - | M | After submission | NTF-001 | Accepted |
| NTF-L03 | notifications | M13 | [Add Slack, Lark and WeCom channels](issues/notifications/l03-add-slack-lark-and-wecom-channels.md) | F-104 | Later | - | L | After submission | NTF-001 | Accepted |
| NTF-L04 | notifications | M13 | [Add notification preferences](issues/notifications/l04-add-notification-preferences.md) | F-105 | Later | - | S | After submission | NTF-002 | Accepted |
| CMP-001 | compliance | M14 | [Build the screening adapter and fixture provider](issues/compliance/001-build-the-screening-adapter-and-fixture-provider.md) | F-110 | M1 | P1 | S | A | MDT-001 | Ready for Assignment |
| CMP-002 | compliance | M14 | [Screen payees before each PAY](issues/compliance/002-screen-payees-before-each-pay.md) | F-110 | M1 | P1 | S | After submission | CMP-001, POL-003 | Ready for Assignment |
| CMP-003 | compliance | M14 | [Implement data classification, encryption helpers and log redaction](issues/compliance/003-implement-data-classification-encryption-helpers-and-log-red.md) | F-113 | M1 | P0 | M | B | DEV-001 | Ready for Assignment |
| CMP-L01 | compliance | M14 | [Integrate a KYB provider](issues/compliance/l01-integrate-a-kyb-provider.md) | F-111 | Later | - | L | After submission | CMP-001 | Accepted |
| CMP-L02 | compliance | M14 | [Add Travel Rule support](issues/compliance/l02-add-travel-rule-support.md) | F-112 | Later | - | L | After submission | CMP-L01 | Accepted |
| CMP-L03 | compliance | M14 | [Add retention and deletion workflows](issues/compliance/l03-add-retention-and-deletion-workflows.md) | F-114 | Later | - | M | After submission | CMP-003 | Accepted |
| CMP-L04 | compliance | M14 | [Add region pinning for stored data](issues/compliance/l04-add-region-pinning-for-stored-data.md) | F-114 | Later | - | M | After submission | CMP-L03 | Accepted |
| AUD-001 | audit | M15 | [Implement the hash-chained audit log](issues/audit/001-implement-the-hash-chained-audit-log.md) | F-120 | M1 | P0 | M | A | IDN-001 | Ready for Assignment |
| AUD-002 | audit | M15 | [Add audit read and chain verification](issues/audit/002-add-audit-read-and-chain-verification.md) | F-120 | M1 | P0 | S | After submission | AUD-001 | Ready for Assignment |
| AUD-003 | audit | M15 | [Define the evidence bundle schema and exporter](issues/audit/003-define-the-evidence-bundle-schema-and-exporter.md) | F-121 | M1 | P0 | M | A | AUD-001, EXE-008 | Ready for Assignment |
| AUD-004 | audit | M15 | [Propagate coverage labels through the API](issues/audit/004-propagate-coverage-labels-through-the-api.md) | F-122 | M1 | P1 | S | After submission | CHR-002 | Ready for Assignment |
| AUD-L01 | audit | M15 | [Anchor the audit hash root on-chain daily](issues/audit/l01-anchor-the-audit-hash-root-on-chain-daily.md) | F-120 | Later | - | L | After submission | AUD-002 | Accepted |
| OBS-001 | observability | M17 | [Configure structured logging with correlation ids](issues/observability/001-configure-structured-logging-with-correlation-ids.md) | F-142 | M1 | P1 | S | After submission | CMP-003 | Ready for Assignment |
| OBS-002 | observability | M17 | [Add OpenTelemetry tracing](issues/observability/002-add-opentelemetry-tracing.md) | F-142 | M1 | P1 | M | After submission | OBS-001 | Ready for Assignment |
| OBS-003 | observability | M17 | [Add Sentry and Prometheus metrics](issues/observability/003-add-sentry-and-prometheus-metrics.md) | F-142 | M1 | P1 | S | After submission | OBS-001 | Ready for Assignment |
| OBS-004 | observability | M17 | [Compute operational metrics](issues/observability/004-compute-operational-metrics.md) | F-140 | M1 | P1 | M | After submission | AUD-001, EXE-008 | Ready for Assignment |
| OBS-005 | observability | M17 | [Compute the savings report](issues/observability/005-compute-the-savings-report.md) | F-141 | M1 | P1 | M | After submission | OBS-004, ENG-006 | Ready for Assignment |
| ADM-L01 | admin | M18 | [Build the platform admin console](issues/admin/l01-build-the-platform-admin-console.md) | F-150 | Later | - | L | After submission | IDN-006 | Accepted |
| ADM-L02 | admin | M18 | [Meter usage for billing](issues/admin/l02-meter-usage-for-billing.md) | F-152 | Later | - | M | After submission | OBS-004 | Accepted |
| ADM-L03 | admin | M18 | [Add subscriptions and customer invoicing](issues/admin/l03-add-subscriptions-and-customer-invoicing.md) | F-152 | Later | - | L | After submission | ADM-L02 | Accepted |
| WEB-001 | web | M16 | [Create the web app shell](issues/web/001-create-the-web-app-shell.md) | F-130 | M1 | P0 | M | A | DEV-001 | Ready for Assignment |
| WEB-002 | web | M16 | [Build login, org selection and onboarding checklist](issues/web/002-build-login-org-selection-and-onboarding-checklist.md) | F-001, F-003 | M1 | P0 | M | A | WEB-001, IDN-005 | Ready for Assignment |
| WEB-003 | web | M16 | [Add wallet connection and SIWE linking](issues/web/003-add-wallet-connection-and-siwe-linking.md) | F-002 | M1 | P0 | S | A | WEB-002, IDN-004 | Ready for Assignment |
| WEB-004 | web | M16 | [Build the treasury setup wizard](issues/web/004-build-the-treasury-setup-wizard.md) | F-010–F-012 | M1 | P0 | M | A | WEB-003, TRS-007, WEB-025 | Ready for Assignment |
| WEB-005 | web | M16 | [Build the mandate editor with summary, diff and activation](issues/web/005-build-the-mandate-editor-with-summary-diff-and-activation.md) | F-134, F-020, F-021 | M1 | P0 | L | B | WEB-004, MDT-003, WEB-025 | Ready for Assignment |
| WEB-006 | web | M16 | [Build the payee registry UI](issues/web/006-build-the-payee-registry-ui.md) | F-134, F-022 | M1 | P0 | M | B | WEB-004, MDT-005, WEB-025 | Ready for Assignment |
| WEB-007 | web | M16 | [Build the request list and manual entry form](issues/web/007-build-the-request-list-and-manual-entry-form.md) | F-030 | M1 | P0 | M | A | WEB-002, INV-003 | Ready for Assignment |
| WEB-008 | web | M16 | [Build upload and extraction review](issues/web/008-build-upload-and-extraction-review.md) | F-031, F-035 | M1 | P0 | L | A | WEB-007, AGT-005 | Ready for Assignment |
| WEB-009 | web | M16 | [Build the approval inbox and EIP-712 signing](issues/web/009-build-the-approval-inbox-and-eip-712-signing.md) | F-131, F-038 | M1 | P0 | L | A | WEB-008, INV-010 | Ready for Assignment |
| WEB-010 | web | M16 | [Build the treasury dashboard](issues/web/010-build-the-treasury-dashboard.md) | F-130 | M1 | P0 | M | A | WEB-004, CHR-002 | Ready for Assignment |
| WEB-011 | web | M16 | [Build plan cards and the Why panel](issues/web/011-build-plan-cards-and-the-why-panel.md) | F-132 | M1 | P0 | M | A | WEB-010, EXE-004 | Ready for Assignment |
| WEB-012 | web | M16 | [Build the live execution timeline](issues/web/012-build-the-live-execution-timeline.md) | F-132 | M1 | P0 | M | A | WEB-011, NTF-002 | Ready for Assignment |
| WEB-013 | web | M16 | [Build the exception and review console](issues/web/013-build-the-exception-and-review-console.md) | F-135 | M1 | P0 | L | B | WEB-011, RCV-004, MDT-006, WEB-025 | Ready for Assignment |
| WEB-014 | web | M16 | [Build the reconciliation view and export](issues/web/014-build-the-reconciliation-view-and-export.md) | F-133 | M1 | P0 | M | B | WEB-010, REC-004 | Ready for Assignment |
| WEB-015 | web | M16 | [Build the notifications center](issues/web/015-build-the-notifications-center.md) | F-100 | M1 | P1 | S | After submission | WEB-001, NTF-002 | Ready for Assignment |
| WEB-016 | web | M16 | [Build the Copilot chat UI](issues/web/016-build-the-copilot-chat-ui.md) | F-090 | M1 | P1 | M | After submission | WEB-010, AGT-012 | Ready for Assignment |
| WEB-017 | web | M16 | [Build members and roles administration](issues/web/017-build-members-and-roles-administration.md) | F-004 | M1 | P1 | M | After submission | WEB-002, IDN-007 | Ready for Assignment |
| WEB-018 | web | M16 | [Build metrics and savings pages](issues/web/018-build-metrics-and-savings-pages.md) | F-140, F-141 | M1 | P1 | M | After submission | WEB-010, OBS-005 | Ready for Assignment |
| WEB-019 | web | M16 | [Add pause and resume controls and status banners](issues/web/019-add-pause-and-resume-controls-and-status-banners.md) | F-026 | M1 | P0 | S | B | WEB-010, MDT-007 | Ready for Assignment |
| WEB-020 | web | M16 | [Build the CSV import UI](issues/web/020-build-the-csv-import-ui.md) | F-032 | M1 | P1 | S | After submission | WEB-007, INV-005 | Ready for Assignment |
| WEB-021 | web | M16 | [Build the runway forecast chart](issues/web/021-build-the-runway-forecast-chart.md) | F-058 | M1 | P2 | S | After submission | WEB-010, ENG-011 | Ready for Assignment |
| WEB-022 | web | M16 | [Run the accessibility and responsive pass](issues/web/022-run-the-accessibility-and-responsive-pass.md) | F-130–F-135 | M1 | P1 | S | After submission | WEB-014 | Ready for Assignment |
| WEB-023 | web | M16 | [Write the Playwright end-to-end happy path](issues/web/023-write-the-playwright-end-to-end-happy-path.md) | F-161 | M1 | P1 | M | After submission | WEB-012 | Ready for Assignment |
| DOM-001 | domain-evidence | M20 | [Verify Ethereum Sepolia infrastructure (owner: Phúc)](issues/domain-evidence/001-verify-ethereum-sepolia-infrastructure-owner-ph-c.md) | F-010, F-151 | M1 | P0 | S | A | — | Ready for Assignment |
| DOM-002 | domain-evidence | M20 | [Set up tUSDC and the Circle USDC evidence run (owner: Phúc)](issues/domain-evidence/002-set-up-tusdc-and-the-circle-usdc-evidence-run-owner-ph-c.md) | F-013 | M1 | P0 | S | A | DOM-001 | Ready for Assignment |
| DOM-003 | domain-evidence | M20 | [Ask the organizers whether testnet evidence is accepted](issues/domain-evidence/003-ask-the-organizers-whether-testnet-evidence-is-accepted.md) | — | M1 | P1 | S | A | — | Ready for Assignment |
| DOM-004 | domain-evidence | M20 | [Author the labelled invoice dataset (30)](issues/domain-evidence/004-author-the-labelled-invoice-dataset-30.md) | F-092 | M1 | P0 | M | B | — | Ready for Assignment |
| DOM-005 | domain-evidence | M20 | [Author planner scenarios with ground truth (≥30)](issues/domain-evidence/005-author-planner-scenarios-with-ground-truth-30.md) | F-092 | M1 | P0 | L | A | — | Ready for Assignment |
| DOM-006 | domain-evidence | M20 | [Author the red-team invoice set (20)](issues/domain-evidence/006-author-the-red-team-invoice-set-20.md) | F-091, F-163 | M1 | P0 | M | A | — | Ready for Assignment |
| DOM-007 | domain-evidence | M20 | [Author Copilot question cases (20)](issues/domain-evidence/007-author-copilot-question-cases-20.md) | F-092 | M1 | P1 | S | After submission | DOM-005 | Ready for Assignment |
| DOM-008 | domain-evidence | M20 | [Review business rules and demo limits from a finance view](issues/domain-evidence/008-review-business-rules-and-demo-limits-from-a-finance-view.md) | — | M1 | P0 | S | A | — | Ready for Assignment |
| DOM-009 | domain-evidence | M20 | [Review the threat model and write the known-risk list](issues/domain-evidence/009-review-the-threat-model-and-write-the-known-risk-list.md) | — | M1 | P0 | M | A | — | Ready for Assignment |
| DOM-010 | domain-evidence | M20 | [Run customer interviews (2–3)](issues/domain-evidence/010-run-customer-interviews-2-3.md) | — | M1 | P1 | M | B | — | Ready for Assignment |
| DOM-011 | domain-evidence | M20 | [Write the security self-assessment report](issues/domain-evidence/011-write-the-security-self-assessment-report.md) | — | M1 | P0 | M | A | DOM-009, SC-015 | Ready for Assignment |
| DOM-012 | domain-evidence | M20 | [Assemble the technical documentation for submission](issues/domain-evidence/012-assemble-the-technical-documentation-for-submission.md) | — | M1 | P0 | M | A | DOM-011 | Ready for Assignment |
| DOM-013 | domain-evidence | M20 | [Create the 10-minute presentation deck](issues/domain-evidence/013-create-the-10-minute-presentation-deck.md) | — | M1 | P0 | M | A | DOM-008 | Ready for Assignment |
| DOM-014 | domain-evidence | M20 | [Script and record the 5-minute demo video](issues/domain-evidence/014-script-and-record-the-5-minute-demo-video.md) | — | M1 | P0 | M | A | DEV-008 | Ready for Assignment |
| DOM-015 | domain-evidence | M20 | [Write the compliance positioning note and license inventory](issues/domain-evidence/015-write-the-compliance-positioning-note-and-license-inventory.md) | — | M1 | P1 | S | B | — | Ready for Assignment |
| DOM-016 | domain-evidence | M20 | [Update the FigJam board from the repo diagrams](issues/domain-evidence/016-update-the-figjam-board-from-the-repo-diagrams.md) | — | M1 | P2 | S | After submission | — | Ready for Assignment |
| DOM-017 | domain-evidence | M20 | [Choose the repository license](issues/domain-evidence/017-choose-the-repository-license.md) | — | M1 | P1 | S | After submission | — | Ready for Assignment |
| SC-021 | contracts | M04 | [Implement the module factory with EIP-1167 clones](issues/contracts/021-implement-the-module-factory-with-eip-1167-clones.md) | F-012, F-021 | M1 | P0 | M | A | SC-002 | Ready for Assignment |
| ENG-012 | financial-engine | M07 | [Implement the exhaustive oracle scheduler for tests](issues/financial-engine/012-implement-the-exhaustive-oracle-scheduler-for-tests.md) | F-052, F-092 | M1 | P0 | S | A | ENG-006 | Ready for Assignment |
| POL-007 | policy-engine | M08 | [Simulate each step with eth_call before signing](issues/policy-engine/007-simulate-each-step-with-eth-call-before-signing.md) | F-055, F-061 | M1 | P0 | S | A | POL-003, POL-001, CHR-002, SC-016 | Ready for Assignment |
| INV-012 | invoices | M05 | [Detect near-duplicate requests](issues/invoices/012-detect-near-duplicate-requests.md) | F-036, F-037 | M1 | P0 | S | A | INV-006 | Ready for Assignment |
| SC-022 | contracts | M04 | [Add on-chain request cancellation](issues/contracts/022-add-on-chain-request-cancellation.md) | F-039 | M1 | P0 | S | A | SC-006, SC-009 | Ready for Assignment |
| MDT-009 | mandate | M03 | [Build governance transactions and collect owner signatures in the app](issues/mandate/009-build-governance-transactions-and-collect-owner-signatures-i.md) | F-020, F-021, F-022, F-025, F-026 | M1 | P0 | L | A | MDT-001, TRS-005 | Ready for Assignment |
| MDT-010 | mandate | M03 | [Set up the Guardian Safe with the sentinel](issues/mandate/010-set-up-the-guardian-safe-with-the-sentinel.md) | F-026, F-027 | M1 | P0 | S | A | MDT-009, EXE-013, TRS-006 | Ready for Assignment |
| EXE-013 | execution | M10 | [Add the pause-only sentinel to the signer](issues/execution/013-add-the-pause-only-sentinel-to-the-signer.md) | F-026, F-027 | M1 | P0 | S | A | EXE-005, EXE-006 | Ready for Assignment |
| EXE-012 | execution | M10 | [Implement the fee policy, fee holds and fee acceptance](issues/execution/012-implement-the-fee-policy-fee-holds-and-fee-acceptance.md) | F-066 | M1 | P0 | M | A | MDT-001, CHR-001, ENG-001 | Ready for Assignment |
| WEB-024 | web | M16 | [Build the fee policy and fee acceptance UI](issues/web/024-build-the-fee-policy-and-fee-acceptance-ui.md) | F-066 | M1 | P1 | S | B | WEB-010, EXE-012 | Ready for Assignment |
| WEB-025 | web | M16 | [Build the governance signing inbox](issues/web/025-build-the-governance-signing-inbox.md) | F-020–F-026 | M1 | P0 | M | A | WEB-003, MDT-009 | Ready for Assignment |
| CHR-006 | chain-reader | M06 | [Index treasury token movements and alert on unexpected outflows](issues/chain-reader/006-index-treasury-token-movements-and-alert-on-unexpected-outfl.md) | F-050 | M1 | P0 | S | A | CHR-005, EXE-001 | Ready for Assignment |
| SC-023 | contracts | M04 | [Add two-option payment approvals (early / standard)](issues/contracts/023-add-two-option-payment-approvals-early-standard.md) | F-038 | M1 | P0 | S | A | SC-006, SC-005 | Ready for Assignment |
| SC-024 | contracts | M04 | [Implement Aave V3 supply and withdraw through Safe T](issues/contracts/024-implement-aave-v3-supply-and-withdraw-through-safe-t.md) | F-068 | M1 | P0 | M | A | SC-021, SC-007, SC-008 | Ready for Assignment |
| SC-025 | contracts | M04 | [Add Aave integration tests on a pinned Sepolia fork](issues/contracts/025-add-aave-integration-tests-on-a-pinned-sepolia-fork.md) | F-068, F-163 | M1 | P0 | S | A | SC-024, SC-016 | Ready for Assignment |
| SC-026 | contracts | M04 | [Implement owner-authorized borrow and repay](issues/contracts/026-implement-owner-authorized-borrow-and-repay.md) | F-079 | M1 | P2 | M | After submission | SC-024 | Ready for Assignment |
| ENG-013 | financial-engine | M07 | [Implement reserve formulas and the liquidity decision](issues/financial-engine/013-implement-reserve-formulas-and-the-liquidity-decision.md) | F-068 | M1 | P0 | S | A | ENG-002, ENG-005 | Ready for Assignment |
| ENG-014 | financial-engine | M07 | [Build the borrow proposal](issues/financial-engine/014-build-the-borrow-proposal.md) | F-069 | M1 | P1 | S | B | ENG-013 | Ready for Assignment |
| EXE-014 | execution | M10 | [Run the liquidity cycle (supply / withdraw)](issues/execution/014-run-the-liquidity-cycle-supply-withdraw.md) | F-068 | M1 | P0 | S | A | EXE-008, ENG-013, SC-024 | Ready for Assignment |
| WEB-026 | web | M16 | [Build the treasury position card](issues/web/026-build-the-treasury-position-card.md) | F-068, F-130 | M1 | P0 | S | A | WEB-010 | Ready for Assignment |
| WEB-027 | web | M16 | [Build the borrow proposal view](issues/web/027-build-the-borrow-proposal-view.md) | F-069 | M1 | P1 | S | B | WEB-026, ENG-014 | Ready for Assignment |
| DEV-012 | devex | M19 | [Add the deployment config gate to CI](issues/devex/012-add-the-deployment-config-gate-to-ci.md) | F-151 | M1 | P0 | S | A | SC-016, DEV-003 | Ready for Assignment |
| MDT-011 | mandate | M03 | [Add owner borrow/repay authorizations (governance)](issues/mandate/011-add-owner-borrow-repay-authorizations-governance.md) | F-079 | M1 | P2 | S | After submission | MDT-009, SC-026 | Ready for Assignment |
