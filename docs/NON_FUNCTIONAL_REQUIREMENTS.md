# TreasuryPilot: Non-Functional Requirements

**Status:** Draft for gate G1 · **Date:** 2026-10-10

Targets apply to **M1** (competition build, testnet) unless a separate **Prod** target is given for the full product. Each NFR includes how it is verified.

## Security

| ID | Requirement | M1 target | Prod target | Verification |
|---|---|---|---|---|
| NFR-SEC-01 | Every financial rule in `BUSINESS_RULES.md` marked "C" is enforced on-chain and cannot be bypassed by calling the backend or the contract directly. | 100% of C-rules have direct-call tests | Plus an external audit | Foundry bypass tests |
| NFR-SEC-02 | Contract invariants hold under fuzzing. | ≥ 8 invariants, 10k runs | 100k runs plus formal checks for the core | `forge test` |
| NFR-SEC-03 | Key isolation: owner keys never touch the system. The executor key is held only by the signer service. LLM and API processes have no key material. | Separate process and env | KMS/HSM-backed signer | Architecture review, secret scan |
| NFR-SEC-04 | No secrets in the repository or logs. | gitleaks in CI | Same | CI |
| NFR-SEC-05 | OWASP ASVS L1 for the web and API (authentication, session, input validation, access control). | Key controls | ASVS L2 | Checklist + tests |
| NFR-SEC-06 | Prompt-injection resilience. | 0/20 red-team cases change any field or policy | 0/100 | Red-team suite |
| NFR-SEC-07 | Static analysis of contracts. | No unresolved high findings | Same + audit | Report in `docs/security/` |
| NFR-SEC-08 | Dependencies are pinned (lockfiles, exact Safe and Solidity versions) and scanned. | Pinned + `npm audit` | + SCA tool | CI |
| NFR-SEC-09 | Rate limiting and bounded jobs (tool calls per plan, actions per plan, scans, retries). | Configured limits | Same | Tests |

## Performance

| ID | Requirement | M1 target | Prod target |
|---|---|---|---|
| NFR-PERF-01 | API p95 latency for read endpoints | < 300 ms | < 200 ms |
| NFR-PERF-02 | Planning cycle (excluding chain confirmations) for ≤ 12 requests | < 15 s, including LLM | < 10 s |
| NFR-PERF-03 | Invoice extraction per document | < 20 s | < 10 s |
| NFR-PERF-04 | UI timeline update after a backend state change | < 2 s | < 1 s |
| NFR-PERF-05 | CSV import of 500 rows | < 10 s | < 10 s for 5,000 rows |

Latency reports separate analysis, queue, chain confirmation and verification time (GA p.39).

## Availability & Reliability

| ID | Requirement | M1 target | Prod target |
|---|---|---|---|
| NFR-REL-01 | Main scenario completion rate on valid, supported requests | ≥ 95% across 30 local + 10 testnet runs | ≥ 99.5% |
| NFR-REL-02 | Double payments | 0 in all suites, including crash tests | 0 |
| NFR-REL-03 | Crash safety: the worker can restart at any point without losing or duplicating operations | Outbox + recovery | Same |
| NFR-REL-04 | RPC resilience: at least 2 RPC providers, with failover | 2 | 3 + health scoring |
| NFR-REL-05 | LLM outage behaviour: deterministic fallback or manual path; never blocked indefinitely | Timeout ≤ 20 s | Provider failover |
| NFR-REL-06 | Service availability | Best effort (demo) | 99.9% monthly (API), 99.5% (worker) |
| NFR-REL-07 | Backup and restore of the database | Daily snapshot | PITR, RPO ≤ 5 min, RTO ≤ 1 h |

## Scalability

| ID | Requirement | M1 | Prod |
|---|---|---|---|
| NFR-SCAL-01 | Tenants | 1–5 | 1,000+ orgs |
| NFR-SCAL-02 | Requests per treasury per day | 50 | 5,000 |
| NFR-SCAL-03 | Horizontal scaling of the API (stateless) and workers (partitioned by treasury, keeping per-treasury sequencing) | Design supports it | Implemented |

## Privacy

| ID | Requirement | Target |
|---|---|---|
| NFR-PRIV-01 | No personal data or invoice content on-chain; hashes only | 100% (event and calldata review) |
| NFR-PRIV-02 | Confidential data (invoice files, vendor contacts) is encrypted at rest; private object storage with signed URLs | M1: private bucket + DB encryption at rest |
| NFR-PRIV-03 | Minimum content sent to the LLM; provider no-retention settings where available | Documented per task |
| NFR-PRIV-04 | Logs redact addresses (optional), emails and document content | Redaction tests |
| NFR-PRIV-05 | Tenant isolation is tested on every endpoint | Automated cross-tenant test |

## Auditability & Logging

| ID | Requirement | Target |
|---|---|---|
| NFR-AUD-01 | Every money- or authority-affecting action is audited; if the audit write fails, the action fails closed | 100% |
| NFR-AUD-02 | The audit log is hash-chained and verifiable by a script | Script in repo |
| NFR-AUD-03 | Every plan traces to its planner source, model version, prompt version, validator decision and tx hashes | 100% |
| NFR-AUD-04 | Structured JSON logs with correlation ids (`requestId`, `planId`, `operationId`, `traceId`) | All services |
| NFR-AUD-05 | Retention of evidence | M1: indefinite; Prod: ≥ 7 years (configurable, legal) |

## Accessibility & Usability

| ID | Requirement | Target |
|---|---|---|
| NFR-UX-01 | WCAG 2.1 AA for core flows (approve, exceptions, dashboard) | Key flows pass an axe check |
| NFR-UX-02 | Responsive design down to 390 px for approval and notifications | Manual test |
| NFR-UX-03 | Amounts are always shown with asset symbol and network; test assets labelled | UI review |
| NFR-UX-04 | Precise status language, with no "safe" or "done" without verification (GA p.32) | Copy checklist |
| NFR-UX-05 | English UI (M1); i18n-ready (Vietnamese and Chinese later) | Strings externalized |

## Maintainability

| ID | Requirement | Target |
|---|---|---|
| NFR-MAINT-01 | Modular boundaries match `docs/modules/`; no cross-module database access | Lint rule / review |
| NFR-MAINT-02 | Type-safe shared domain types across web, API and worker | Shared package |
| NFR-MAINT-03 | Test coverage of core packages (financial engine, policy, contracts) | ≥ 85% lines (M1), ≥ 90% (Prod) |
| NFR-MAINT-04 | ADRs for every significant architecture decision | `docs/adr/` |
| NFR-MAINT-05 | Reproducible builds and environments (pinned versions, deployment manifest) | Lockfiles + manifest |
| NFR-MAINT-06 | Docs updated in the same PR as behaviour changes | PR template checkbox |

## Compliance & Legal

| ID | Requirement | Target |
|---|---|---|
| NFR-CMP-01 | M1 runs only on test networks with test assets, labelled as such | Enforced by the scenario runner allowlist |
| NFR-CMP-02 | Market positioning excludes mainland China retail or business use of stablecoins | Statement in docs/deck |
| NFR-CMP-03 | Third-party code, data and models are properly licensed (competition IP rule) | License inventory in repo |
| NFR-CMP-04 | Provider adapters for KYB, KYT and Travel Rule exist so that providers can be swapped | Interface defined in M1 |
