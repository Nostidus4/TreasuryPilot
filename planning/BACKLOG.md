# Master Backlog

Generated from `planning/tools/data` by `planning/tools/gen_issues.py`. Do not edit by hand.

**Status legend:** Draft → Needs Discussion → Ready for Review → Accepted → Ready for Assignment → Assigned → In Progress → Review → Done.
Until gate G3, no ticket is above **Ready for Review**. Later-phase tickets are **Needs Discussion**.

## Totals

| Phase | P0 | P1 | P2 | Total |
|---|---:|---:|---:|---:|
| M1 | 127 | 46 | 10 | 183 |
| Later | – | – | – | 38 |
| **All** | | | | **221** |

## Epics

| Epic | Module | Tickets (M1) | Tickets (Later) | Folder |
|---|---|---:|---:|---|
| M19 · Developer Experience & Quality | `devex` | 11 | 0 | [`issues/devex/`](issues/devex/) |
| M04 · Smart Contracts | `contracts` | 20 | 6 | [`issues/contracts/`](issues/contracts/) |
| M07 · Financial Engine (py-core) | `financial-engine` | 11 | 3 | [`issues/financial-engine/`](issues/financial-engine/) |
| M08 · Policy Engine & Attestation | `policy-engine` | 6 | 0 | [`issues/policy-engine/`](issues/policy-engine/) |
| M01 · Identity & Access | `identity` | 8 | 3 | [`issues/identity/`](issues/identity/) |
| M02 · Treasury & Chain Configuration | `treasury` | 8 | 2 | [`issues/treasury/`](issues/treasury/) |
| M03 · Mandate, Payees, Exceptions & Pause | `mandate` | 8 | 1 | [`issues/mandate/`](issues/mandate/) |
| M05 · Invoices & Payment Requests | `invoices` | 11 | 4 | [`issues/invoices/`](issues/invoices/) |
| M06 · Chain Reader & Tx Tracking | `chain-reader` | 5 | 0 | [`issues/chain-reader/`](issues/chain-reader/) |
| M09 · AI Agent | `agent` | 17 | 0 | [`issues/agent/`](issues/agent/) |
| M10 · Orchestration & Execution | `execution` | 11 | 4 | [`issues/execution/`](issues/execution/) |
| M11 · Verification & Reconciliation | `reconciliation` | 5 | 3 | [`issues/reconciliation/`](issues/reconciliation/) |
| M12 · Recovery & Exceptions | `recovery` | 7 | 0 | [`issues/recovery/`](issues/recovery/) |
| M13 · Notifications | `notifications` | 3 | 4 | [`issues/notifications/`](issues/notifications/) |
| M14 · Compliance | `compliance` | 3 | 4 | [`issues/compliance/`](issues/compliance/) |
| M15 · Audit & Evidence | `audit` | 4 | 1 | [`issues/audit/`](issues/audit/) |
| M16 · Web Application | `web` | 23 | 0 | [`issues/web/`](issues/web/) |
| M17 · Observability & Analytics | `observability` | 5 | 0 | [`issues/observability/`](issues/observability/) |
| M18 · Platform Admin & Billing | `admin` | 0 | 3 | [`issues/admin/`](issues/admin/) |
| M20 · Domain & Evidence (non-code) | `domain-evidence` | 17 | 0 | [`issues/domain-evidence/`](issues/domain-evidence/) |

## All tickets

| ID | Module | Epic | Issue | Features | Phase | Prio | Size | Dependency | Status |
|---|---|---|---|---|---|---|---|---|---|
| DEV-001 | devex | M19 | [Initialize monorepo skeleton](issues/devex/001-initialize-monorepo-skeleton.md) | F-160 | M1 | P0 | M | — | Ready for Review |
| DEV-002 | devex | M19 | [Create Docker Compose stack (local profile)](issues/devex/002-create-docker-compose-stack-local-profile.md) | F-160 | M1 | P0 | M | DEV-001 | Ready for Review |
| DEV-003 | devex | M19 | [Add CI workflow for Python](issues/devex/003-add-ci-workflow-for-python.md) | F-161 | M1 | P1 | S | DEV-001 | Ready for Review |
| DEV-004 | devex | M19 | [Add CI workflow for contracts](issues/devex/004-add-ci-workflow-for-contracts.md) | F-161, F-163 | M1 | P1 | S | SC-001 | Ready for Review |
| DEV-005 | devex | M19 | [Add CI workflow for web and OpenAPI client drift](issues/devex/005-add-ci-workflow-for-web-and-openapi-client-drift.md) | F-161 | M1 | P1 | S | WEB-001 | Ready for Review |
| DEV-006 | devex | M19 | [Write seed script for the local environment](issues/devex/006-write-seed-script-for-the-local-environment.md) | F-160 | M1 | P1 | M | SC-016, TRS-004, MDT-003, INV-003 | Ready for Review |
| DEV-007 | devex | M19 | [Build scenario runner CLI](issues/devex/007-build-scenario-runner-cli.md) | F-162 | M1 | P1 | M | DEV-006, AUD-003 | Ready for Review |
| DEV-008 | devex | M19 | [Write the demo runbook](issues/devex/008-write-the-demo-runbook.md) | F-162 | M1 | P1 | S | DEV-007 | Ready for Review |
| DEV-009 | devex | M19 | [Build the reliability run harness](issues/devex/009-build-the-reliability-run-harness.md) | F-164 | M1 | P1 | S | DEV-007 | Ready for Review |
| DEV-010 | devex | M19 | [Add testnet profile and VM deployment](issues/devex/010-add-testnet-profile-and-vm-deployment.md) | F-160, F-151 | M1 | P1 | M | DEV-002, DOM-001, SC-016 | Ready for Review |
| DEV-011 | devex | M19 | [Enforce module boundaries with import-linter](issues/devex/011-enforce-module-boundaries-with-import-linter.md) | F-161 | M1 | P1 | S | DEV-001 | Ready for Review |
| SC-001 | contracts | M04 | [Set up the Foundry project with pinned dependencies](issues/contracts/001-set-up-the-foundry-project-with-pinned-dependencies.md) | F-163 | M1 | P0 | S | DEV-001 | Ready for Review |
| SC-002 | contracts | M04 | [Define module storage, structs, EIP-712 domain, errors and events](issues/contracts/002-define-module-storage-structs-eip-712-domain-errors-and-even.md) | F-021, F-038 | M1 | P0 | M | SC-001 | Ready for Review |
| SC-003 | contracts | M04 | [Implement mandate governance and versioning](issues/contracts/003-implement-mandate-governance-and-versioning.md) | F-021 | M1 | P0 | M | SC-002 | Ready for Review |
| SC-004 | contracts | M04 | [Implement the payee registry with cooling period](issues/contracts/004-implement-the-payee-registry-with-cooling-period.md) | F-022 | M1 | P0 | S | SC-003 | Ready for Review |
| SC-005 | contracts | M04 | [Implement approval signature verification](issues/contracts/005-implement-approval-signature-verification.md) | F-038 | M1 | P0 | M | SC-002 | Ready for Review |
| SC-006 | contracts | M04 | [Implement pay() core flow](issues/contracts/006-implement-pay-core-flow.md) | F-063 | M1 | P0 | M | SC-004, SC-005 | Ready for Review |
| SC-007 | contracts | M04 | [Implement per-request limits and UTC daily counters](issues/contracts/007-implement-per-request-limits-and-utc-daily-counters.md) | F-023 | M1 | P0 | M | SC-006 | Ready for Review |
| SC-008 | contracts | M04 | [Enforce minimum buffers on pay and refill](issues/contracts/008-enforce-minimum-buffers-on-pay-and-refill.md) | F-024 | M1 | P0 | S | SC-006 | Ready for Review |
| SC-009 | contracts | M04 | [Implement refill() bound to an approved request](issues/contracts/009-implement-refill-bound-to-an-approved-request.md) | F-062 | M1 | P0 | M | SC-005, SC-007, SC-008 | Ready for Review |
| SC-010 | contracts | M04 | [Implement pause, resume, revoke and guardian](issues/contracts/010-implement-pause-resume-revoke-and-guardian.md) | F-026 | M1 | P0 | S | SC-003 | Ready for Review |
| SC-011 | contracts | M04 | [Implement one-time exception verification and consumption](issues/contracts/011-implement-one-time-exception-verification-and-consumption.md) | F-025 | M1 | P1 | M | SC-007 | Ready for Review |
| SC-012 | contracts | M04 | [Add the duplicate-invoice fingerprint registry](issues/contracts/012-add-the-duplicate-invoice-fingerprint-registry.md) | F-037 | M1 | P0 | S | SC-006 | Ready for Review |
| SC-013 | contracts | M04 | [Write the contract acceptance test suite (AT cases)](issues/contracts/013-write-the-contract-acceptance-test-suite-at-cases.md) | F-163 | M1 | P0 | M | SC-009, SC-010, SC-012 | Ready for Review |
| SC-014 | contracts | M04 | [Write the invariant and fuzz suite](issues/contracts/014-write-the-invariant-and-fuzz-suite.md) | F-163 | M1 | P0 | M | SC-013 | Ready for Review |
| SC-015 | contracts | M04 | [Run static analysis and write the findings report](issues/contracts/015-run-static-analysis-and-write-the-findings-report.md) | F-163 | M1 | P0 | S | SC-013 | Ready for Review |
| SC-016 | contracts | M04 | [Write deployment scripts and the deployments manifest](issues/contracts/016-write-deployment-scripts-and-the-deployments-manifest.md) | F-151 | M1 | P0 | M | SC-010 | Ready for Review |
| SC-017 | contracts | M04 | [Publish EIP-712 golden vectors](issues/contracts/017-publish-eip-712-golden-vectors.md) | F-038, F-056 | M1 | P0 | S | SC-005 | Ready for Review |
| SC-018 | contracts | M04 | [Add the test router and swapForGas](issues/contracts/018-add-the-test-router-and-swapforgas.md) | F-064 | M1 | P2 | M | SC-009 | Ready for Review |
| SC-019 | contracts | M04 | [Register the attestation schema and add an attest helper](issues/contracts/019-register-the-attestation-schema-and-add-an-attest-helper.md) | F-074 | M1 | P2 | S | DOM-001 | Ready for Review |
| SC-020 | contracts | M04 | [Write direct-call bypass tests](issues/contracts/020-write-direct-call-bypass-tests.md) | F-163 | M1 | P0 | S | SC-013 | Ready for Review |
| SC-L01 | contracts | M04 | [Enforce reserves and execution holds on-chain](issues/contracts/l01-enforce-reserves-and-execution-holds-on-chain.md) | F-028 | Later | - | L | SC-014 | Needs Discussion |
| SC-L02 | contracts | M04 | [Enforce n-of-m approval thresholds by amount band](issues/contracts/l02-enforce-n-of-m-approval-thresholds-by-amount-band.md) | F-029 | Later | - | L | SC-005 | Needs Discussion |
| SC-L03 | contracts | M04 | [Add a production swap adapter with signed quotes](issues/contracts/l03-add-a-production-swap-adapter-with-signed-quotes.md) | F-065 | Later | - | L | SC-018 | Needs Discussion |
| SC-L04 | contracts | M04 | [Verify plan attestations on-chain](issues/contracts/l04-verify-plan-attestations-on-chain.md) | F-056 | Later | - | M | SC-017 | Needs Discussion |
| SC-L05 | contracts | M04 | [Support multiple stablecoins with per-asset limits](issues/contracts/l05-support-multiple-stablecoins-with-per-asset-limits.md) | F-015 | Later | - | M | SC-007 | Needs Discussion |
| SC-L06 | contracts | M04 | [Allow refill paths between operational wallets](issues/contracts/l06-allow-refill-paths-between-operational-wallets.md) | F-059 | Later | - | M | SC-009 | Needs Discussion |
| ENG-001 | financial-engine | M07 | [Create py-core money types and domain models](issues/financial-engine/001-create-py-core-money-types-and-domain-models.md) | F-013, F-051 | M1 | P0 | M | DEV-001 | Ready for Review |
| ENG-002 | financial-engine | M07 | [Implement the liquidity calculator](issues/financial-engine/002-implement-the-liquidity-calculator.md) | F-051 | M1 | P0 | M | ENG-001 | Ready for Review |
| ENG-003 | financial-engine | M07 | [Implement the refill decision table](issues/financial-engine/003-implement-the-refill-decision-table.md) | F-051 | M1 | P0 | S | ENG-002 | Ready for Review |
| ENG-004 | financial-engine | M07 | [Add property tests for buffer and limit safety](issues/financial-engine/004-add-property-tests-for-buffer-and-limit-safety.md) | F-051 | M1 | P0 | S | ENG-003 | Ready for Review |
| ENG-005 | financial-engine | M07 | [Model payment terms and their value function](issues/financial-engine/005-model-payment-terms-and-their-value-function.md) | F-035, F-052 | M1 | P0 | S | ENG-001 | Ready for Review |
| ENG-006 | financial-engine | M07 | [Implement the baseline scheduler B1 (earliest deadline first)](issues/financial-engine/006-implement-the-baseline-scheduler-b1-earliest-deadline-first.md) | F-052, F-092 | M1 | P0 | S | ENG-003, ENG-005 | Ready for Review |
| ENG-007 | financial-engine | M07 | [Implement the terms-aware scheduler](issues/financial-engine/007-implement-the-terms-aware-scheduler.md) | F-052 | M1 | P0 | L | ENG-006 | Ready for Review |
| ENG-008 | financial-engine | M07 | [Expose plan scoring and binding-constraint reporting](issues/financial-engine/008-expose-plan-scoring-and-binding-constraint-reporting.md) | F-052, F-053 | M1 | P0 | S | ENG-007 | Ready for Review |
| ENG-009 | financial-engine | M07 | [Implement invoice fingerprint normalization and hashing](issues/financial-engine/009-implement-invoice-fingerprint-normalization-and-hashing.md) | F-037 | M1 | P0 | S | ENG-001 | Ready for Review |
| ENG-010 | financial-engine | M07 | [Build EIP-712 typed data for approvals, exceptions and attestations](issues/financial-engine/010-build-eip-712-typed-data-for-approvals-exceptions-and-attest.md) | F-038, F-025, F-056 | M1 | P0 | M | SC-017, ENG-001 | Ready for Review |
| ENG-011 | financial-engine | M07 | [Implement the 7-day liquidity forecast](issues/financial-engine/011-implement-the-7-day-liquidity-forecast.md) | F-058 | M1 | P2 | S | ENG-003 | Ready for Review |
| ENG-L01 | financial-engine | M07 | [Plan refills from other operational wallets](issues/financial-engine/l01-plan-refills-from-other-operational-wallets.md) | F-059 | Later | - | M | ENG-007, SC-L06 | Needs Discussion |
| ENG-L02 | financial-engine | M07 | [Add FX conversion and depeg checks for fiat invoices](issues/financial-engine/l02-add-fx-conversion-and-depeg-checks-for-fiat-invoices.md) | F-041 | Later | - | M | ENG-005 | Needs Discussion |
| ENG-L03 | financial-engine | M07 | [Extend the scheduler to multiple assets](issues/financial-engine/l03-extend-the-scheduler-to-multiple-assets.md) | F-015 | Later | - | M | ENG-007 | Needs Discussion |
| POL-001 | policy-engine | M08 | [Define the reason-code catalogue and decision model](issues/policy-engine/001-define-the-reason-code-catalogue-and-decision-model.md) | F-055 | M1 | P0 | S | ENG-001 | Ready for Review |
| POL-002 | policy-engine | M08 | [Validate approval, mandate and payee conditions](issues/policy-engine/002-validate-approval-mandate-and-payee-conditions.md) | F-055 | M1 | P0 | M | POL-001, ENG-010 | Ready for Review |
| POL-003 | policy-engine | M08 | [Validate limits, buffers, deadlines, coverage and unknown operations](issues/policy-engine/003-validate-limits-buffers-deadlines-coverage-and-unknown-opera.md) | F-055 | M1 | P0 | M | POL-002 | Ready for Review |
| POL-004 | policy-engine | M08 | [Add differential tests between validator and contract](issues/policy-engine/004-add-differential-tests-between-validator-and-contract.md) | F-055, F-163 | M1 | P0 | M | POL-003, SC-013 | Ready for Review |
| POL-005 | policy-engine | M08 | [Define canonical plan encoding and planHash](issues/policy-engine/005-define-canonical-plan-encoding-and-planhash.md) | F-056 | M1 | P1 | S | ENG-010 | Ready for Review |
| POL-006 | policy-engine | M08 | [Sign and verify plan attestations](issues/policy-engine/006-sign-and-verify-plan-attestations.md) | F-056 | M1 | P1 | S | POL-005 | Ready for Review |
| IDN-001 | identity | M01 | [Create identity database schema and migrations](issues/identity/001-create-identity-database-schema-and-migrations.md) | F-001–F-005 | M1 | P0 | S | DEV-002 | Ready for Review |
| IDN-002 | identity | M01 | [Implement magic-link login, sessions and CSRF](issues/identity/002-implement-magic-link-login-sessions-and-csrf.md) | F-001 | M1 | P0 | M | IDN-001 | Ready for Review |
| IDN-003 | identity | M01 | [Rate-limit authentication endpoints](issues/identity/003-rate-limit-authentication-endpoints.md) | F-001 | M1 | P0 | S | IDN-002 | Ready for Review |
| IDN-004 | identity | M01 | [Implement SIWE wallet linking](issues/identity/004-implement-siwe-wallet-linking.md) | F-002 | M1 | P0 | M | IDN-002 | Ready for Review |
| IDN-005 | identity | M01 | [Implement organization creation and onboarding checklist](issues/identity/005-implement-organization-creation-and-onboarding-checklist.md) | F-003 | M1 | P0 | S | IDN-002 | Ready for Review |
| IDN-006 | identity | M01 | [Implement RBAC dependencies and tenant isolation](issues/identity/006-implement-rbac-dependencies-and-tenant-isolation.md) | F-004 | M1 | P0 | M | IDN-005 | Ready for Review |
| IDN-007 | identity | M01 | [Implement invites and membership management](issues/identity/007-implement-invites-and-membership-management.md) | F-004 | M1 | P1 | M | IDN-006 | Ready for Review |
| IDN-008 | identity | M01 | [Implement the maker-checker service and solo mode](issues/identity/008-implement-the-maker-checker-service-and-solo-mode.md) | F-005 | M1 | P0 | S | IDN-006 | Ready for Review |
| IDN-L01 | identity | M01 | [Add MFA and step-up authentication](issues/identity/l01-add-mfa-and-step-up-authentication.md) | F-006 | Later | - | L | IDN-002 | Needs Discussion |
| IDN-L02 | identity | M01 | [Add OIDC single sign-on](issues/identity/l02-add-oidc-single-sign-on.md) | F-007 | Later | - | L | IDN-006 | Needs Discussion |
| IDN-L03 | identity | M01 | [Add SAML and SCIM provisioning](issues/identity/l03-add-saml-and-scim-provisioning.md) | F-007 | Later | - | L | IDN-L02 | Needs Discussion |
| TRS-001 | treasury | M02 | [Create treasury and chain schema](issues/treasury/001-create-treasury-and-chain-schema.md) | F-010, F-013 | M1 | P0 | S | IDN-001 | Ready for Review |
| TRS-002 | treasury | M02 | [Load and validate platform chain configuration](issues/treasury/002-load-and-validate-platform-chain-configuration.md) | F-151 | M1 | P0 | S | TRS-001 | Ready for Review |
| TRS-003 | treasury | M02 | [Implement the asset registry with on-chain decimals check](issues/treasury/003-implement-the-asset-registry-with-on-chain-decimals-check.md) | F-013 | M1 | P0 | S | TRS-002, CHR-001 | Ready for Review |
| TRS-004 | treasury | M02 | [Implement treasury creation with Safe verification](issues/treasury/004-implement-treasury-creation-with-safe-verification.md) | F-010, F-011 | M1 | P0 | M | TRS-003, IDN-006 | Ready for Review |
| TRS-005 | treasury | M02 | [Read and snapshot Safe configuration](issues/treasury/005-read-and-snapshot-safe-configuration.md) | F-011 | M1 | P0 | S | TRS-004 | Ready for Review |
| TRS-006 | treasury | M02 | [Build the module deploy-and-enable Safe transaction](issues/treasury/006-build-the-module-deploy-and-enable-safe-transaction.md) | F-012 | M1 | P0 | M | TRS-004, SC-016 | Ready for Review |
| TRS-007 | treasury | M02 | [Compute coverage and handle acknowledgment](issues/treasury/007-compute-coverage-and-handle-acknowledgment.md) | F-012 | M1 | P0 | M | TRS-005, TRS-006 | Ready for Review |
| TRS-008 | treasury | M02 | [Build a Safe deployment transaction from the UI](issues/treasury/008-build-a-safe-deployment-transaction-from-the-ui.md) | F-011 | M1 | P2 | S | TRS-004 | Ready for Review |
| TRS-L01 | treasury | M02 | [Support multiple treasuries with a consolidated view](issues/treasury/l01-support-multiple-treasuries-with-a-consolidated-view.md) | F-014 | Later | - | M | TRS-004 | Needs Discussion |
| TRS-L02 | treasury | M02 | [Support multiple stablecoins per treasury](issues/treasury/l02-support-multiple-stablecoins-per-treasury.md) | F-015 | Later | - | M | TRS-L01, SC-L05 | Needs Discussion |
| MDT-001 | mandate | M03 | [Create mandate, payee and exception schema](issues/mandate/001-create-mandate-payee-and-exception-schema.md) | F-020–F-026 | M1 | P0 | S | TRS-001 | Ready for Review |
| MDT-002 | mandate | M03 | [Validate mandate drafts and generate summary and diff](issues/mandate/002-validate-mandate-drafts-and-generate-summary-and-diff.md) | F-020 | M1 | P0 | M | MDT-001, ENG-001 | Ready for Review |
| MDT-003 | mandate | M03 | [Implement mandate activation and read-back](issues/mandate/003-implement-mandate-activation-and-read-back.md) | F-021 | M1 | P0 | M | MDT-002, TRS-006, CHR-003 | Ready for Review |
| MDT-004 | mandate | M03 | [Implement vendor and payee proposals with screening](issues/mandate/004-implement-vendor-and-payee-proposals-with-screening.md) | F-022 | M1 | P0 | M | MDT-001, CMP-001 | Ready for Review |
| MDT-005 | mandate | M03 | [Build payee registration and deactivation transactions and sync status](issues/mandate/005-build-payee-registration-and-deactivation-transactions-and-s.md) | F-022 | M1 | P0 | M | MDT-004, CHR-005 | Ready for Review |
| MDT-006 | mandate | M03 | [Implement one-time exception records and signatures](issues/mandate/006-implement-one-time-exception-records-and-signatures.md) | F-025 | M1 | P1 | M | MDT-003, ENG-010, INV-010 | Ready for Review |
| MDT-007 | mandate | M03 | [Implement pause and resume (backend and transactions)](issues/mandate/007-implement-pause-and-resume-backend-and-transactions.md) | F-026 | M1 | P0 | M | MDT-003 | Ready for Review |
| MDT-008 | mandate | M03 | [Sync mandate expiry and status](issues/mandate/008-sync-mandate-expiry-and-status.md) | F-021 | M1 | P1 | S | MDT-003 | Ready for Review |
| MDT-L01 | mandate | M03 | [Configure threshold-based approval policies](issues/mandate/l01-configure-threshold-based-approval-policies.md) | F-029 | Later | - | M | MDT-002, SC-L02 | Needs Discussion |
| INV-001 | invoices | M05 | [Create invoice and request schema](issues/invoices/001-create-invoice-and-request-schema.md) | F-030–F-039 | M1 | P0 | S | MDT-001 | Ready for Review |
| INV-002 | invoices | M05 | [Implement the request state machine](issues/invoices/002-implement-the-request-state-machine.md) | F-039 | M1 | P0 | M | INV-001 | Ready for Review |
| INV-003 | invoices | M05 | [Implement manual request creation and editing](issues/invoices/003-implement-manual-request-creation-and-editing.md) | F-030 | M1 | P0 | M | INV-002, MDT-004 | Ready for Review |
| INV-004 | invoices | M05 | [Implement document upload to private storage](issues/invoices/004-implement-document-upload-to-private-storage.md) | F-031 | M1 | P0 | S | INV-003 | Ready for Review |
| INV-005 | invoices | M05 | [Implement CSV bulk import](issues/invoices/005-implement-csv-bulk-import.md) | F-032 | M1 | P1 | M | INV-003 | Ready for Review |
| INV-006 | invoices | M05 | [Compute fingerprints at intake and block duplicates](issues/invoices/006-compute-fingerprints-at-intake-and-block-duplicates.md) | F-037 | M1 | P0 | S | INV-003, ENG-009 | Ready for Review |
| INV-007 | invoices | M05 | [Implement deterministic anomaly checks](issues/invoices/007-implement-deterministic-anomaly-checks.md) | F-036 | M1 | P0 | M | INV-006 | Ready for Review |
| INV-008 | invoices | M05 | [Implement payment-terms confirmation](issues/invoices/008-implement-payment-terms-confirmation.md) | F-035 | M1 | P0 | S | INV-003, ENG-005 | Ready for Review |
| INV-009 | invoices | M05 | [Implement submit-for-approval and flag acknowledgment](issues/invoices/009-implement-submit-for-approval-and-flag-acknowledgment.md) | F-036, F-038 | M1 | P0 | S | INV-007, INV-008 | Ready for Review |
| INV-010 | invoices | M05 | [Implement approval typed data and signature verification](issues/invoices/010-implement-approval-typed-data-and-signature-verification.md) | F-038 | M1 | P0 | M | INV-009, ENG-010, IDN-008 | Ready for Review |
| INV-011 | invoices | M05 | [Implement reject, cancel, invalidation and expiry](issues/invoices/011-implement-reject-cancel-invalidation-and-expiry.md) | F-038, F-039 | M1 | P0 | S | INV-010 | Ready for Review |
| INV-L01 | invoices | M05 | [Add the email-forwarding invoice inbox](issues/invoices/l01-add-the-email-forwarding-invoice-inbox.md) | F-033 | Later | - | L | INV-004, AGT-004 | Needs Discussion |
| INV-L02 | invoices | M05 | [Add the inbound invoice API with scoped keys](issues/invoices/l02-add-the-inbound-invoice-api-with-scoped-keys.md) | F-034 | Later | - | M | INV-003 | Needs Discussion |
| INV-L03 | invoices | M05 | [Add recurring payment schedules](issues/invoices/l03-add-recurring-payment-schedules.md) | F-040 | Later | - | M | INV-003 | Needs Discussion |
| INV-L04 | invoices | M05 | [Support fiat-denominated invoices](issues/invoices/l04-support-fiat-denominated-invoices.md) | F-041 | Later | - | L | INV-003, ENG-L02 | Needs Discussion |
| CHR-001 | chain-reader | M06 | [Build the RPC client with failover](issues/chain-reader/001-build-the-rpc-client-with-failover.md) | F-050 | M1 | P0 | M | TRS-002 | Ready for Review |
| CHR-002 | chain-reader | M06 | [Implement block-consistent snapshots](issues/chain-reader/002-implement-block-consistent-snapshots.md) | F-050 | M1 | P0 | M | CHR-001, TRS-004 | Ready for Review |
| CHR-003 | chain-reader | M06 | [Implement the transaction tracker](issues/chain-reader/003-implement-the-transaction-tracker.md) | F-070 | M1 | P0 | M | CHR-001, EXE-001 | Ready for Review |
| CHR-004 | chain-reader | M06 | [Detect reorgs and re-evaluate status](issues/chain-reader/004-detect-reorgs-and-re-evaluate-status.md) | F-070 | M1 | P1 | S | CHR-003 | Ready for Review |
| CHR-005 | chain-reader | M06 | [Index module and Safe events](issues/chain-reader/005-index-module-and-safe-events.md) | F-050, F-120 | M1 | P1 | M | CHR-001, SC-016 | Ready for Review |
| EXE-001 | execution | M10 | [Create operations (outbox), transactions and gas ledger schema](issues/execution/001-create-operations-outbox-transactions-and-gas-ledger-schema.md) | F-061 | M1 | P0 | S | INV-001 | Ready for Review |
| EXE-002 | execution | M10 | [Set up Celery with core and ai queues](issues/execution/002-set-up-celery-with-core-and-ai-queues.md) | F-060, F-061 | M1 | P0 | M | DEV-002 | Ready for Review |
| EXE-003 | execution | M10 | [Implement the deadline trigger](issues/execution/003-implement-the-deadline-trigger.md) | F-060 | M1 | P0 | M | EXE-002, INV-010, MDT-007, TRS-007 | Ready for Review |
| EXE-004 | execution | M10 | [Implement the planning pipeline task](issues/execution/004-implement-the-planning-pipeline-task.md) | F-052–F-056 | M1 | P0 | L | EXE-003, CHR-002, ENG-008, POL-006, AGT-009 | Ready for Review |
| EXE-005 | execution | M10 | [Build the signer service](issues/execution/005-build-the-signer-service.md) | F-061 | M1 | P0 | L | POL-006, SC-016 | Ready for Review |
| EXE-006 | execution | M10 | [Load the executor key from an encrypted keystore](issues/execution/006-load-the-executor-key-from-an-encrypted-keystore.md) | F-061 | M1 | P0 | S | EXE-005 | Ready for Review |
| EXE-007 | execution | M10 | [Implement the executor with outbox semantics](issues/execution/007-implement-the-executor-with-outbox-semantics.md) | F-061–F-063 | M1 | P0 | M | EXE-005, EXE-001 | Ready for Review |
| EXE-008 | execution | M10 | [Sequence steps with re-read and re-validation](issues/execution/008-sequence-steps-with-re-read-and-re-validation.md) | F-061 | M1 | P0 | M | EXE-007, CHR-003, POL-003 | Ready for Review |
| EXE-009 | execution | M10 | [Add the operator run-now endpoint](issues/execution/009-add-the-operator-run-now-endpoint.md) | F-060 | M1 | P1 | S | EXE-003 | Ready for Review |
| EXE-010 | execution | M10 | [Track gas fees and alert on low executor gas](issues/execution/010-track-gas-fees-and-alert-on-low-executor-gas.md) | F-066 | M1 | P1 | S | EXE-007 | Ready for Review |
| EXE-011 | execution | M10 | [Execute the swap-for-gas step on the test router](issues/execution/011-execute-the-swap-for-gas-step-on-the-test-router.md) | F-064 | M1 | P2 | S | EXE-008, SC-018 | Ready for Review |
| EXE-L01 | execution | M10 | [Add a KMS-backed signer](issues/execution/l01-add-a-kms-backed-signer.md) | F-061 | Later | - | M | EXE-005 | Needs Discussion |
| EXE-L02 | execution | M10 | [Integrate the production swap adapter](issues/execution/l02-integrate-the-production-swap-adapter.md) | F-065 | Later | - | M | EXE-011, SC-L03 | Needs Discussion |
| EXE-L03 | execution | M10 | [Add cross-chain bridging](issues/execution/l03-add-cross-chain-bridging.md) | F-067 | Later | - | L | TRS-L01 | Needs Discussion |
| EXE-L04 | execution | M10 | [Partition workers by treasury for scale](issues/execution/l04-partition-workers-by-treasury-for-scale.md) | F-061 | Later | - | M | EXE-002 | Needs Discussion |
| REC-001 | reconciliation | M11 | [Verify post-conditions after each confirmed step](issues/reconciliation/001-verify-post-conditions-after-each-confirmed-step.md) | F-071 | M1 | P0 | M | EXE-008 | Ready for Review |
| REC-002 | reconciliation | M11 | [Build reconciliation records with classification](issues/reconciliation/002-build-reconciliation-records-with-classification.md) | F-072 | M1 | P0 | M | REC-001 | Ready for Review |
| REC-003 | reconciliation | M11 | [Implement match, discrepancy and auto-match](issues/reconciliation/003-implement-match-discrepancy-and-auto-match.md) | F-072 | M1 | P0 | S | REC-002 | Ready for Review |
| REC-004 | reconciliation | M11 | [Export reconciliation CSV and journal lines](issues/reconciliation/004-export-reconciliation-csv-and-journal-lines.md) | F-073 | M1 | P1 | M | REC-003 | Ready for Review |
| REC-005 | reconciliation | M11 | [Publish on-chain payment attestations](issues/reconciliation/005-publish-on-chain-payment-attestations.md) | F-074 | M1 | P2 | S | REC-003, SC-019 | Ready for Review |
| REC-L01 | reconciliation | M11 | [Build the ERP integration framework with Xero](issues/reconciliation/l01-build-the-erp-integration-framework-with-xero.md) | F-075 | Later | - | L | REC-004 | Needs Discussion |
| REC-L02 | reconciliation | M11 | [Add the QuickBooks connector](issues/reconciliation/l02-add-the-quickbooks-connector.md) | F-075 | Later | - | M | REC-L01 | Needs Discussion |
| REC-L03 | reconciliation | M11 | [Add the NetSuite connector](issues/reconciliation/l03-add-the-netsuite-connector.md) | F-075 | Later | - | M | REC-L01 | Needs Discussion |
| RCV-001 | recovery | M12 | [Scan in-flight operations at startup](issues/recovery/001-scan-in-flight-operations-at-startup.md) | F-080 | M1 | P0 | S | EXE-007 | Ready for Review |
| RCV-002 | recovery | M12 | [Resolve unknown operations from chain evidence](issues/recovery/002-resolve-unknown-operations-from-chain-evidence.md) | F-080 | M1 | P0 | M | RCV-001, CHR-003 | Ready for Review |
| RCV-003 | recovery | M12 | [Handle partial completion and resume](issues/recovery/003-handle-partial-completion-and-resume.md) | F-081 | M1 | P0 | S | EXE-008 | Ready for Review |
| RCV-004 | recovery | M12 | [Implement the review queue and routing](issues/recovery/004-implement-the-review-queue-and-routing.md) | F-082 | M1 | P0 | M | INV-002 | Ready for Review |
| RCV-005 | recovery | M12 | [Implement retry policy and error classification](issues/recovery/005-implement-retry-policy-and-error-classification.md) | F-083 | M1 | P0 | S | EXE-007 | Ready for Review |
| RCV-006 | recovery | M12 | [Implement circuit-breaker rules and auto-pause](issues/recovery/006-implement-circuit-breaker-rules-and-auto-pause.md) | F-027 | M1 | P2 | M | REC-001, MDT-007 | Ready for Review |
| RCV-007 | recovery | M12 | [Automate the crash-recovery test](issues/recovery/007-automate-the-crash-recovery-test.md) | F-080 | M1 | P0 | S | RCV-002 | Ready for Review |
| AGT-001 | agent | M09 | [Build the LLM adapter with routing and timeouts](issues/agent/001-build-the-llm-adapter-with-routing-and-timeouts.md) | F-094 | M1 | P0 | M | EXE-002 | Ready for Review |
| AGT-002 | agent | M09 | [Log every AI call and fail closed](issues/agent/002-log-every-ai-call-and-fail-closed.md) | F-093 | M1 | P0 | S | AGT-001 | Ready for Review |
| AGT-003 | agent | M09 | [Implement untrusted-content wrapping and sanitization](issues/agent/003-implement-untrusted-content-wrapping-and-sanitization.md) | F-091 | M1 | P0 | S | AGT-001 | Ready for Review |
| AGT-004 | agent | M09 | [Implement invoice extraction](issues/agent/004-implement-invoice-extraction.md) | F-031 | M1 | P0 | M | AGT-003, AGT-002, INV-004 | Ready for Review |
| AGT-005 | agent | M09 | [Extract and validate payment terms](issues/agent/005-extract-and-validate-payment-terms.md) | F-035 | M1 | P0 | S | AGT-004, ENG-005 | Ready for Review |
| AGT-006 | agent | M09 | [Detect instruction-like text in documents](issues/agent/006-detect-instruction-like-text-in-documents.md) | F-036, F-091 | M1 | P0 | S | AGT-004 | Ready for Review |
| AGT-007 | agent | M09 | [Implement the read-only tool layer](issues/agent/007-implement-the-read-only-tool-layer.md) | F-053, F-090 | M1 | P0 | M | CHR-002, ENG-008, POL-003 | Ready for Review |
| AGT-008 | agent | M09 | [Implement the plan proposer](issues/agent/008-implement-the-plan-proposer.md) | F-053 | M1 | P0 | M | AGT-007 | Ready for Review |
| AGT-009 | agent | M09 | [Score AI proposals and select the plan](issues/agent/009-score-ai-proposals-and-select-the-plan.md) | F-053 | M1 | P0 | S | AGT-008, ENG-008 | Ready for Review |
| AGT-010 | agent | M09 | [Implement rule-based fallback templates](issues/agent/010-implement-rule-based-fallback-templates.md) | F-054 | M1 | P0 | S | ENG-007, POL-003 | Ready for Review |
| AGT-011 | agent | M09 | [Draft exception requests with a numeric post-check](issues/agent/011-draft-exception-requests-with-a-numeric-post-check.md) | F-057 | M1 | P1 | S | AGT-001, MDT-006 | Ready for Review |
| AGT-012 | agent | M09 | [Build the Copilot backend](issues/agent/012-build-the-copilot-backend.md) | F-090 | M1 | P1 | L | AGT-007 | Ready for Review |
| AGT-013 | agent | M09 | [Build the extraction accuracy eval](issues/agent/013-build-the-extraction-accuracy-eval.md) | F-092 | M1 | P0 | S | AGT-005, DOM-004 | Ready for Review |
| AGT-014 | agent | M09 | [Build the planner benchmark (B1 vs B2)](issues/agent/014-build-the-planner-benchmark-b1-vs-b2.md) | F-092 | M1 | P0 | M | AGT-009, ENG-006, DOM-005 | Ready for Review |
| AGT-015 | agent | M09 | [Build the red-team suite runner](issues/agent/015-build-the-red-team-suite-runner.md) | F-091, F-163 | M1 | P0 | S | AGT-006, DOM-006 | Ready for Review |
| AGT-016 | agent | M09 | [Build the Copilot numeric-fidelity suite](issues/agent/016-build-the-copilot-numeric-fidelity-suite.md) | F-092 | M1 | P1 | S | AGT-012, DOM-007 | Ready for Review |
| AGT-017 | agent | M09 | [Add a secondary LLM provider fallback](issues/agent/017-add-a-secondary-llm-provider-fallback.md) | F-094 | M1 | P1 | M | AGT-001 | Ready for Review |
| NTF-001 | notifications | M13 | [Create the domain event bus and notification routing](issues/notifications/001-create-the-domain-event-bus-and-notification-routing.md) | F-100 | M1 | P1 | M | INV-002 | Ready for Review |
| NTF-002 | notifications | M13 | [Expose in-app notifications and the SSE stream](issues/notifications/002-expose-in-app-notifications-and-the-sse-stream.md) | F-100, F-132 | M1 | P1 | M | NTF-001 | Ready for Review |
| NTF-003 | notifications | M13 | [Add Telegram linking and delivery](issues/notifications/003-add-telegram-linking-and-delivery.md) | F-101 | M1 | P2 | M | NTF-001 | Ready for Review |
| NTF-L01 | notifications | M13 | [Add email notifications and digests](issues/notifications/l01-add-email-notifications-and-digests.md) | F-102 | Later | - | M | NTF-001 | Needs Discussion |
| NTF-L02 | notifications | M13 | [Add outbound webhooks](issues/notifications/l02-add-outbound-webhooks.md) | F-103 | Later | - | M | NTF-001 | Needs Discussion |
| NTF-L03 | notifications | M13 | [Add Slack, Lark and WeCom channels](issues/notifications/l03-add-slack-lark-and-wecom-channels.md) | F-104 | Later | - | L | NTF-001 | Needs Discussion |
| NTF-L04 | notifications | M13 | [Add notification preferences](issues/notifications/l04-add-notification-preferences.md) | F-105 | Later | - | S | NTF-002 | Needs Discussion |
| CMP-001 | compliance | M14 | [Build the screening adapter and fixture provider](issues/compliance/001-build-the-screening-adapter-and-fixture-provider.md) | F-110 | M1 | P1 | S | MDT-001 | Ready for Review |
| CMP-002 | compliance | M14 | [Screen payees before each PAY](issues/compliance/002-screen-payees-before-each-pay.md) | F-110 | M1 | P1 | S | CMP-001, POL-003 | Ready for Review |
| CMP-003 | compliance | M14 | [Implement data classification, encryption helpers and log redaction](issues/compliance/003-implement-data-classification-encryption-helpers-and-log-red.md) | F-113 | M1 | P0 | M | DEV-001 | Ready for Review |
| CMP-L01 | compliance | M14 | [Integrate a KYB provider](issues/compliance/l01-integrate-a-kyb-provider.md) | F-111 | Later | - | L | CMP-001 | Needs Discussion |
| CMP-L02 | compliance | M14 | [Add Travel Rule support](issues/compliance/l02-add-travel-rule-support.md) | F-112 | Later | - | L | CMP-L01 | Needs Discussion |
| CMP-L03 | compliance | M14 | [Add retention and deletion workflows](issues/compliance/l03-add-retention-and-deletion-workflows.md) | F-114 | Later | - | M | CMP-003 | Needs Discussion |
| CMP-L04 | compliance | M14 | [Add region pinning for stored data](issues/compliance/l04-add-region-pinning-for-stored-data.md) | F-114 | Later | - | M | CMP-L03 | Needs Discussion |
| AUD-001 | audit | M15 | [Implement the hash-chained audit log](issues/audit/001-implement-the-hash-chained-audit-log.md) | F-120 | M1 | P0 | M | IDN-001 | Ready for Review |
| AUD-002 | audit | M15 | [Add audit read and chain verification](issues/audit/002-add-audit-read-and-chain-verification.md) | F-120 | M1 | P0 | S | AUD-001 | Ready for Review |
| AUD-003 | audit | M15 | [Define the evidence bundle schema and exporter](issues/audit/003-define-the-evidence-bundle-schema-and-exporter.md) | F-121 | M1 | P0 | M | AUD-001, EXE-008 | Ready for Review |
| AUD-004 | audit | M15 | [Propagate coverage labels through the API](issues/audit/004-propagate-coverage-labels-through-the-api.md) | F-122 | M1 | P1 | S | CHR-002 | Ready for Review |
| AUD-L01 | audit | M15 | [Anchor the audit hash root on-chain daily](issues/audit/l01-anchor-the-audit-hash-root-on-chain-daily.md) | F-120 | Later | - | S | AUD-002 | Needs Discussion |
| OBS-001 | observability | M17 | [Configure structured logging with correlation ids](issues/observability/001-configure-structured-logging-with-correlation-ids.md) | F-142 | M1 | P1 | S | CMP-003 | Ready for Review |
| OBS-002 | observability | M17 | [Add OpenTelemetry tracing](issues/observability/002-add-opentelemetry-tracing.md) | F-142 | M1 | P1 | M | OBS-001 | Ready for Review |
| OBS-003 | observability | M17 | [Add Sentry and Prometheus metrics](issues/observability/003-add-sentry-and-prometheus-metrics.md) | F-142 | M1 | P1 | S | OBS-001 | Ready for Review |
| OBS-004 | observability | M17 | [Compute operational metrics](issues/observability/004-compute-operational-metrics.md) | F-140 | M1 | P1 | M | AUD-001, EXE-008 | Ready for Review |
| OBS-005 | observability | M17 | [Compute the savings report](issues/observability/005-compute-the-savings-report.md) | F-141 | M1 | P1 | M | OBS-004, ENG-006 | Ready for Review |
| ADM-L01 | admin | M18 | [Build the platform admin console](issues/admin/l01-build-the-platform-admin-console.md) | F-150 | Later | - | L | IDN-006 | Needs Discussion |
| ADM-L02 | admin | M18 | [Meter usage for billing](issues/admin/l02-meter-usage-for-billing.md) | F-152 | Later | - | M | OBS-004 | Needs Discussion |
| ADM-L03 | admin | M18 | [Add subscriptions and customer invoicing](issues/admin/l03-add-subscriptions-and-customer-invoicing.md) | F-152 | Later | - | L | ADM-L02 | Needs Discussion |
| WEB-001 | web | M16 | [Create the web app shell](issues/web/001-create-the-web-app-shell.md) | F-130 | M1 | P0 | M | DEV-001 | Ready for Review |
| WEB-002 | web | M16 | [Build login, org selection and onboarding checklist](issues/web/002-build-login-org-selection-and-onboarding-checklist.md) | F-001, F-003 | M1 | P0 | M | WEB-001, IDN-005 | Ready for Review |
| WEB-003 | web | M16 | [Add wallet connection and SIWE linking](issues/web/003-add-wallet-connection-and-siwe-linking.md) | F-002 | M1 | P0 | S | WEB-002, IDN-004 | Ready for Review |
| WEB-004 | web | M16 | [Build the treasury setup wizard](issues/web/004-build-the-treasury-setup-wizard.md) | F-010–F-012 | M1 | P0 | M | WEB-003, TRS-007 | Ready for Review |
| WEB-005 | web | M16 | [Build the mandate editor with summary, diff and activation](issues/web/005-build-the-mandate-editor-with-summary-diff-and-activation.md) | F-134, F-020, F-021 | M1 | P0 | L | WEB-004, MDT-003 | Ready for Review |
| WEB-006 | web | M16 | [Build the payee registry UI](issues/web/006-build-the-payee-registry-ui.md) | F-134, F-022 | M1 | P0 | M | WEB-004, MDT-005 | Ready for Review |
| WEB-007 | web | M16 | [Build the request list and manual entry form](issues/web/007-build-the-request-list-and-manual-entry-form.md) | F-030 | M1 | P0 | M | WEB-002, INV-003 | Ready for Review |
| WEB-008 | web | M16 | [Build upload and extraction review](issues/web/008-build-upload-and-extraction-review.md) | F-031, F-035 | M1 | P0 | L | WEB-007, AGT-005 | Ready for Review |
| WEB-009 | web | M16 | [Build the approval inbox and EIP-712 signing](issues/web/009-build-the-approval-inbox-and-eip-712-signing.md) | F-131, F-038 | M1 | P0 | L | WEB-008, INV-010 | Ready for Review |
| WEB-010 | web | M16 | [Build the treasury dashboard](issues/web/010-build-the-treasury-dashboard.md) | F-130 | M1 | P0 | M | WEB-004, CHR-002 | Ready for Review |
| WEB-011 | web | M16 | [Build plan cards and the Why panel](issues/web/011-build-plan-cards-and-the-why-panel.md) | F-132 | M1 | P0 | M | WEB-010, EXE-004 | Ready for Review |
| WEB-012 | web | M16 | [Build the live execution timeline](issues/web/012-build-the-live-execution-timeline.md) | F-132 | M1 | P0 | M | WEB-011, NTF-002 | Ready for Review |
| WEB-013 | web | M16 | [Build the exception and review console](issues/web/013-build-the-exception-and-review-console.md) | F-135 | M1 | P0 | L | WEB-011, RCV-004, MDT-006 | Ready for Review |
| WEB-014 | web | M16 | [Build the reconciliation view and export](issues/web/014-build-the-reconciliation-view-and-export.md) | F-133 | M1 | P0 | M | WEB-010, REC-004 | Ready for Review |
| WEB-015 | web | M16 | [Build the notifications center](issues/web/015-build-the-notifications-center.md) | F-100 | M1 | P1 | S | WEB-001, NTF-002 | Ready for Review |
| WEB-016 | web | M16 | [Build the Copilot chat UI](issues/web/016-build-the-copilot-chat-ui.md) | F-090 | M1 | P1 | M | WEB-010, AGT-012 | Ready for Review |
| WEB-017 | web | M16 | [Build members and roles administration](issues/web/017-build-members-and-roles-administration.md) | F-004 | M1 | P1 | M | WEB-002, IDN-007 | Ready for Review |
| WEB-018 | web | M16 | [Build metrics and savings pages](issues/web/018-build-metrics-and-savings-pages.md) | F-140, F-141 | M1 | P1 | M | WEB-010, OBS-005 | Ready for Review |
| WEB-019 | web | M16 | [Add pause and resume controls and status banners](issues/web/019-add-pause-and-resume-controls-and-status-banners.md) | F-026 | M1 | P0 | S | WEB-010, MDT-007 | Ready for Review |
| WEB-020 | web | M16 | [Build the CSV import UI](issues/web/020-build-the-csv-import-ui.md) | F-032 | M1 | P1 | S | WEB-007, INV-005 | Ready for Review |
| WEB-021 | web | M16 | [Build the runway forecast chart](issues/web/021-build-the-runway-forecast-chart.md) | F-058 | M1 | P2 | S | WEB-010, ENG-011 | Ready for Review |
| WEB-022 | web | M16 | [Run the accessibility and responsive pass](issues/web/022-run-the-accessibility-and-responsive-pass.md) | F-130–F-135 | M1 | P1 | S | WEB-014 | Ready for Review |
| WEB-023 | web | M16 | [Write the Playwright end-to-end happy path](issues/web/023-write-the-playwright-end-to-end-happy-path.md) | F-161 | M1 | P1 | M | WEB-012 | Ready for Review |
| DOM-001 | domain-evidence | M20 | [Decide the M1 chain (owner: Phúc)](issues/domain-evidence/001-decide-the-m1-chain-owner-ph-c.md) | F-010, F-151 | M1 | P0 | S | — | Ready for Review |
| DOM-002 | domain-evidence | M20 | [Decide the M1 stablecoin (owner: Phúc)](issues/domain-evidence/002-decide-the-m1-stablecoin-owner-ph-c.md) | F-013 | M1 | P0 | S | DOM-001 | Ready for Review |
| DOM-003 | domain-evidence | M20 | [Ask the organizers whether testnet evidence is accepted](issues/domain-evidence/003-ask-the-organizers-whether-testnet-evidence-is-accepted.md) | — | M1 | P0 | S | — | Ready for Review |
| DOM-004 | domain-evidence | M20 | [Author the labelled invoice dataset (30)](issues/domain-evidence/004-author-the-labelled-invoice-dataset-30.md) | F-092 | M1 | P0 | M | — | Ready for Review |
| DOM-005 | domain-evidence | M20 | [Author planner scenarios with ground truth (≥30)](issues/domain-evidence/005-author-planner-scenarios-with-ground-truth-30.md) | F-092 | M1 | P0 | L | — | Ready for Review |
| DOM-006 | domain-evidence | M20 | [Author the red-team invoice set (20)](issues/domain-evidence/006-author-the-red-team-invoice-set-20.md) | F-091, F-163 | M1 | P0 | M | — | Ready for Review |
| DOM-007 | domain-evidence | M20 | [Author Copilot question cases (20)](issues/domain-evidence/007-author-copilot-question-cases-20.md) | F-092 | M1 | P1 | S | DOM-005 | Ready for Review |
| DOM-008 | domain-evidence | M20 | [Review business rules and demo limits from a finance view](issues/domain-evidence/008-review-business-rules-and-demo-limits-from-a-finance-view.md) | — | M1 | P0 | S | — | Ready for Review |
| DOM-009 | domain-evidence | M20 | [Review the threat model and write the known-risk list](issues/domain-evidence/009-review-the-threat-model-and-write-the-known-risk-list.md) | — | M1 | P0 | M | — | Ready for Review |
| DOM-010 | domain-evidence | M20 | [Run customer interviews (2–3)](issues/domain-evidence/010-run-customer-interviews-2-3.md) | — | M1 | P1 | M | — | Ready for Review |
| DOM-011 | domain-evidence | M20 | [Write the security self-assessment report](issues/domain-evidence/011-write-the-security-self-assessment-report.md) | — | M1 | P0 | M | DOM-009, SC-015 | Ready for Review |
| DOM-012 | domain-evidence | M20 | [Assemble the technical documentation for submission](issues/domain-evidence/012-assemble-the-technical-documentation-for-submission.md) | — | M1 | P0 | M | DOM-011 | Ready for Review |
| DOM-013 | domain-evidence | M20 | [Create the 10-minute presentation deck](issues/domain-evidence/013-create-the-10-minute-presentation-deck.md) | — | M1 | P0 | M | DOM-008 | Ready for Review |
| DOM-014 | domain-evidence | M20 | [Script and record the 5-minute demo video](issues/domain-evidence/014-script-and-record-the-5-minute-demo-video.md) | — | M1 | P0 | M | DEV-008 | Ready for Review |
| DOM-015 | domain-evidence | M20 | [Write the compliance positioning note and license inventory](issues/domain-evidence/015-write-the-compliance-positioning-note-and-license-inventory.md) | — | M1 | P1 | S | — | Ready for Review |
| DOM-016 | domain-evidence | M20 | [Update the FigJam board from the repo diagrams](issues/domain-evidence/016-update-the-figjam-board-from-the-repo-diagrams.md) | — | M1 | P2 | S | — | Ready for Review |
| DOM-017 | domain-evidence | M20 | [Choose the repository license](issues/domain-evidence/017-choose-the-repository-license.md) | — | M1 | P1 | S | — | Ready for Review |
