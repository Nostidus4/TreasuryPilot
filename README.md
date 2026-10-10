# TreasuryPilot

> An AI treasury operator that gets **approved** invoices paid on time. It moves liquidity between a company's own wallets and settles on-chain. A smart-contract mandate guarantees it can never pay the wrong party, exceed the budget, or touch the safety buffer.

**Humans decide whether to pay. The agent decides how and when. The contract makes sure it can't do anything else.**

Built for **FinTechathon 2026 – International Track, Topic F (Agent Wallet)**. Designed as a real multi-tenant product; Milestone 1 (M1) is the competition build.

> ⚠️ **Status: planning complete, implementation not started.** M1 runs on test networks with test assets only. The contracts are unaudited. Do not use with real funds.

## What it does

1. **Intake:** upload an invoice (PDF, CSV or manual). AI extracts the fields and payment terms and flags fraud signals.
2. **Approve:** a human approver signs an EIP-712 approval over the exact payment fields.
3. **Plan:** a deterministic engine and an AI planner schedule payments to capture discounts and avoid late fees, within liquidity and limits.
4. **Execute:** the agent refills the paying wallet from the treasury wallet and pays the vendor through a Safe module that enforces the mandate on-chain.
5. **Verify and reconcile:** receipts, post-conditions, reconciliation export and an evidence bundle.

## Documentation map

| Read this | For |
|---|---|
| [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) ([Tiếng Việt](docs/vi/01-tong-quan.md)) | Product, problem, users, journeys |
| [`docs/FEATURES.md`](docs/FEATURES.md) | 99 features with full specs |
| [`docs/FUNCTIONAL_REQUIREMENTS.md`](docs/FUNCTIONAL_REQUIREMENTS.md) · [`NON_FUNCTIONAL_REQUIREMENTS.md`](docs/NON_FUNCTIONAL_REQUIREMENTS.md) · [`BUSINESS_RULES.md`](docs/BUSINESS_RULES.md) | Requirements and rules |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) → [`docs/SYSTEM_ARCHITECTURE.md`](docs/SYSTEM_ARCHITECTURE.md) | Architecture |
| [`docs/TECH_STACK.md`](docs/TECH_STACK.md) · [`docs/adr/`](docs/adr/README.md) | Stack and decisions |
| [`docs/AI_AGENT_ARCHITECTURE.md`](docs/AI_AGENT_ARCHITECTURE.md) | What the AI may and may not do |
| [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) · [`docs/API_SPEC.md`](docs/API_SPEC.md) | Data and API |
| [`docs/modules/`](docs/modules/README.md) | 20 module specs |
| [`planning/BACKLOG.md`](planning/BACKLOG.md) · [`planning/issues/`](planning/issues/) | Epics and ticket drafts |
| [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) · [`docs/decisions-log.md`](docs/decisions-log.md) | Open points and decisions |

## Repository layout

See [`docs/REPOSITORY_STRUCTURE.md`](docs/REPOSITORY_STRUCTURE.md). The code folders (`apps/`, `services/`, `packages/`, `contracts/`) are created by the first tickets of each module.

## Getting started

See [`DEVELOPMENT.md`](DEVELOPMENT.md). Contribution rules are in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Security

Trust boundaries and the known-risk list are in `docs/SYSTEM_ARCHITECTURE.md` §3 and `docs/security/` (created during M1). Please report vulnerabilities privately to the maintainers. Do not open public issues for them.

## License

To be decided before the repository is made public (see OPEN_QUESTIONS).
