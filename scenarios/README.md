# Reproducible scenarios

One YAML file per named scenario (DEV-007). Run with:

```sh
uv run python infra/scripts/scenario.py list
uv run python infra/scripts/scenario.py run pause    # needs `make dev` and `make deploy-local`
```

Fields: `name` (= file name), `adr019` (D-id), `chain_id` (must be in the allowlist: 31337, 11155111;
the live RPC chain id must match, mainnet is refused), `requires` (capabilities), `steps`, `must_show`.

A scenario whose `requires` lists a capability the runner does not provide yet is reported as
`NOT_RUNNABLE` (exit 2) and writes no evidence bundle. Capabilities are derived from the registered
step functions (`STEPS` in `scenario.py`): `anvil` and `deployment` today. Pending: `planner` (#146),
`sequencer` (#65), `executor-pipeline`, `ai-extraction`, `outbox-recovery`, `chain-reader-alerts`,
`fee-policy-runtime`, `aave-adapter`, `borrow-authorization`. Unknown capability names, a mainnet
`chain_id`, and a runnable scenario with empty `steps` are rejected when the files load.

`must_show` is documentation only: the runner prints it but does not assert it. The `pause` step
asserts its own outcome (receipt status 1, module status Paused after the call); other scenarios
must assert their `must_show` lines in their steps when they become runnable.

Each run writes `docs/evidence/scenarios/<name>-<UTC time>/run.json` and `evidence-bundle.json`
(evidence-bundle.v1, validated before writing). Only `pause` is runnable today. The D2, D3 and
D6-D8 files are stubs (names provisional, Sepolia, all NOT_RUNNABLE) so `list` shows all ten.
