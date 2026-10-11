# Modules

| ID | Module | Path | Kind | Spec level |
|---|---|---|---|---|
| M01 | Identity & Access | `identity/` | api | Detailed — defaults marked *(mặc định)*, to review |
| M02 | Treasury & Chain Config | `treasury/` | api/worker | Detailed — defaults marked *(mặc định)*, to review |
| M03 | Mandate, Payees, Exceptions & Pause | `mandate/` | api/worker | Detailed — grilled with the team |
| M04 | Smart Contracts | `contracts/` | on-chain | Detailed — grilled with the team |
| M05 | Invoices & Payment Requests | `invoices/` | api | Detailed — grilled with the team |
| M06 | Chain Reader & Tx Tracking | `chain-reader/` | worker | Detailed — grilled with the team |
| M07 | Financial Engine | `financial-engine/` | py-core | Detailed — grilled with the team |
| M08 | Policy Engine & Attestation | `policy-engine/` | py-core/worker | Detailed — grilled with the team |
| M09 | AI Agent | `agent/` | worker/api | Detailed — reviewed with the project lead |
| M10 | Orchestration & Execution | `execution/` | worker/signer | Detailed — reviewed with the project lead |
| M11 | Verification & Reconciliation | `reconciliation/` | worker/api | Detailed — reviewed with the project lead |
| M12 | Recovery & Exceptions | `recovery/` | worker | Detailed — reviewed with the project lead |
| M13 | Notifications | `notifications/` | worker/api | Detailed — defaults marked *(mặc định)*, to review |
| M14 | Compliance | `compliance/` | worker/api | Detailed — defaults marked *(mặc định)*, to review |
| M15 | Audit & Evidence | `audit/` | all | Detailed — defaults marked *(mặc định)*, to review |
| M16 | Web | `web/` | browser | Detailed — defaults marked *(mặc định)*, to review |
| M17 | Observability & Analytics | `observability/` | all | Detailed — defaults marked *(mặc định)*, to review |
| M18 | Platform Admin & Billing | `admin/` | api | Detailed — defaults marked *(mặc định)*, to review |
| M19 | DevEx & Quality | `devex/` | repo/CI | Detailed — defaults marked *(mặc định)*, to review |
| M20 | Domain & Evidence (non-code) | `domain-evidence/` | people | Detailed — grilled with the team |

Every one of the 99 features in `FEATURES.md` maps to at least one module (see each module's "Features" section).

Each module README follows the same 14 sections: purpose and boundaries, features/FR/BR, concepts, data model, state machines, interfaces, flows, algorithms with worked examples, configuration, security, failure scenarios, test plan, tickets in order, decisions.
