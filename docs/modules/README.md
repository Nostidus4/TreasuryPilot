# Modules

| ID | Module | Path | Kind |
|---|---|---|---|
| M01 | Identity & Access | `identity/` | api |
| M02 | Treasury & Chain Config | `treasury/` | api/worker |
| M03 | Mandate, Payees, Exceptions & Pause | `mandate/` | api/worker |
| M04 | Smart Contracts | `contracts/` | on-chain |
| M05 | Invoices & Payment Requests | `invoices/` | api |
| M06 | Chain Reader & Tx Tracking | `chain-reader/` | worker |
| M07 | Financial Engine | `financial-engine/` | py-core |
| M08 | Policy Engine & Attestation | `policy-engine/` | py-core/worker |
| M09 | AI Agent | `agent/` | worker/api |
| M10 | Orchestration & Execution | `execution/` | worker/signer |
| M11 | Verification & Reconciliation | `reconciliation/` | worker/api |
| M12 | Recovery & Exceptions | `recovery/` | worker |
| M13 | Notifications | `notifications/` | worker/api |
| M14 | Compliance | `compliance/` | worker/api |
| M15 | Audit & Evidence | `audit/` | all |
| M16 | Web | `web/` | browser |
| M17 | Observability & Analytics | `observability/` | all |
| M18 | Platform Admin & Billing | `admin/` | api |
| M19 | DevEx & Quality | `devex/` | repo/CI |
| M20 | Domain & Evidence (non-code) | `domain-evidence/` | people |

Every one of the 99 features in `FEATURES.md` maps to at least one module (see each module's "Features" section).
