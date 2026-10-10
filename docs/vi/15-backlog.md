# TreasuryPilot: Backlog & phụ thuộc

**Nguồn chuẩn:** `planning/BACKLOG.md`, `planning/DEPENDENCIES.md`, `planning/issues/` · **Trạng thái:** Chờ team review (cổng G3)

Tiêu đề ticket giữ nguyên tiếng Anh vì GitHub issue viết bằng tiếng Anh (quyết định Q4). Mỗi ticket có file riêng trong `planning/issues/<module>/`, gồm đủ: bối cảnh, mục tiêu, phạm vi, ngoài phạm vi, ghi chú kỹ thuật, phụ thuộc, tiêu chí nghiệm thu, yêu cầu test, Definition of Done.

## 1. Tổng số

| Phase | P0 | P1 | P2 | Tổng |
|---|---:|---:|---:|---:|
| M1 (bản thi) | 127 | 46 | 10 | 183 |
| Later | – | – | – | 38 |
| **Tất cả** | | | | **221** |

Kích thước: S ≤ 0,5 ngày · M khoảng 1 ngày · L 1,5–2 ngày (nếu phình ra thì phải tách).

## 2. Epic theo module

| Epic | Module | Ticket M1 | Ticket Later | Ước tính công M1 (ngày) |
|---|---|---:|---:|---:|
| M19 · Developer Experience & Quality | `devex` | 11 | 0 | 8 |
| M04 · Smart Contracts | `contracts` | 20 | 6 | 15.5 |
| M07 · Financial Engine (py-core) | `financial-engine` | 11 | 3 | 8.5 |
| M08 · Policy Engine & Attestation | `policy-engine` | 6 | 0 | 4.5 |
| M01 · Identity & Access | `identity` | 8 | 3 | 6 |
| M02 · Treasury & Chain Configuration | `treasury` | 8 | 2 | 5.5 |
| M03 · Mandate, Payees, Exceptions & Pause | `mandate` | 8 | 1 | 7 |
| M05 · Invoices & Payment Requests | `invoices` | 11 | 4 | 8 |
| M06 · Chain Reader & Tx Tracking | `chain-reader` | 5 | 0 | 4.5 |
| M09 · AI Agent | `agent` | 17 | 0 | 13 |
| M10 · Orchestration & Execution | `execution` | 11 | 4 | 10.5 |
| M11 · Verification & Reconciliation | `reconciliation` | 5 | 3 | 4 |
| M12 · Recovery & Exceptions | `recovery` | 7 | 0 | 5 |
| M13 · Notifications | `notifications` | 3 | 4 | 3 |
| M14 · Compliance | `compliance` | 3 | 4 | 2 |
| M15 · Audit & Evidence | `audit` | 4 | 1 | 3 |
| M16 · Web Application | `web` | 23 | 0 | 24 |
| M17 · Observability & Analytics | `observability` | 5 | 0 | 4 |
| M18 · Platform Admin & Billing | `admin` | 0 | 3 | 0 |
| M20 · Domain & Evidence (non-code) | `domain-evidence` | 17 | 0 | 14 |

## 3. Toàn bộ ticket

| ID | Module | Ticket | Feature | Phase | Ưu tiên | Cỡ | Phụ thuộc | Trạng thái |
|---|---|---|---|---|---|---|---|---|
| DEV-001 | devex | Initialize monorepo skeleton | F-160 | M1 | P0 | M | — | Ready for Review |
| DEV-002 | devex | Create Docker Compose stack (local profile) | F-160 | M1 | P0 | M | DEV-001 | Ready for Review |
| DEV-003 | devex | Add CI workflow for Python | F-161 | M1 | P1 | S | DEV-001 | Ready for Review |
| DEV-004 | devex | Add CI workflow for contracts | F-161, F-163 | M1 | P1 | S | SC-001 | Ready for Review |
| DEV-005 | devex | Add CI workflow for web and OpenAPI client drift | F-161 | M1 | P1 | S | WEB-001 | Ready for Review |
| DEV-006 | devex | Write seed script for the local environment | F-160 | M1 | P1 | M | SC-016, TRS-004, MDT-003, INV-003 | Ready for Review |
| DEV-007 | devex | Build scenario runner CLI | F-162 | M1 | P1 | M | DEV-006, AUD-003 | Ready for Review |
| DEV-008 | devex | Write the demo runbook | F-162 | M1 | P1 | S | DEV-007 | Ready for Review |
| DEV-009 | devex | Build the reliability run harness | F-164 | M1 | P1 | S | DEV-007 | Ready for Review |
| DEV-010 | devex | Add testnet profile and VM deployment | F-160, F-151 | M1 | P1 | M | DEV-002, DOM-001, SC-016 | Ready for Review |
| DEV-011 | devex | Enforce module boundaries with import-linter | F-161 | M1 | P1 | S | DEV-001 | Ready for Review |
| SC-001 | contracts | Set up the Foundry project with pinned dependencies | F-163 | M1 | P0 | S | DEV-001 | Ready for Review |
| SC-002 | contracts | Define module storage, structs, EIP-712 domain, errors and events | F-021, F-038 | M1 | P0 | M | SC-001 | Ready for Review |
| SC-003 | contracts | Implement mandate governance and versioning | F-021 | M1 | P0 | M | SC-002 | Ready for Review |
| SC-004 | contracts | Implement the payee registry with cooling period | F-022 | M1 | P0 | S | SC-003 | Ready for Review |
| SC-005 | contracts | Implement approval signature verification | F-038 | M1 | P0 | M | SC-002 | Ready for Review |
| SC-006 | contracts | Implement pay() core flow | F-063 | M1 | P0 | M | SC-004, SC-005 | Ready for Review |
| SC-007 | contracts | Implement per-request limits and UTC daily counters | F-023 | M1 | P0 | M | SC-006 | Ready for Review |
| SC-008 | contracts | Enforce minimum buffers on pay and refill | F-024 | M1 | P0 | S | SC-006 | Ready for Review |
| SC-009 | contracts | Implement refill() bound to an approved request | F-062 | M1 | P0 | M | SC-005, SC-007, SC-008 | Ready for Review |
| SC-010 | contracts | Implement pause, resume, revoke and guardian | F-026 | M1 | P0 | S | SC-003 | Ready for Review |
| SC-011 | contracts | Implement one-time exception verification and consumption | F-025 | M1 | P1 | M | SC-007 | Ready for Review |
| SC-012 | contracts | Add the duplicate-invoice fingerprint registry | F-037 | M1 | P0 | S | SC-006 | Ready for Review |
| SC-013 | contracts | Write the contract acceptance test suite (AT cases) | F-163 | M1 | P0 | M | SC-009, SC-010, SC-012 | Ready for Review |
| SC-014 | contracts | Write the invariant and fuzz suite | F-163 | M1 | P0 | M | SC-013 | Ready for Review |
| SC-015 | contracts | Run static analysis and write the findings report | F-163 | M1 | P0 | S | SC-013 | Ready for Review |
| SC-016 | contracts | Write deployment scripts and the deployments manifest | F-151 | M1 | P0 | M | SC-010 | Ready for Review |
| SC-017 | contracts | Publish EIP-712 golden vectors | F-038, F-056 | M1 | P0 | S | SC-005 | Ready for Review |
| SC-018 | contracts | Add the test router and swapForGas | F-064 | M1 | P2 | M | SC-009 | Ready for Review |
| SC-019 | contracts | Register the attestation schema and add an attest helper | F-074 | M1 | P2 | S | DOM-001 | Ready for Review |
| SC-020 | contracts | Write direct-call bypass tests | F-163 | M1 | P0 | S | SC-013 | Ready for Review |
| SC-L01 | contracts | Enforce reserves and execution holds on-chain | F-028 | Later | - | L | SC-014 | Needs Discussion |
| SC-L02 | contracts | Enforce n-of-m approval thresholds by amount band | F-029 | Later | - | L | SC-005 | Needs Discussion |
| SC-L03 | contracts | Add a production swap adapter with signed quotes | F-065 | Later | - | L | SC-018 | Needs Discussion |
| SC-L04 | contracts | Verify plan attestations on-chain | F-056 | Later | - | M | SC-017 | Needs Discussion |
| SC-L05 | contracts | Support multiple stablecoins with per-asset limits | F-015 | Later | - | M | SC-007 | Needs Discussion |
| SC-L06 | contracts | Allow refill paths between operational wallets | F-059 | Later | - | M | SC-009 | Needs Discussion |
| ENG-001 | financial-engine | Create py-core money types and domain models | F-013, F-051 | M1 | P0 | M | DEV-001 | Ready for Review |
| ENG-002 | financial-engine | Implement the liquidity calculator | F-051 | M1 | P0 | M | ENG-001 | Ready for Review |
| ENG-003 | financial-engine | Implement the refill decision table | F-051 | M1 | P0 | S | ENG-002 | Ready for Review |
| ENG-004 | financial-engine | Add property tests for buffer and limit safety | F-051 | M1 | P0 | S | ENG-003 | Ready for Review |
| ENG-005 | financial-engine | Model payment terms and their value function | F-035, F-052 | M1 | P0 | S | ENG-001 | Ready for Review |
| ENG-006 | financial-engine | Implement the baseline scheduler B1 (earliest deadline first) | F-052, F-092 | M1 | P0 | S | ENG-003, ENG-005 | Ready for Review |
| ENG-007 | financial-engine | Implement the terms-aware scheduler | F-052 | M1 | P0 | L | ENG-006 | Ready for Review |
| ENG-008 | financial-engine | Expose plan scoring and binding-constraint reporting | F-052, F-053 | M1 | P0 | S | ENG-007 | Ready for Review |
| ENG-009 | financial-engine | Implement invoice fingerprint normalization and hashing | F-037 | M1 | P0 | S | ENG-001 | Ready for Review |
| ENG-010 | financial-engine | Build EIP-712 typed data for approvals, exceptions and attestations | F-038, F-025, F-056 | M1 | P0 | M | SC-017, ENG-001 | Ready for Review |
| ENG-011 | financial-engine | Implement the 7-day liquidity forecast | F-058 | M1 | P2 | S | ENG-003 | Ready for Review |
| ENG-L01 | financial-engine | Plan refills from other operational wallets | F-059 | Later | - | M | ENG-007, SC-L06 | Needs Discussion |
| ENG-L02 | financial-engine | Add FX conversion and depeg checks for fiat invoices | F-041 | Later | - | M | ENG-005 | Needs Discussion |
| ENG-L03 | financial-engine | Extend the scheduler to multiple assets | F-015 | Later | - | M | ENG-007 | Needs Discussion |
| POL-001 | policy-engine | Define the reason-code catalogue and decision model | F-055 | M1 | P0 | S | ENG-001 | Ready for Review |
| POL-002 | policy-engine | Validate approval, mandate and payee conditions | F-055 | M1 | P0 | M | POL-001, ENG-010 | Ready for Review |
| POL-003 | policy-engine | Validate limits, buffers, deadlines, coverage and unknown operations | F-055 | M1 | P0 | M | POL-002 | Ready for Review |
| POL-004 | policy-engine | Add differential tests between validator and contract | F-055, F-163 | M1 | P0 | M | POL-003, SC-013 | Ready for Review |
| POL-005 | policy-engine | Define canonical plan encoding and planHash | F-056 | M1 | P1 | S | ENG-010 | Ready for Review |
| POL-006 | policy-engine | Sign and verify plan attestations | F-056 | M1 | P1 | S | POL-005 | Ready for Review |
| IDN-001 | identity | Create identity database schema and migrations | F-001–F-005 | M1 | P0 | S | DEV-002 | Ready for Review |
| IDN-002 | identity | Implement magic-link login, sessions and CSRF | F-001 | M1 | P0 | M | IDN-001 | Ready for Review |
| IDN-003 | identity | Rate-limit authentication endpoints | F-001 | M1 | P0 | S | IDN-002 | Ready for Review |
| IDN-004 | identity | Implement SIWE wallet linking | F-002 | M1 | P0 | M | IDN-002 | Ready for Review |
| IDN-005 | identity | Implement organization creation and onboarding checklist | F-003 | M1 | P0 | S | IDN-002 | Ready for Review |
| IDN-006 | identity | Implement RBAC dependencies and tenant isolation | F-004 | M1 | P0 | M | IDN-005 | Ready for Review |
| IDN-007 | identity | Implement invites and membership management | F-004 | M1 | P1 | M | IDN-006 | Ready for Review |
| IDN-008 | identity | Implement the maker-checker service and solo mode | F-005 | M1 | P0 | S | IDN-006 | Ready for Review |
| IDN-L01 | identity | Add MFA and step-up authentication | F-006 | Later | - | L | IDN-002 | Needs Discussion |
| IDN-L02 | identity | Add OIDC single sign-on | F-007 | Later | - | L | IDN-006 | Needs Discussion |
| IDN-L03 | identity | Add SAML and SCIM provisioning | F-007 | Later | - | L | IDN-L02 | Needs Discussion |
| TRS-001 | treasury | Create treasury and chain schema | F-010, F-013 | M1 | P0 | S | IDN-001 | Ready for Review |
| TRS-002 | treasury | Load and validate platform chain configuration | F-151 | M1 | P0 | S | TRS-001 | Ready for Review |
| TRS-003 | treasury | Implement the asset registry with on-chain decimals check | F-013 | M1 | P0 | S | TRS-002, CHR-001 | Ready for Review |
| TRS-004 | treasury | Implement treasury creation with Safe verification | F-010, F-011 | M1 | P0 | M | TRS-003, IDN-006 | Ready for Review |
| TRS-005 | treasury | Read and snapshot Safe configuration | F-011 | M1 | P0 | S | TRS-004 | Ready for Review |
| TRS-006 | treasury | Build the module deploy-and-enable Safe transaction | F-012 | M1 | P0 | M | TRS-004, SC-016 | Ready for Review |
| TRS-007 | treasury | Compute coverage and handle acknowledgment | F-012 | M1 | P0 | M | TRS-005, TRS-006 | Ready for Review |
| TRS-008 | treasury | Build a Safe deployment transaction from the UI | F-011 | M1 | P2 | S | TRS-004 | Ready for Review |
| TRS-L01 | treasury | Support multiple treasuries with a consolidated view | F-014 | Later | - | M | TRS-004 | Needs Discussion |
| TRS-L02 | treasury | Support multiple stablecoins per treasury | F-015 | Later | - | M | TRS-L01, SC-L05 | Needs Discussion |
| MDT-001 | mandate | Create mandate, payee and exception schema | F-020–F-026 | M1 | P0 | S | TRS-001 | Ready for Review |
| MDT-002 | mandate | Validate mandate drafts and generate summary and diff | F-020 | M1 | P0 | M | MDT-001, ENG-001 | Ready for Review |
| MDT-003 | mandate | Implement mandate activation and read-back | F-021 | M1 | P0 | M | MDT-002, TRS-006, CHR-003 | Ready for Review |
| MDT-004 | mandate | Implement vendor and payee proposals with screening | F-022 | M1 | P0 | M | MDT-001, CMP-001 | Ready for Review |
| MDT-005 | mandate | Build payee registration and deactivation transactions and sync status | F-022 | M1 | P0 | M | MDT-004, CHR-005 | Ready for Review |
| MDT-006 | mandate | Implement one-time exception records and signatures | F-025 | M1 | P1 | M | MDT-003, ENG-010, INV-010 | Ready for Review |
| MDT-007 | mandate | Implement pause and resume (backend and transactions) | F-026 | M1 | P0 | M | MDT-003 | Ready for Review |
| MDT-008 | mandate | Sync mandate expiry and status | F-021 | M1 | P1 | S | MDT-003 | Ready for Review |
| MDT-L01 | mandate | Configure threshold-based approval policies | F-029 | Later | - | M | MDT-002, SC-L02 | Needs Discussion |
| INV-001 | invoices | Create invoice and request schema | F-030–F-039 | M1 | P0 | S | MDT-001 | Ready for Review |
| INV-002 | invoices | Implement the request state machine | F-039 | M1 | P0 | M | INV-001 | Ready for Review |
| INV-003 | invoices | Implement manual request creation and editing | F-030 | M1 | P0 | M | INV-002, MDT-004 | Ready for Review |
| INV-004 | invoices | Implement document upload to private storage | F-031 | M1 | P0 | S | INV-003 | Ready for Review |
| INV-005 | invoices | Implement CSV bulk import | F-032 | M1 | P1 | M | INV-003 | Ready for Review |
| INV-006 | invoices | Compute fingerprints at intake and block duplicates | F-037 | M1 | P0 | S | INV-003, ENG-009 | Ready for Review |
| INV-007 | invoices | Implement deterministic anomaly checks | F-036 | M1 | P0 | M | INV-006 | Ready for Review |
| INV-008 | invoices | Implement payment-terms confirmation | F-035 | M1 | P0 | S | INV-003, ENG-005 | Ready for Review |
| INV-009 | invoices | Implement submit-for-approval and flag acknowledgment | F-036, F-038 | M1 | P0 | S | INV-007, INV-008 | Ready for Review |
| INV-010 | invoices | Implement approval typed data and signature verification | F-038 | M1 | P0 | M | INV-009, ENG-010, IDN-008 | Ready for Review |
| INV-011 | invoices | Implement reject, cancel, invalidation and expiry | F-038, F-039 | M1 | P0 | S | INV-010 | Ready for Review |
| INV-L01 | invoices | Add the email-forwarding invoice inbox | F-033 | Later | - | L | INV-004, AGT-004 | Needs Discussion |
| INV-L02 | invoices | Add the inbound invoice API with scoped keys | F-034 | Later | - | M | INV-003 | Needs Discussion |
| INV-L03 | invoices | Add recurring payment schedules | F-040 | Later | - | M | INV-003 | Needs Discussion |
| INV-L04 | invoices | Support fiat-denominated invoices | F-041 | Later | - | L | INV-003, ENG-L02 | Needs Discussion |
| CHR-001 | chain-reader | Build the RPC client with failover | F-050 | M1 | P0 | M | TRS-002 | Ready for Review |
| CHR-002 | chain-reader | Implement block-consistent snapshots | F-050 | M1 | P0 | M | CHR-001, TRS-004 | Ready for Review |
| CHR-003 | chain-reader | Implement the transaction tracker | F-070 | M1 | P0 | M | CHR-001, EXE-001 | Ready for Review |
| CHR-004 | chain-reader | Detect reorgs and re-evaluate status | F-070 | M1 | P1 | S | CHR-003 | Ready for Review |
| CHR-005 | chain-reader | Index module and Safe events | F-050, F-120 | M1 | P1 | M | CHR-001, SC-016 | Ready for Review |
| EXE-001 | execution | Create operations (outbox), transactions and gas ledger schema | F-061 | M1 | P0 | S | INV-001 | Ready for Review |
| EXE-002 | execution | Set up Celery with core and ai queues | F-060, F-061 | M1 | P0 | M | DEV-002 | Ready for Review |
| EXE-003 | execution | Implement the deadline trigger | F-060 | M1 | P0 | M | EXE-002, INV-010, MDT-007, TRS-007 | Ready for Review |
| EXE-004 | execution | Implement the planning pipeline task | F-052–F-056 | M1 | P0 | L | EXE-003, CHR-002, ENG-008, POL-006, AGT-009 | Ready for Review |
| EXE-005 | execution | Build the signer service | F-061 | M1 | P0 | L | POL-006, SC-016 | Ready for Review |
| EXE-006 | execution | Load the executor key from an encrypted keystore | F-061 | M1 | P0 | S | EXE-005 | Ready for Review |
| EXE-007 | execution | Implement the executor with outbox semantics | F-061–F-063 | M1 | P0 | M | EXE-005, EXE-001 | Ready for Review |
| EXE-008 | execution | Sequence steps with re-read and re-validation | F-061 | M1 | P0 | M | EXE-007, CHR-003, POL-003 | Ready for Review |
| EXE-009 | execution | Add the operator run-now endpoint | F-060 | M1 | P1 | S | EXE-003 | Ready for Review |
| EXE-010 | execution | Track gas fees and alert on low executor gas | F-066 | M1 | P1 | S | EXE-007 | Ready for Review |
| EXE-011 | execution | Execute the swap-for-gas step on the test router | F-064 | M1 | P2 | S | EXE-008, SC-018 | Ready for Review |
| EXE-L01 | execution | Add a KMS-backed signer | F-061 | Later | - | M | EXE-005 | Needs Discussion |
| EXE-L02 | execution | Integrate the production swap adapter | F-065 | Later | - | M | EXE-011, SC-L03 | Needs Discussion |
| EXE-L03 | execution | Add cross-chain bridging | F-067 | Later | - | L | TRS-L01 | Needs Discussion |
| EXE-L04 | execution | Partition workers by treasury for scale | F-061 | Later | - | M | EXE-002 | Needs Discussion |
| REC-001 | reconciliation | Verify post-conditions after each confirmed step | F-071 | M1 | P0 | M | EXE-008 | Ready for Review |
| REC-002 | reconciliation | Build reconciliation records with classification | F-072 | M1 | P0 | M | REC-001 | Ready for Review |
| REC-003 | reconciliation | Implement match, discrepancy and auto-match | F-072 | M1 | P0 | S | REC-002 | Ready for Review |
| REC-004 | reconciliation | Export reconciliation CSV and journal lines | F-073 | M1 | P1 | M | REC-003 | Ready for Review |
| REC-005 | reconciliation | Publish on-chain payment attestations | F-074 | M1 | P2 | S | REC-003, SC-019 | Ready for Review |
| REC-L01 | reconciliation | Build the ERP integration framework with Xero | F-075 | Later | - | L | REC-004 | Needs Discussion |
| REC-L02 | reconciliation | Add the QuickBooks connector | F-075 | Later | - | M | REC-L01 | Needs Discussion |
| REC-L03 | reconciliation | Add the NetSuite connector | F-075 | Later | - | M | REC-L01 | Needs Discussion |
| RCV-001 | recovery | Scan in-flight operations at startup | F-080 | M1 | P0 | S | EXE-007 | Ready for Review |
| RCV-002 | recovery | Resolve unknown operations from chain evidence | F-080 | M1 | P0 | M | RCV-001, CHR-003 | Ready for Review |
| RCV-003 | recovery | Handle partial completion and resume | F-081 | M1 | P0 | S | EXE-008 | Ready for Review |
| RCV-004 | recovery | Implement the review queue and routing | F-082 | M1 | P0 | M | INV-002 | Ready for Review |
| RCV-005 | recovery | Implement retry policy and error classification | F-083 | M1 | P0 | S | EXE-007 | Ready for Review |
| RCV-006 | recovery | Implement circuit-breaker rules and auto-pause | F-027 | M1 | P2 | M | REC-001, MDT-007 | Ready for Review |
| RCV-007 | recovery | Automate the crash-recovery test | F-080 | M1 | P0 | S | RCV-002 | Ready for Review |
| AGT-001 | agent | Build the LLM adapter with routing and timeouts | F-094 | M1 | P0 | M | EXE-002 | Ready for Review |
| AGT-002 | agent | Log every AI call and fail closed | F-093 | M1 | P0 | S | AGT-001 | Ready for Review |
| AGT-003 | agent | Implement untrusted-content wrapping and sanitization | F-091 | M1 | P0 | S | AGT-001 | Ready for Review |
| AGT-004 | agent | Implement invoice extraction | F-031 | M1 | P0 | M | AGT-003, AGT-002, INV-004 | Ready for Review |
| AGT-005 | agent | Extract and validate payment terms | F-035 | M1 | P0 | S | AGT-004, ENG-005 | Ready for Review |
| AGT-006 | agent | Detect instruction-like text in documents | F-036, F-091 | M1 | P0 | S | AGT-004 | Ready for Review |
| AGT-007 | agent | Implement the read-only tool layer | F-053, F-090 | M1 | P0 | M | CHR-002, ENG-008, POL-003 | Ready for Review |
| AGT-008 | agent | Implement the plan proposer | F-053 | M1 | P0 | M | AGT-007 | Ready for Review |
| AGT-009 | agent | Score AI proposals and select the plan | F-053 | M1 | P0 | S | AGT-008, ENG-008 | Ready for Review |
| AGT-010 | agent | Implement rule-based fallback templates | F-054 | M1 | P0 | S | ENG-007, POL-003 | Ready for Review |
| AGT-011 | agent | Draft exception requests with a numeric post-check | F-057 | M1 | P1 | S | AGT-001, MDT-006 | Ready for Review |
| AGT-012 | agent | Build the Copilot backend | F-090 | M1 | P1 | L | AGT-007 | Ready for Review |
| AGT-013 | agent | Build the extraction accuracy eval | F-092 | M1 | P0 | S | AGT-005, DOM-004 | Ready for Review |
| AGT-014 | agent | Build the planner benchmark (B1 vs B2) | F-092 | M1 | P0 | M | AGT-009, ENG-006, DOM-005 | Ready for Review |
| AGT-015 | agent | Build the red-team suite runner | F-091, F-163 | M1 | P0 | S | AGT-006, DOM-006 | Ready for Review |
| AGT-016 | agent | Build the Copilot numeric-fidelity suite | F-092 | M1 | P1 | S | AGT-012, DOM-007 | Ready for Review |
| AGT-017 | agent | Add a secondary LLM provider fallback | F-094 | M1 | P1 | M | AGT-001 | Ready for Review |
| NTF-001 | notifications | Create the domain event bus and notification routing | F-100 | M1 | P1 | M | INV-002 | Ready for Review |
| NTF-002 | notifications | Expose in-app notifications and the SSE stream | F-100, F-132 | M1 | P1 | M | NTF-001 | Ready for Review |
| NTF-003 | notifications | Add Telegram linking and delivery | F-101 | M1 | P2 | M | NTF-001 | Ready for Review |
| NTF-L01 | notifications | Add email notifications and digests | F-102 | Later | - | M | NTF-001 | Needs Discussion |
| NTF-L02 | notifications | Add outbound webhooks | F-103 | Later | - | M | NTF-001 | Needs Discussion |
| NTF-L03 | notifications | Add Slack, Lark and WeCom channels | F-104 | Later | - | L | NTF-001 | Needs Discussion |
| NTF-L04 | notifications | Add notification preferences | F-105 | Later | - | S | NTF-002 | Needs Discussion |
| CMP-001 | compliance | Build the screening adapter and fixture provider | F-110 | M1 | P1 | S | MDT-001 | Ready for Review |
| CMP-002 | compliance | Screen payees before each PAY | F-110 | M1 | P1 | S | CMP-001, POL-003 | Ready for Review |
| CMP-003 | compliance | Implement data classification, encryption helpers and log redaction | F-113 | M1 | P0 | M | DEV-001 | Ready for Review |
| CMP-L01 | compliance | Integrate a KYB provider | F-111 | Later | - | L | CMP-001 | Needs Discussion |
| CMP-L02 | compliance | Add Travel Rule support | F-112 | Later | - | L | CMP-L01 | Needs Discussion |
| CMP-L03 | compliance | Add retention and deletion workflows | F-114 | Later | - | M | CMP-003 | Needs Discussion |
| CMP-L04 | compliance | Add region pinning for stored data | F-114 | Later | - | M | CMP-L03 | Needs Discussion |
| AUD-001 | audit | Implement the hash-chained audit log | F-120 | M1 | P0 | M | IDN-001 | Ready for Review |
| AUD-002 | audit | Add audit read and chain verification | F-120 | M1 | P0 | S | AUD-001 | Ready for Review |
| AUD-003 | audit | Define the evidence bundle schema and exporter | F-121 | M1 | P0 | M | AUD-001, EXE-008 | Ready for Review |
| AUD-004 | audit | Propagate coverage labels through the API | F-122 | M1 | P1 | S | CHR-002 | Ready for Review |
| AUD-L01 | audit | Anchor the audit hash root on-chain daily | F-120 | Later | - | S | AUD-002 | Needs Discussion |
| OBS-001 | observability | Configure structured logging with correlation ids | F-142 | M1 | P1 | S | CMP-003 | Ready for Review |
| OBS-002 | observability | Add OpenTelemetry tracing | F-142 | M1 | P1 | M | OBS-001 | Ready for Review |
| OBS-003 | observability | Add Sentry and Prometheus metrics | F-142 | M1 | P1 | S | OBS-001 | Ready for Review |
| OBS-004 | observability | Compute operational metrics | F-140 | M1 | P1 | M | AUD-001, EXE-008 | Ready for Review |
| OBS-005 | observability | Compute the savings report | F-141 | M1 | P1 | M | OBS-004, ENG-006 | Ready for Review |
| ADM-L01 | admin | Build the platform admin console | F-150 | Later | - | L | IDN-006 | Needs Discussion |
| ADM-L02 | admin | Meter usage for billing | F-152 | Later | - | M | OBS-004 | Needs Discussion |
| ADM-L03 | admin | Add subscriptions and customer invoicing | F-152 | Later | - | L | ADM-L02 | Needs Discussion |
| WEB-001 | web | Create the web app shell | F-130 | M1 | P0 | M | DEV-001 | Ready for Review |
| WEB-002 | web | Build login, org selection and onboarding checklist | F-001, F-003 | M1 | P0 | M | WEB-001, IDN-005 | Ready for Review |
| WEB-003 | web | Add wallet connection and SIWE linking | F-002 | M1 | P0 | S | WEB-002, IDN-004 | Ready for Review |
| WEB-004 | web | Build the treasury setup wizard | F-010–F-012 | M1 | P0 | M | WEB-003, TRS-007 | Ready for Review |
| WEB-005 | web | Build the mandate editor with summary, diff and activation | F-134, F-020, F-021 | M1 | P0 | L | WEB-004, MDT-003 | Ready for Review |
| WEB-006 | web | Build the payee registry UI | F-134, F-022 | M1 | P0 | M | WEB-004, MDT-005 | Ready for Review |
| WEB-007 | web | Build the request list and manual entry form | F-030 | M1 | P0 | M | WEB-002, INV-003 | Ready for Review |
| WEB-008 | web | Build upload and extraction review | F-031, F-035 | M1 | P0 | L | WEB-007, AGT-005 | Ready for Review |
| WEB-009 | web | Build the approval inbox and EIP-712 signing | F-131, F-038 | M1 | P0 | L | WEB-008, INV-010 | Ready for Review |
| WEB-010 | web | Build the treasury dashboard | F-130 | M1 | P0 | M | WEB-004, CHR-002 | Ready for Review |
| WEB-011 | web | Build plan cards and the Why panel | F-132 | M1 | P0 | M | WEB-010, EXE-004 | Ready for Review |
| WEB-012 | web | Build the live execution timeline | F-132 | M1 | P0 | M | WEB-011, NTF-002 | Ready for Review |
| WEB-013 | web | Build the exception and review console | F-135 | M1 | P0 | L | WEB-011, RCV-004, MDT-006 | Ready for Review |
| WEB-014 | web | Build the reconciliation view and export | F-133 | M1 | P0 | M | WEB-010, REC-004 | Ready for Review |
| WEB-015 | web | Build the notifications center | F-100 | M1 | P1 | S | WEB-001, NTF-002 | Ready for Review |
| WEB-016 | web | Build the Copilot chat UI | F-090 | M1 | P1 | M | WEB-010, AGT-012 | Ready for Review |
| WEB-017 | web | Build members and roles administration | F-004 | M1 | P1 | M | WEB-002, IDN-007 | Ready for Review |
| WEB-018 | web | Build metrics and savings pages | F-140, F-141 | M1 | P1 | M | WEB-010, OBS-005 | Ready for Review |
| WEB-019 | web | Add pause and resume controls and status banners | F-026 | M1 | P0 | S | WEB-010, MDT-007 | Ready for Review |
| WEB-020 | web | Build the CSV import UI | F-032 | M1 | P1 | S | WEB-007, INV-005 | Ready for Review |
| WEB-021 | web | Build the runway forecast chart | F-058 | M1 | P2 | S | WEB-010, ENG-011 | Ready for Review |
| WEB-022 | web | Run the accessibility and responsive pass | F-130–F-135 | M1 | P1 | S | WEB-014 | Ready for Review |
| WEB-023 | web | Write the Playwright end-to-end happy path | F-161 | M1 | P1 | M | WEB-012 | Ready for Review |
| DOM-001 | domain-evidence | Decide the M1 chain (owner: Phúc) | F-010, F-151 | M1 | P0 | S | — | Ready for Review |
| DOM-002 | domain-evidence | Decide the M1 stablecoin (owner: Phúc) | F-013 | M1 | P0 | S | DOM-001 | Ready for Review |
| DOM-003 | domain-evidence | Ask the organizers whether testnet evidence is accepted | — | M1 | P0 | S | — | Ready for Review |
| DOM-004 | domain-evidence | Author the labelled invoice dataset (30) | F-092 | M1 | P0 | M | — | Ready for Review |
| DOM-005 | domain-evidence | Author planner scenarios with ground truth (≥30) | F-092 | M1 | P0 | L | — | Ready for Review |
| DOM-006 | domain-evidence | Author the red-team invoice set (20) | F-091, F-163 | M1 | P0 | M | — | Ready for Review |
| DOM-007 | domain-evidence | Author Copilot question cases (20) | F-092 | M1 | P1 | S | DOM-005 | Ready for Review |
| DOM-008 | domain-evidence | Review business rules and demo limits from a finance view | — | M1 | P0 | S | — | Ready for Review |
| DOM-009 | domain-evidence | Review the threat model and write the known-risk list | — | M1 | P0 | M | — | Ready for Review |
| DOM-010 | domain-evidence | Run customer interviews (2–3) | — | M1 | P1 | M | — | Ready for Review |
| DOM-011 | domain-evidence | Write the security self-assessment report | — | M1 | P0 | M | DOM-009, SC-015 | Ready for Review |
| DOM-012 | domain-evidence | Assemble the technical documentation for submission | — | M1 | P0 | M | DOM-011 | Ready for Review |
| DOM-013 | domain-evidence | Create the 10-minute presentation deck | — | M1 | P0 | M | DOM-008 | Ready for Review |
| DOM-014 | domain-evidence | Script and record the 5-minute demo video | — | M1 | P0 | M | DEV-008 | Ready for Review |
| DOM-015 | domain-evidence | Write the compliance positioning note and license inventory | — | M1 | P1 | S | — | Ready for Review |
| DOM-016 | domain-evidence | Update the FigJam board from the repo diagrams | — | M1 | P2 | S | — | Ready for Review |
| DOM-017 | domain-evidence | Choose the repository license | — | M1 | P1 | S | — | Ready for Review |

## 4. Phụ thuộc

- **Chặn (blocking):** ticket B không bắt đầu được khi ticket A chưa merge. Được liệt kê trong mục *Dependencies* của từng ticket.
- **Mềm (soft):** B có thể bắt đầu với dữ liệu giả hoặc phản hồi ghi sẵn rồi tích hợp sau. Ví dụ: các trang web làm theo schema OpenAPI trước khi endpoint xong; trích xuất hóa đơn chạy với phản hồi model ghi sẵn.
- **Song song:** không phụ thuộc nhau. Ví dụ: contract ‖ financial engine ‖ định danh ‖ khung web ‖ toàn bộ ticket của nhóm cố vấn.

### Các đợt thực hiện (M1)

Ticket trong cùng một đợt không chặn nhau nên **làm song song được**.

| Đợt | Số ticket |
|---|---:|
| 1 | 12 |
| 2 | 11 |
| 3 | 10 |
| 4 | 9 |
| 5 | 15 |
| 6 | 10 |
| 7 | 15 |
| 8 | 11 |
| 9 | 17 |
| 10 | 14 |
| 11 | 14 |
| 12 | 16 |
| 13 | 13 |
| 14 | 7 |
| 15 | 4 |
| 16 | 3 |
| 17 | 2 |

### Chuỗi phụ thuộc dài nhất

Bất kỳ ticket nào trên chuỗi này trễ thì cuối M1 trễ theo:

DEV-001 → SC-001 → SC-002 → SC-005 → SC-017 → ENG-010 → POL-005 → POL-006 → EXE-005 → EXE-007 → EXE-008 → REC-001 → REC-002 → REC-003 → REC-004 → WEB-014 → WEB-022

