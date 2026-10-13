# TreasuryPilot: Repository Structure

**Status:** Draft for gate G2 · **Decision:** Q34, ADR-001

## Monorepo or multi-repo?

**Monorepo.** Reasons:
1. Two developers. One clone, one CI, one PR can touch contract + API + UI.
2. EIP-712 structs must match byte-for-byte across Solidity, Python and TypeScript (ADR-003). Shared golden vectors live in one place.
3. Evidence for judges (docs, evals, test reports) sits next to the code.
4. The submission requires one GitHub link with a README and deployment instructions.

## Layout

```text
TreasuryPilot/
├── apps/
│   └── web/                         # React + Vite + TS (M16)
│       ├── src/{routes,components,features,lib/api(generated),lib/wallet}
│       └── package.json
├── services/
│   ├── api/                         # FastAPI (M01–M05, M11, M13–M15 endpoints)
│   │   ├── src/treasurypilot_api/{identity,treasury,mandate,invoices,reconciliation,notifications,audit,copilot,common}
│   │   ├── migrations/              # Alembic
│   │   └── tests/
│   ├── worker/                      # Celery; one codebase, two containers: `core` queue (M06, M08 attest, M10–M13) and `ai` queue (M09)
│   │   ├── src/treasurypilot_worker/{trigger,planner,agent,executor,tracker,recovery,reconcile,notify}
│   │   ├── agent/config.yaml        # model routing, budgets, prompt versions
│   │   └── tests/
│   └── signer/                      # internal signing service (M10, ADR-006)
│       ├── src/treasurypilot_signer/
│       └── tests/
├── packages/
│   └── py-core/                     # pure domain: money, models, financial engine (M07), policy (M08), eip712
│       ├── src/treasurypilot_core/{money,domain,engine,policy,eip712,fingerprint,privacy,observability}
│       └── tests/                   # unit + hypothesis property tests + Domain §3.4 goldens
├── contracts/                       # Foundry (M04)
│   ├── src/{TreasuryPilotModule.sol,interfaces/,test-assets/TestUSDC.sol,test-assets/TestRouter.sol}
│   ├── test/{unit,fuzz,invariant,vectors}
│   ├── script/                      # deploy + seed
│   └── foundry.toml
├── evals/                           # M09/M20: datasets & ground truth (versioned)
│   ├── invoices/                    # 30 labelled invoices (PDF + json labels)
│   ├── scenarios/                   # ≥30 planner scenarios (dev/heldout)
│   ├── redteam/                     # 20 injection invoices
│   └── copilot/                     # 20 Q&A fidelity cases
├── scenarios/                       # M19: named demo/reliability scenarios
├── deployments/                     # <chainId>.json manifests (addresses, code hashes)
├── infra/
│   ├── compose.yaml                 # profiles: local, testnet, ci
│   ├── caddy/Caddyfile
│   └── env/.env.example             # names only, no values
├── docs/                            # product, BA, architecture, ADRs, modules, vi/ mirror, evidence/, security/
├── planning/
│   ├── issues/<module>/NNN-*.md     # ticket drafts (Phase 11)
│   ├── BACKLOG.md                   # master backlog (Phase 16)
│   ├── DEPENDENCIES.md              # dependency graph (Phase 15)
│   └── tracker/                     # Excel tracker + generator script (Q19)
├── .github/
│   ├── ISSUE_TEMPLATE/{feature.yml,bug.yml,task.yml,non-code.yml}
│   ├── pull_request_template.md
│   └── workflows/{ci.yml,contracts.yml,web.yml,evals.yml}
├── pyproject.toml                   # uv workspace (services/*, packages/*)
├── uv.lock
├── pnpm-workspace.yaml
├── Makefile                         # dev, test, bench, reliability, scenario
├── README.md · CONTRIBUTING.md · DEVELOPMENT.md · ARCHITECTURE.md · LICENSE
└── .pre-commit-config.yaml
```

## Rules

| Rule | Enforcement |
|---|---|
| `py-core` imports no I/O (no DB, HTTP, web3) | import-linter contract in CI |
| Services never import each other; they share only `py-core` | import-linter |
| One module per folder under `api/src` and `worker/src`, mirroring `docs/modules` | review |
| Generated code (`apps/web/src/lib/api`) is never edited by hand | CI regenerates and diffs |
| Every PR that changes behaviour updates the matching doc or ADR | PR template checkbox |
| No secrets committed | gitleaks pre-commit + CI |

## Branch strategy & conventions (detailed in CONTRIBUTING.md, Phase 9)

- **Trunk-based:** `main` is protected (CI green + 1 review). Short-lived branches `feat/<module>-<issue#>-slug`, `fix/…`, `docs/…`, `chore/…`.
- **Conventional Commits:** `feat(mandate): add cooling period check (#42)`.
- **Releases:** tags `m1-rc1`, `m1-submission`.
