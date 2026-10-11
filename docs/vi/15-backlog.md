# TreasuryPilot: Backlog & phụ thuộc

**Nguồn chuẩn:** `planning/BACKLOG.md`, `planning/DEPENDENCIES.md`, `planning/issues/` · **Trạng thái:** Đã qua G3; cập nhật sau grilling các module (11/10/2026)

Tiêu đề ticket giữ tiếng Anh vì GitHub issue viết bằng tiếng Anh (Q4). Mỗi ticket có file riêng trong `planning/issues/<module>/` và một issue trên GitHub Project #1.

## 1. Tổng số

| Phase | P0 | P1 | P2 | Tổng |
|---|---:|---:|---:|---:|
| M1 (bản thi) | 144 | 52 | 10 | 206 |
| Later | – | – | – | 38 |
| **Tất cả** | | | | **244** |

Kích thước: S ≤ 0,5 ngày · M khoảng 1 ngày · L 1,5–2 ngày. Cut: A = bắt buộc cho bản demo nộp bài (khép kín phụ thuộc), B = nên có, còn lại làm sau khi nộp.

## 2. Epic theo module

| Epic | Module | Ticket M1 | Tier A | Ticket Later | Ước tính công M1 (ngày) |
|---|---|---:|---:|---:|---:|
| M19 · Developer Experience & Quality | `devex` | 12 | 8 | 0 | 8.5 |
| M04 · Smart Contracts | `contracts` | 26 | 23 | 6 | 20 |
| M07 · Financial Engine (py-core) | `financial-engine` | 14 | 11 | 3 | 10 |
| M08 · Policy Engine & Attestation | `policy-engine` | 7 | 6 | 0 | 5 |
| M01 · Identity & Access | `identity` | 8 | 6 | 3 | 6 |
| M02 · Treasury & Chain Configuration | `treasury` | 8 | 7 | 2 | 5.5 |
| M03 · Mandate, Payees, Exceptions & Pause | `mandate` | 11 | 7 | 1 | 10 |
| M05 · Invoices & Payment Requests | `invoices` | 12 | 10 | 4 | 8.5 |
| M06 · Chain Reader & Tx Tracking | `chain-reader` | 6 | 5 | 0 | 5 |
| M09 · AI Agent | `agent` | 17 | 12 | 0 | 13 |
| M10 · Orchestration & Execution | `execution` | 14 | 11 | 4 | 12.5 |
| M11 · Verification & Reconciliation | `reconciliation` | 5 | 3 | 3 | 4 |
| M12 · Recovery & Exceptions | `recovery` | 7 | 3 | 0 | 5 |
| M13 · Notifications | `notifications` | 3 | 2 | 4 | 3 |
| M14 · Compliance | `compliance` | 3 | 1 | 4 | 2 |
| M15 · Audit & Evidence | `audit` | 4 | 2 | 1 | 3 |
| M16 · Web Application | `web` | 27 | 12 | 0 | 26.5 |
| M17 · Observability & Analytics | `observability` | 5 | 0 | 0 | 4 |
| M18 · Platform Admin & Billing | `admin` | 0 | 0 | 3 | 0 |
| M20 · Domain & Evidence (non-code) | `domain-evidence` | 17 | 11 | 0 | 14 |

## 3. Toàn bộ ticket

| ID | Module | Ticket | Feature | Phase | Ưu tiên | Cỡ | Cut | Phụ thuộc | Trạng thái |
|---|---|---|---|---|---|---|---|---|---|
| DEV-001 | devex | Initialize monorepo skeleton | F-160 | M1 | P0 | M | A | — | Sẵn sàng phân công |
| DEV-002 | devex | Create Docker Compose stack (local profile) | F-160 | M1 | P0 | M | A | DEV-001 | Sẵn sàng phân công |
| DEV-003 | devex | Add CI workflow for Python | F-161 | M1 | P1 | S | A | DEV-001 | Sẵn sàng phân công |
| DEV-004 | devex | Add CI workflow for contracts | F-161, F-163 | M1 | P1 | S | B | SC-001 | Sẵn sàng phân công |
| DEV-005 | devex | Add CI workflow for web and OpenAPI client drift | F-161 | M1 | P1 | S | After submission | WEB-001 | Sẵn sàng phân công |
| DEV-006 | devex | Write seed script for the local environment | F-160 | M1 | P1 | M | A | SC-016, TRS-004, MDT-003, INV-003 | Sẵn sàng phân công |
| DEV-007 | devex | Build scenario runner CLI | F-162 | M1 | P1 | M | A | DEV-006, AUD-003 | Sẵn sàng phân công |
| DEV-008 | devex | Write the demo runbook | F-162 | M1 | P1 | S | A | DEV-007 | Sẵn sàng phân công |
| DEV-009 | devex | Build the reliability run harness | F-164 | M1 | P1 | S | After submission | DEV-007 | Sẵn sàng phân công |
| DEV-010 | devex | Add testnet profile and VM deployment | F-160, F-151 | M1 | P1 | M | A | DEV-002, DOM-001, SC-016 | Sẵn sàng phân công |
| DEV-011 | devex | Enforce module boundaries with import-linter | F-161 | M1 | P1 | S | After submission | DEV-001 | Sẵn sàng phân công |
| SC-001 | contracts | Set up the Foundry project with pinned dependencies | F-163 | M1 | P0 | S | A | DEV-001 | Sẵn sàng phân công |
| SC-002 | contracts | Define module storage, structs, EIP-712 domain, errors and events | F-021, F-038 | M1 | P0 | M | A | SC-001 | Sẵn sàng phân công |
| SC-003 | contracts | Implement mandate governance and versioning | F-021 | M1 | P0 | M | A | SC-021 | Sẵn sàng phân công |
| SC-004 | contracts | Implement the payee registry with cooling period | F-022 | M1 | P0 | S | A | SC-003 | Sẵn sàng phân công |
| SC-005 | contracts | Implement approval signature verification | F-038 | M1 | P0 | M | A | SC-002 | Sẵn sàng phân công |
| SC-006 | contracts | Implement pay() core flow | F-063 | M1 | P0 | M | A | SC-004, SC-005 | Sẵn sàng phân công |
| SC-007 | contracts | Implement per-request limits and UTC daily counters | F-023 | M1 | P0 | M | A | SC-006 | Sẵn sàng phân công |
| SC-008 | contracts | Enforce minimum buffers on pay and refill | F-024 | M1 | P0 | S | A | SC-006 | Sẵn sàng phân công |
| SC-009 | contracts | Implement refill() bound to an approved request | F-062 | M1 | P0 | M | A | SC-005, SC-007, SC-008 | Sẵn sàng phân công |
| SC-010 | contracts | Implement pause, resume, revoke and guardian | F-026 | M1 | P0 | S | A | SC-003 | Sẵn sàng phân công |
| SC-011 | contracts | Implement one-time exceptions via owner governance | F-025 | M1 | P1 | M | B | SC-007 | Sẵn sàng phân công |
| SC-012 | contracts | Add the duplicate-invoice fingerprint registry and owner override | F-037 | M1 | P0 | S | A | SC-006 | Sẵn sàng phân công |
| SC-013 | contracts | Write the contract acceptance test suite (AT cases) | F-163 | M1 | P0 | M | A | SC-009, SC-010, SC-012 | Sẵn sàng phân công |
| SC-014 | contracts | Write the invariant and fuzz suite | F-163 | M1 | P0 | M | A | SC-013, SC-022 | Sẵn sàng phân công |
| SC-015 | contracts | Run static analysis and write the findings report | F-163 | M1 | P0 | S | A | SC-013 | Sẵn sàng phân công |
| SC-016 | contracts | Write deployment scripts and the deployments manifest | F-151 | M1 | P0 | M | A | SC-010, SC-021, DOM-001 | Sẵn sàng phân công |
| SC-017 | contracts | Publish EIP-712 golden vectors | F-038, F-056 | M1 | P0 | S | A | SC-005 | Sẵn sàng phân công |
| SC-018 | contracts | Add the test router and swapForGas | F-064 | M1 | P2 | M | After submission | SC-009 | Sẵn sàng phân công |
| SC-019 | contracts | Register the attestation schema and add an attest helper | F-074 | M1 | P1 | S | A | DOM-001 | Sẵn sàng phân công |
| SC-020 | contracts | Write direct-call bypass tests | F-163 | M1 | P0 | S | A | SC-013 | Sẵn sàng phân công |
| SC-L01 | contracts | Enforce reserves and execution holds on-chain | F-028 | Later | - | L | Later | SC-014 | Đã chấp nhận (Later) |
| SC-L02 | contracts | Enforce n-of-m approval thresholds by amount band | F-029 | Later | - | L | Later | SC-005 | Đã chấp nhận (Later) |
| SC-L03 | contracts | Add a production swap adapter with signed quotes | F-065 | Later | - | L | Later | SC-018 | Đã chấp nhận (Later) |
| SC-L04 | contracts | Verify plan attestations on-chain | F-056 | Later | - | M | Later | SC-017 | Đã chấp nhận (Later) |
| SC-L05 | contracts | Support multiple stablecoins with per-asset limits | F-015 | Later | - | M | Later | SC-007 | Đã chấp nhận (Later) |
| SC-L06 | contracts | Allow refill paths between operational wallets | F-059 | Later | - | M | Later | SC-009 | Đã chấp nhận (Later) |
| ENG-001 | financial-engine | Create py-core money types and domain models | F-013, F-051 | M1 | P0 | M | A | DEV-001 | Sẵn sàng phân công |
| ENG-002 | financial-engine | Implement the liquidity calculator | F-051 | M1 | P0 | M | A | ENG-001 | Sẵn sàng phân công |
| ENG-003 | financial-engine | Implement the refill decision table | F-051 | M1 | P0 | S | A | ENG-002 | Sẵn sàng phân công |
| ENG-004 | financial-engine | Add property tests for buffer and limit safety | F-051 | M1 | P0 | S | After submission | ENG-003 | Sẵn sàng phân công |
| ENG-005 | financial-engine | Model payment terms and their value function | F-035, F-052 | M1 | P0 | S | A | ENG-001 | Sẵn sàng phân công |
| ENG-006 | financial-engine | Implement the baseline scheduler B1 (earliest deadline first) | F-052, F-092 | M1 | P0 | S | A | ENG-003, ENG-005 | Sẵn sàng phân công |
| ENG-007 | financial-engine | Implement the terms-aware scheduler with OR-Tools CP-SAT | F-052 | M1 | P0 | L | A | ENG-006, ENG-012 | Sẵn sàng phân công |
| ENG-008 | financial-engine | Expose plan scoring and binding-constraint reporting | F-052, F-053 | M1 | P0 | S | A | ENG-007 | Sẵn sàng phân công |
| ENG-009 | financial-engine | Implement invoice fingerprint normalization and hashing | F-037 | M1 | P0 | S | A | ENG-001 | Sẵn sàng phân công |
| ENG-010 | financial-engine | Build EIP-712 typed data for payment approvals and attestations | F-038, F-025, F-056 | M1 | P0 | M | A | SC-017, ENG-001 | Sẵn sàng phân công |
| ENG-011 | financial-engine | Implement the 7-day liquidity forecast | F-058 | M1 | P2 | S | After submission | ENG-003 | Sẵn sàng phân công |
| ENG-L01 | financial-engine | Plan refills from other operational wallets | F-059 | Later | - | M | Later | ENG-007, SC-L06 | Đã chấp nhận (Later) |
| ENG-L02 | financial-engine | Add FX conversion and depeg checks for fiat invoices | F-041 | Later | - | M | Later | ENG-005 | Đã chấp nhận (Later) |
| ENG-L03 | financial-engine | Extend the scheduler to multiple assets | F-015 | Later | - | M | Later | ENG-007 | Đã chấp nhận (Later) |
| POL-001 | policy-engine | Define the reason-code catalogue and decision model | F-055 | M1 | P0 | S | A | ENG-001 | Sẵn sàng phân công |
| POL-002 | policy-engine | Validate approval, mandate and payee conditions | F-055 | M1 | P0 | M | A | POL-001, ENG-010 | Sẵn sàng phân công |
| POL-003 | policy-engine | Validate limits, buffers, deadlines, coverage and unknown operations | F-055 | M1 | P0 | M | A | POL-002 | Sẵn sàng phân công |
| POL-004 | policy-engine | Add differential tests between validator and contract | F-055, F-163 | M1 | P0 | M | After submission | POL-003, SC-013 | Sẵn sàng phân công |
| POL-005 | policy-engine | Define canonical plan encoding and planHash | F-056 | M1 | P1 | S | A | ENG-010 | Sẵn sàng phân công |
| POL-006 | policy-engine | Sign and verify EIP-712 plan attestations with the policy key | F-056 | M1 | P1 | S | A | POL-005 | Sẵn sàng phân công |
| IDN-001 | identity | Create identity database schema and migrations | F-001–F-005 | M1 | P0 | S | A | DEV-002 | Sẵn sàng phân công |
| IDN-002 | identity | Implement magic-link login, sessions and CSRF | F-001 | M1 | P0 | M | A | IDN-001 | Sẵn sàng phân công |
| IDN-003 | identity | Rate-limit authentication endpoints | F-001 | M1 | P0 | S | B | IDN-002 | Sẵn sàng phân công |
| IDN-004 | identity | Implement SIWE wallet linking | F-002 | M1 | P0 | M | A | IDN-002 | Sẵn sàng phân công |
| IDN-005 | identity | Implement organization creation and onboarding checklist | F-003 | M1 | P0 | S | A | IDN-002 | Sẵn sàng phân công |
| IDN-006 | identity | Implement RBAC dependencies and tenant isolation | F-004 | M1 | P0 | M | A | IDN-005 | Sẵn sàng phân công |
| IDN-007 | identity | Implement invites and membership management | F-004 | M1 | P1 | M | After submission | IDN-006 | Sẵn sàng phân công |
| IDN-008 | identity | Implement the maker-checker service and solo mode | F-005 | M1 | P0 | S | A | IDN-006 | Sẵn sàng phân công |
| IDN-L01 | identity | Add MFA and step-up authentication | F-006 | Later | - | L | Later | IDN-002 | Đã chấp nhận (Later) |
| IDN-L02 | identity | Add OIDC single sign-on | F-007 | Later | - | L | Later | IDN-006 | Đã chấp nhận (Later) |
| IDN-L03 | identity | Add SAML and SCIM provisioning | F-007 | Later | - | L | Later | IDN-L02 | Đã chấp nhận (Later) |
| TRS-001 | treasury | Create treasury and chain schema | F-010, F-013 | M1 | P0 | S | A | IDN-001 | Sẵn sàng phân công |
| TRS-002 | treasury | Load and validate platform chain configuration | F-151 | M1 | P0 | S | A | TRS-001 | Sẵn sàng phân công |
| TRS-003 | treasury | Implement the asset registry with on-chain decimals check | F-013 | M1 | P0 | S | A | TRS-002, CHR-001 | Sẵn sàng phân công |
| TRS-004 | treasury | Implement treasury creation with Safe verification | F-010, F-011 | M1 | P0 | M | A | TRS-003, IDN-006 | Sẵn sàng phân công |
| TRS-005 | treasury | Read and snapshot Safe configuration | F-011 | M1 | P0 | S | A | TRS-004 | Sẵn sàng phân công |
| TRS-006 | treasury | Build the module deploy-and-enable Safe transaction | F-012 | M1 | P0 | M | A | TRS-004, SC-016, SC-021, MDT-009 | Sẵn sàng phân công |
| TRS-007 | treasury | Compute coverage and handle acknowledgment | F-012 | M1 | P0 | M | A | TRS-005, TRS-006 | Sẵn sàng phân công |
| TRS-008 | treasury | Build a Safe deployment transaction from the UI | F-011 | M1 | P2 | S | After submission | TRS-004 | Sẵn sàng phân công |
| TRS-L01 | treasury | Support multiple treasuries with a consolidated view | F-014 | Later | - | M | Later | TRS-004 | Đã chấp nhận (Later) |
| TRS-L02 | treasury | Support multiple stablecoins per treasury | F-015 | Later | - | M | Later | TRS-L01, SC-L05 | Đã chấp nhận (Later) |
| MDT-001 | mandate | Create mandate, payee and exception schema | F-020–F-026 | M1 | P0 | S | A | TRS-001 | Sẵn sàng phân công |
| MDT-002 | mandate | Validate mandate drafts and generate summary and diff | F-020 | M1 | P0 | M | A | MDT-001, ENG-001 | Sẵn sàng phân công |
| MDT-003 | mandate | Implement mandate activation and read-back | F-021 | M1 | P0 | M | A | MDT-002, MDT-009, TRS-006, CHR-003 | Sẵn sàng phân công |
| MDT-004 | mandate | Implement vendor and payee proposals with screening | F-022 | M1 | P0 | M | A | MDT-001, CMP-001 | Sẵn sàng phân công |
| MDT-005 | mandate | Build payee registration and deactivation transactions and sync status | F-022 | M1 | P0 | M | B | MDT-004, MDT-009, CHR-005 | Sẵn sàng phân công |
| MDT-006 | mandate | Implement one-time exception requests and owner grant transactions | F-025 | M1 | P1 | M | B | MDT-003, MDT-009, INV-010 | Sẵn sàng phân công |
| MDT-007 | mandate | Implement pause and resume (backend and transactions) | F-026 | M1 | P0 | M | A | MDT-003, MDT-009, EXE-013 | Sẵn sàng phân công |
| MDT-008 | mandate | Sync mandate expiry and status | F-021 | M1 | P1 | S | After submission | MDT-003 | Sẵn sàng phân công |
| MDT-L01 | mandate | Configure threshold-based approval policies | F-029 | Later | - | M | Later | MDT-002, SC-L02 | Đã chấp nhận (Later) |
| INV-001 | invoices | Create invoice and request schema | F-030–F-039 | M1 | P0 | S | A | MDT-001 | Sẵn sàng phân công |
| INV-002 | invoices | Implement the request state machine | F-039 | M1 | P0 | M | A | INV-001 | Sẵn sàng phân công |
| INV-003 | invoices | Implement manual request creation and editing | F-030 | M1 | P0 | M | A | INV-002, MDT-004 | Sẵn sàng phân công |
| INV-004 | invoices | Implement document upload to private storage | F-031 | M1 | P0 | S | A | INV-003 | Sẵn sàng phân công |
| INV-005 | invoices | Implement CSV bulk import | F-032 | M1 | P1 | M | After submission | INV-003 | Sẵn sàng phân công |
| INV-006 | invoices | Compute fingerprints at intake and block duplicates | F-037 | M1 | P0 | S | A | INV-003, ENG-009 | Sẵn sàng phân công |
| INV-007 | invoices | Implement deterministic anomaly checks | F-036 | M1 | P0 | M | A | INV-006 | Sẵn sàng phân công |
| INV-008 | invoices | Implement payment-terms confirmation | F-035 | M1 | P0 | S | A | INV-003, ENG-005 | Sẵn sàng phân công |
| INV-009 | invoices | Implement submit-for-approval and flag acknowledgment | F-036, F-038 | M1 | P0 | S | A | INV-007, INV-008 | Sẵn sàng phân công |
| INV-010 | invoices | Implement approval typed data and signature verification | F-038 | M1 | P0 | M | A | INV-009, ENG-010, IDN-008 | Sẵn sàng phân công |
| INV-011 | invoices | Implement reject, cancel, invalidation and expiry | F-038, F-039 | M1 | P0 | S | B | INV-010, SC-022, MDT-009 | Sẵn sàng phân công |
| INV-L01 | invoices | Add the email-forwarding invoice inbox | F-033 | Later | - | L | Later | INV-004, AGT-004 | Đã chấp nhận (Later) |
| INV-L02 | invoices | Add the inbound invoice API with scoped keys | F-034 | Later | - | M | Later | INV-003 | Đã chấp nhận (Later) |
| INV-L03 | invoices | Add recurring payment schedules | F-040 | Later | - | M | Later | INV-003 | Đã chấp nhận (Later) |
| INV-L04 | invoices | Support fiat-denominated invoices | F-041 | Later | - | L | Later | INV-003, ENG-L02 | Đã chấp nhận (Later) |
| CHR-001 | chain-reader | Build the RPC client with failover | F-050 | M1 | P0 | M | A | TRS-002 | Sẵn sàng phân công |
| CHR-002 | chain-reader | Implement block-consistent snapshots | F-050 | M1 | P0 | M | A | CHR-001, TRS-004 | Sẵn sàng phân công |
| CHR-003 | chain-reader | Implement the transaction tracker | F-070 | M1 | P0 | M | A | CHR-001, EXE-001 | Sẵn sàng phân công |
| CHR-004 | chain-reader | Detect reorgs and re-evaluate status | F-070 | M1 | P1 | S | After submission | CHR-003 | Sẵn sàng phân công |
| CHR-005 | chain-reader | Index module and Safe events | F-050, F-120 | M1 | P1 | M | A | CHR-001, SC-016 | Sẵn sàng phân công |
| EXE-001 | execution | Create operations (outbox), transactions and gas ledger schema | F-061 | M1 | P0 | S | A | INV-001 | Sẵn sàng phân công |
| EXE-002 | execution | Set up Celery with core and ai queues | F-060, F-061 | M1 | P0 | M | A | DEV-002 | Sẵn sàng phân công |
| EXE-003 | execution | Implement the deadline trigger | F-060 | M1 | P0 | M | A | EXE-002, INV-010, MDT-007, TRS-007 | Sẵn sàng phân công |
| EXE-004 | execution | Implement the planning pipeline task | F-052–F-056 | M1 | P0 | L | A | EXE-003, CHR-002, ENG-008, POL-006, AGT-009, EXE-012 | Sẵn sàng phân công |
| EXE-005 | execution | Build the signer service | F-061 | M1 | P0 | L | A | POL-006, POL-007, SC-016 | Sẵn sàng phân công |
| EXE-006 | execution | Load the executor key from an encrypted keystore | F-061 | M1 | P0 | S | A | EXE-005 | Sẵn sàng phân công |
| EXE-007 | execution | Implement the executor with outbox semantics | F-061–F-063 | M1 | P0 | M | A | EXE-005, EXE-001 | Sẵn sàng phân công |
| EXE-008 | execution | Sequence steps with re-read and re-validation | F-061 | M1 | P0 | M | A | EXE-007, CHR-003, POL-003, POL-007 | Sẵn sàng phân công |
| EXE-009 | execution | Add the operator run-now endpoint | F-060 | M1 | P1 | S | After submission | EXE-003 | Sẵn sàng phân công |
| EXE-010 | execution | Track gas fees and alert on low executor gas | F-066 | M1 | P1 | S | After submission | EXE-007 | Sẵn sàng phân công |
| EXE-011 | execution | Execute the swap-for-gas step on the test router | F-064 | M1 | P2 | S | After submission | EXE-008, SC-018 | Sẵn sàng phân công |
| EXE-L01 | execution | Add a KMS-backed signer | F-061 | Later | - | M | Later | EXE-005 | Đã chấp nhận (Later) |
| EXE-L02 | execution | Integrate the production swap adapter | F-065 | Later | - | M | Later | EXE-011, SC-L03 | Đã chấp nhận (Later) |
| EXE-L03 | execution | Add cross-chain bridging | F-067 | Later | - | L | Later | TRS-L01 | Đã chấp nhận (Later) |
| EXE-L04 | execution | Partition workers by treasury for scale | F-061 | Later | - | M | Later | EXE-002 | Đã chấp nhận (Later) |
| REC-001 | reconciliation | Verify post-conditions after each confirmed step | F-071 | M1 | P0 | M | A | EXE-008 | Sẵn sàng phân công |
| REC-002 | reconciliation | Build reconciliation records with classification | F-072 | M1 | P0 | M | A | REC-001 | Sẵn sàng phân công |
| REC-003 | reconciliation | Implement match, discrepancy and auto-match | F-072 | M1 | P0 | S | B | REC-002 | Sẵn sàng phân công |
| REC-004 | reconciliation | Export reconciliation CSV and journal lines | F-073 | M1 | P1 | M | B | REC-003 | Sẵn sàng phân công |
| REC-005 | reconciliation | Publish on-chain payment attestations | F-074 | M1 | P1 | S | A | REC-002, SC-019 | Sẵn sàng phân công |
| REC-L01 | reconciliation | Build the ERP integration framework with Xero | F-075 | Later | - | L | Later | REC-004 | Đã chấp nhận (Later) |
| REC-L02 | reconciliation | Add the QuickBooks connector | F-075 | Later | - | M | Later | REC-L01 | Đã chấp nhận (Later) |
| REC-L03 | reconciliation | Add the NetSuite connector | F-075 | Later | - | M | Later | REC-L01 | Đã chấp nhận (Later) |
| RCV-001 | recovery | Scan in-flight operations at startup | F-080 | M1 | P0 | S | A | EXE-007 | Sẵn sàng phân công |
| RCV-002 | recovery | Resolve unknown operations from chain evidence | F-080 | M1 | P0 | M | A | RCV-001, CHR-003 | Sẵn sàng phân công |
| RCV-003 | recovery | Handle partial completion and resume | F-081 | M1 | P0 | S | After submission | EXE-008 | Sẵn sàng phân công |
| RCV-004 | recovery | Implement the review queue and routing | F-082 | M1 | P0 | M | B | INV-002 | Sẵn sàng phân công |
| RCV-005 | recovery | Implement retry policy and error classification | F-083 | M1 | P0 | S | B | EXE-007 | Sẵn sàng phân công |
| RCV-006 | recovery | Implement circuit-breaker rules and auto-pause | F-027 | M1 | P2 | M | After submission | REC-001, MDT-007, EXE-013, CHR-006 | Sẵn sàng phân công |
| RCV-007 | recovery | Automate the crash-recovery test | F-080 | M1 | P0 | S | A | RCV-002 | Sẵn sàng phân công |
| AGT-001 | agent | Build the LLM adapter with routing and timeouts | F-094 | M1 | P0 | M | A | EXE-002 | Sẵn sàng phân công |
| AGT-002 | agent | Log every AI call and fail closed | F-093 | M1 | P0 | S | A | AGT-001 | Sẵn sàng phân công |
| AGT-003 | agent | Implement untrusted-content wrapping and sanitization | F-091 | M1 | P0 | S | A | AGT-001 | Sẵn sàng phân công |
| AGT-004 | agent | Implement invoice extraction | F-031 | M1 | P0 | M | A | AGT-003, AGT-002, INV-004 | Sẵn sàng phân công |
| AGT-005 | agent | Extract and validate payment terms | F-035 | M1 | P0 | S | A | AGT-004, ENG-005 | Sẵn sàng phân công |
| AGT-006 | agent | Detect instruction-like text in documents | F-036, F-091 | M1 | P0 | S | A | AGT-004 | Sẵn sàng phân công |
| AGT-007 | agent | Implement the read-only tool layer | F-053, F-090 | M1 | P0 | M | A | CHR-002, ENG-008, POL-003 | Sẵn sàng phân công |
| AGT-008 | agent | Implement the plan proposer | F-053 | M1 | P0 | M | A | AGT-007 | Sẵn sàng phân công |
| AGT-009 | agent | Score AI proposals and select the plan | F-053 | M1 | P0 | S | A | AGT-008, ENG-008 | Sẵn sàng phân công |
| AGT-010 | agent | Implement rule-based fallback templates | F-054 | M1 | P0 | S | A | ENG-007, POL-003 | Sẵn sàng phân công |
| AGT-011 | agent | Draft exception requests with a numeric post-check | F-057 | M1 | P1 | S | B | AGT-001, MDT-006 | Sẵn sàng phân công |
| AGT-012 | agent | Build the Copilot backend | F-090 | M1 | P1 | L | After submission | AGT-007 | Sẵn sàng phân công |
| AGT-013 | agent | Build the extraction accuracy eval | F-092 | M1 | P0 | S | B | AGT-005, DOM-004 | Sẵn sàng phân công |
| AGT-014 | agent | Build the planner benchmark (B1 vs B2) | F-092 | M1 | P0 | M | A | AGT-009, ENG-006, DOM-005 | Sẵn sàng phân công |
| AGT-015 | agent | Build the red-team suite runner | F-091, F-163 | M1 | P0 | S | A | AGT-006, DOM-006 | Sẵn sàng phân công |
| AGT-016 | agent | Build the Copilot numeric-fidelity suite | F-092 | M1 | P1 | S | After submission | AGT-012, DOM-007 | Sẵn sàng phân công |
| AGT-017 | agent | Add a secondary LLM provider fallback | F-094 | M1 | P1 | M | After submission | AGT-001 | Sẵn sàng phân công |
| NTF-001 | notifications | Create the domain event bus and notification routing | F-100 | M1 | P1 | M | A | INV-002 | Sẵn sàng phân công |
| NTF-002 | notifications | Expose in-app notifications and the SSE stream | F-100, F-132 | M1 | P1 | M | A | NTF-001 | Sẵn sàng phân công |
| NTF-003 | notifications | Add Telegram linking and delivery | F-101 | M1 | P2 | M | After submission | NTF-001 | Sẵn sàng phân công |
| NTF-L01 | notifications | Add email notifications and digests | F-102 | Later | - | M | Later | NTF-001 | Đã chấp nhận (Later) |
| NTF-L02 | notifications | Add outbound webhooks | F-103 | Later | - | M | Later | NTF-001 | Đã chấp nhận (Later) |
| NTF-L03 | notifications | Add Slack, Lark and WeCom channels | F-104 | Later | - | L | Later | NTF-001 | Đã chấp nhận (Later) |
| NTF-L04 | notifications | Add notification preferences | F-105 | Later | - | S | Later | NTF-002 | Đã chấp nhận (Later) |
| CMP-001 | compliance | Build the screening adapter and fixture provider | F-110 | M1 | P1 | S | A | MDT-001 | Sẵn sàng phân công |
| CMP-002 | compliance | Screen payees before each PAY | F-110 | M1 | P1 | S | After submission | CMP-001, POL-003 | Sẵn sàng phân công |
| CMP-003 | compliance | Implement data classification, encryption helpers and log redaction | F-113 | M1 | P0 | M | B | DEV-001 | Sẵn sàng phân công |
| CMP-L01 | compliance | Integrate a KYB provider | F-111 | Later | - | L | Later | CMP-001 | Đã chấp nhận (Later) |
| CMP-L02 | compliance | Add Travel Rule support | F-112 | Later | - | L | Later | CMP-L01 | Đã chấp nhận (Later) |
| CMP-L03 | compliance | Add retention and deletion workflows | F-114 | Later | - | M | Later | CMP-003 | Đã chấp nhận (Later) |
| CMP-L04 | compliance | Add region pinning for stored data | F-114 | Later | - | M | Later | CMP-L03 | Đã chấp nhận (Later) |
| AUD-001 | audit | Implement the hash-chained audit log | F-120 | M1 | P0 | M | A | IDN-001 | Sẵn sàng phân công |
| AUD-002 | audit | Add audit read and chain verification | F-120 | M1 | P0 | S | After submission | AUD-001 | Sẵn sàng phân công |
| AUD-003 | audit | Define the evidence bundle schema and exporter | F-121 | M1 | P0 | M | A | AUD-001, EXE-008 | Sẵn sàng phân công |
| AUD-004 | audit | Propagate coverage labels through the API | F-122 | M1 | P1 | S | After submission | CHR-002 | Sẵn sàng phân công |
| AUD-L01 | audit | Anchor the audit hash root on-chain daily | F-120 | Later | - | S | Later | AUD-002 | Đã chấp nhận (Later) |
| OBS-001 | observability | Configure structured logging with correlation ids | F-142 | M1 | P1 | S | After submission | CMP-003 | Sẵn sàng phân công |
| OBS-002 | observability | Add OpenTelemetry tracing | F-142 | M1 | P1 | M | After submission | OBS-001 | Sẵn sàng phân công |
| OBS-003 | observability | Add Sentry and Prometheus metrics | F-142 | M1 | P1 | S | After submission | OBS-001 | Sẵn sàng phân công |
| OBS-004 | observability | Compute operational metrics | F-140 | M1 | P1 | M | After submission | AUD-001, EXE-008 | Sẵn sàng phân công |
| OBS-005 | observability | Compute the savings report | F-141 | M1 | P1 | M | After submission | OBS-004, ENG-006 | Sẵn sàng phân công |
| ADM-L01 | admin | Build the platform admin console | F-150 | Later | - | L | Later | IDN-006 | Đã chấp nhận (Later) |
| ADM-L02 | admin | Meter usage for billing | F-152 | Later | - | M | Later | OBS-004 | Đã chấp nhận (Later) |
| ADM-L03 | admin | Add subscriptions and customer invoicing | F-152 | Later | - | L | Later | ADM-L02 | Đã chấp nhận (Later) |
| WEB-001 | web | Create the web app shell | F-130 | M1 | P0 | M | A | DEV-001 | Sẵn sàng phân công |
| WEB-002 | web | Build login, org selection and onboarding checklist | F-001, F-003 | M1 | P0 | M | A | WEB-001, IDN-005 | Sẵn sàng phân công |
| WEB-003 | web | Add wallet connection and SIWE linking | F-002 | M1 | P0 | S | A | WEB-002, IDN-004 | Sẵn sàng phân công |
| WEB-004 | web | Build the treasury setup wizard | F-010–F-012 | M1 | P0 | M | A | WEB-003, TRS-007, WEB-025 | Sẵn sàng phân công |
| WEB-005 | web | Build the mandate editor with summary, diff and activation | F-134, F-020, F-021 | M1 | P0 | L | B | WEB-004, MDT-003, WEB-025 | Sẵn sàng phân công |
| WEB-006 | web | Build the payee registry UI | F-134, F-022 | M1 | P0 | M | B | WEB-004, MDT-005, WEB-025 | Sẵn sàng phân công |
| WEB-007 | web | Build the request list and manual entry form | F-030 | M1 | P0 | M | A | WEB-002, INV-003 | Sẵn sàng phân công |
| WEB-008 | web | Build upload and extraction review | F-031, F-035 | M1 | P0 | L | A | WEB-007, AGT-005 | Sẵn sàng phân công |
| WEB-009 | web | Build the approval inbox and EIP-712 signing | F-131, F-038 | M1 | P0 | L | A | WEB-008, INV-010 | Sẵn sàng phân công |
| WEB-010 | web | Build the treasury dashboard | F-130 | M1 | P0 | M | A | WEB-004, CHR-002 | Sẵn sàng phân công |
| WEB-011 | web | Build plan cards and the Why panel | F-132 | M1 | P0 | M | A | WEB-010, EXE-004 | Sẵn sàng phân công |
| WEB-012 | web | Build the live execution timeline | F-132 | M1 | P0 | M | A | WEB-011, NTF-002 | Sẵn sàng phân công |
| WEB-013 | web | Build the exception and review console | F-135 | M1 | P0 | L | B | WEB-011, RCV-004, MDT-006, WEB-025 | Sẵn sàng phân công |
| WEB-014 | web | Build the reconciliation view and export | F-133 | M1 | P0 | M | B | WEB-010, REC-004 | Sẵn sàng phân công |
| WEB-015 | web | Build the notifications center | F-100 | M1 | P1 | S | After submission | WEB-001, NTF-002 | Sẵn sàng phân công |
| WEB-016 | web | Build the Copilot chat UI | F-090 | M1 | P1 | M | After submission | WEB-010, AGT-012 | Sẵn sàng phân công |
| WEB-017 | web | Build members and roles administration | F-004 | M1 | P1 | M | After submission | WEB-002, IDN-007 | Sẵn sàng phân công |
| WEB-018 | web | Build metrics and savings pages | F-140, F-141 | M1 | P1 | M | After submission | WEB-010, OBS-005 | Sẵn sàng phân công |
| WEB-019 | web | Add pause and resume controls and status banners | F-026 | M1 | P0 | S | B | WEB-010, MDT-007 | Sẵn sàng phân công |
| WEB-020 | web | Build the CSV import UI | F-032 | M1 | P1 | S | After submission | WEB-007, INV-005 | Sẵn sàng phân công |
| WEB-021 | web | Build the runway forecast chart | F-058 | M1 | P2 | S | After submission | WEB-010, ENG-011 | Sẵn sàng phân công |
| WEB-022 | web | Run the accessibility and responsive pass | F-130–F-135 | M1 | P1 | S | After submission | WEB-014 | Sẵn sàng phân công |
| WEB-023 | web | Write the Playwright end-to-end happy path | F-161 | M1 | P1 | M | After submission | WEB-012 | Sẵn sàng phân công |
| DOM-001 | domain-evidence | Verify Ethereum Sepolia infrastructure (owner: Phúc) | F-010, F-151 | M1 | P0 | S | A | — | Sẵn sàng phân công |
| DOM-002 | domain-evidence | Set up tUSDC and the Circle USDC evidence run (owner: Phúc) | F-013 | M1 | P0 | S | A | DOM-001 | Sẵn sàng phân công |
| DOM-003 | domain-evidence | Ask the organizers whether testnet evidence is accepted | — | M1 | P1 | S | A | — | Sẵn sàng phân công |
| DOM-004 | domain-evidence | Author the labelled invoice dataset (30) | F-092 | M1 | P0 | M | B | — | Sẵn sàng phân công |
| DOM-005 | domain-evidence | Author planner scenarios with ground truth (≥30) | F-092 | M1 | P0 | L | A | — | Sẵn sàng phân công |
| DOM-006 | domain-evidence | Author the red-team invoice set (20) | F-091, F-163 | M1 | P0 | M | A | — | Sẵn sàng phân công |
| DOM-007 | domain-evidence | Author Copilot question cases (20) | F-092 | M1 | P1 | S | After submission | DOM-005 | Sẵn sàng phân công |
| DOM-008 | domain-evidence | Review business rules and demo limits from a finance view | — | M1 | P0 | S | A | — | Sẵn sàng phân công |
| DOM-009 | domain-evidence | Review the threat model and write the known-risk list | — | M1 | P0 | M | A | — | Sẵn sàng phân công |
| DOM-010 | domain-evidence | Run customer interviews (2–3) | — | M1 | P1 | M | B | — | Sẵn sàng phân công |
| DOM-011 | domain-evidence | Write the security self-assessment report | — | M1 | P0 | M | A | DOM-009, SC-015 | Sẵn sàng phân công |
| DOM-012 | domain-evidence | Assemble the technical documentation for submission | — | M1 | P0 | M | A | DOM-011 | Sẵn sàng phân công |
| DOM-013 | domain-evidence | Create the 10-minute presentation deck | — | M1 | P0 | M | A | DOM-008 | Sẵn sàng phân công |
| DOM-014 | domain-evidence | Script and record the 5-minute demo video | — | M1 | P0 | M | A | DEV-008 | Sẵn sàng phân công |
| DOM-015 | domain-evidence | Write the compliance positioning note and license inventory | — | M1 | P1 | S | B | — | Sẵn sàng phân công |
| DOM-016 | domain-evidence | Update the FigJam board from the repo diagrams | — | M1 | P2 | S | After submission | — | Sẵn sàng phân công |
| DOM-017 | domain-evidence | Choose the repository license | — | M1 | P1 | S | After submission | — | Sẵn sàng phân công |
| SC-021 | contracts | Implement the module factory with EIP-1167 clones | F-012, F-021 | M1 | P0 | M | A | SC-002 | Sẵn sàng phân công |
| ENG-012 | financial-engine | Implement the exhaustive oracle scheduler for tests | F-052, F-092 | M1 | P0 | S | A | ENG-006 | Sẵn sàng phân công |
| POL-007 | policy-engine | Simulate each step with eth_call before signing | F-055, F-061 | M1 | P0 | S | A | POL-003, POL-001, CHR-002, SC-016 | Sẵn sàng phân công |
| INV-012 | invoices | Detect near-duplicate requests | F-036, F-037 | M1 | P0 | S | A | INV-006 | Sẵn sàng phân công |
| SC-022 | contracts | Add on-chain request cancellation | F-039 | M1 | P0 | S | A | SC-006, SC-009 | Sẵn sàng phân công |
| MDT-009 | mandate | Build governance transactions and collect owner signatures in the app | F-020, F-021, F-022, F-025, F-026 | M1 | P0 | L | A | MDT-001, TRS-005 | Sẵn sàng phân công |
| MDT-010 | mandate | Set up the Guardian Safe with the sentinel | F-026, F-027 | M1 | P0 | S | A | MDT-009, EXE-013, TRS-006 | Sẵn sàng phân công |
| EXE-013 | execution | Add the pause-only sentinel to the signer | F-026, F-027 | M1 | P0 | S | A | EXE-005, EXE-006 | Sẵn sàng phân công |
| EXE-012 | execution | Implement the fee policy, fee holds and fee acceptance | F-066 | M1 | P0 | M | A | MDT-001, CHR-001, ENG-001 | Sẵn sàng phân công |
| WEB-024 | web | Build the fee policy and fee acceptance UI | F-066 | M1 | P1 | S | B | WEB-010, EXE-012 | Sẵn sàng phân công |
| WEB-025 | web | Build the governance signing inbox | F-020–F-026 | M1 | P0 | M | A | WEB-003, MDT-009 | Sẵn sàng phân công |
| CHR-006 | chain-reader | Index treasury token movements and alert on unexpected outflows | F-050 | M1 | P0 | S | A | CHR-005, EXE-001 | Sẵn sàng phân công |
| SC-023 | contracts | Add two-option payment approvals (early / standard) | F-038 | M1 | P0 | S | A | SC-006, SC-005 | Sẵn sàng phân công |
| SC-024 | contracts | Implement Aave V3 supply and withdraw through Safe T | F-068 | M1 | P0 | M | A | SC-021, SC-007, SC-008 | Sẵn sàng phân công |
| SC-025 | contracts | Add Aave integration tests on a pinned Sepolia fork | F-068, F-163 | M1 | P0 | S | A | SC-024, SC-016 | Sẵn sàng phân công |
| SC-026 | contracts | Implement owner-authorized borrow and repay | F-079 | M1 | P2 | M | After submission | SC-024 | Sẵn sàng phân công |
| ENG-013 | financial-engine | Implement reserve formulas and the liquidity decision | F-068 | M1 | P0 | S | A | ENG-002, ENG-005 | Sẵn sàng phân công |
| ENG-014 | financial-engine | Build the borrow proposal | F-069 | M1 | P1 | S | B | ENG-013 | Sẵn sàng phân công |
| EXE-014 | execution | Run the liquidity cycle (supply / withdraw) | F-068 | M1 | P0 | S | A | EXE-008, ENG-013, SC-024 | Sẵn sàng phân công |
| WEB-026 | web | Build the treasury position card | F-068, F-130 | M1 | P0 | S | A | WEB-010 | Sẵn sàng phân công |
| WEB-027 | web | Build the borrow proposal view | F-069 | M1 | P1 | S | B | WEB-026, ENG-014 | Sẵn sàng phân công |
| DEV-012 | devex | Add the deployment config gate to CI | F-151 | M1 | P0 | S | A | SC-016, DEV-003 | Sẵn sàng phân công |
| MDT-011 | mandate | Add owner borrow/repay authorizations (governance) | F-079 | M1 | P2 | S | After submission | MDT-009, SC-026 | Sẵn sàng phân công |

## 4. Các đợt thực hiện (M1)

Ticket trong cùng một đợt không chặn nhau nên **làm song song được**.

| Đợt | Số ticket |
|---|---:|
| 1 | 12 |
| 2 | 11 |
| 3 | 10 |
| 4 | 10 |
| 5 | 15 |
| 6 | 10 |
| 7 | 13 |
| 8 | 16 |
| 9 | 17 |
| 10 | 14 |
| 11 | 14 |
| 12 | 11 |
| 13 | 13 |
| 14 | 13 |
| 15 | 11 |
| 16 | 8 |
| 17 | 3 |
| 18 | 3 |
| 19 | 2 |

## 5. Chuỗi phụ thuộc dài nhất

Bất kỳ ticket nào trên chuỗi này trễ thì cuối M1 trễ theo:

DEV-001 → DEV-002 → IDN-001 → TRS-001 → TRS-002 → CHR-001 → TRS-003 → TRS-004 → CHR-002 → POL-007 → EXE-005 → EXE-007 → EXE-008 → REC-001 → REC-002 → REC-003 → REC-004 → WEB-014 → WEB-022
