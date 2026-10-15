# Demo runbook (D1-D10)

Step-by-step script for the 5-minute judge demo (DEV-008, #68). Scenes follow ADR-019 D1-D10 and
each one names its scenario file in `scenarios/` (DEV-007 runner). Scene timing and narrative:
`docs/research/TreasuryPilot-Ke-hoach-nang-diem-80-90.md` section 7.

**Status today:** all twelve scenarios run on Anvil (the Aave scenarios use the TEST-only mock pool
that `make deploy-local` deploys). The runner drives the contracts and policy math and asserts each
scene's on-chain outcome; it does not run the planner, AI extraction, worker or UI, so the screens
and fallbacks below are still the way to show those parts. Each run reverts Anvil to a snapshot
afterwards (`--keep-state` to keep the result), so a scene can be replayed on the same deployment.
`make scenario` lists them.

## Numbering

ADR-019 V3-12 and the scenario YAML `adr019:` field disagree on three entries. Headings below use
the scenario name and YAML label; the ADR label is shown where it differs. Follow-up decision
needed: pick one numbering and update either the ADR or the YAML files.

| Scene | ADR-019 label | YAML `adr019` | Scenario name |
|---|---|---|---|
| Refill then pay | D1 | D1 | `demo-main` |
| Supply surplus | D2 | D2 | `aave-supply` |
| Withdraw for new invoice | D3 | D3 | `aave-withdraw` |
| Injected invoice, unknown payee | D4 (unknown payee) | D4 | `injected-invoice` |
| Over-cap and owner exception | D5 (cap breach) | D5 | `over-cap-exception` |
| Borrow proposal | D6 | D6 | `borrow-proposal` |
| Owner-signed borrow | D7 | D7 | `borrow-execution` |
| Borrow repayment | not listed (ADR D8 = AI outage) **mismatch** | D8 | `borrow-repay` |
| AI outage | D8 | none | no scenario file |
| Crash recovery | not listed (ADR D9 = unknown tx) **mismatch** | D9 | `crash-recovery` |
| Unknown tx (unexpected outflow) | D9 | M19-D5 **mismatch** | `unexpected-outflow` |
| Guardian pause | D10 | D10 | `pause` |

## Setup

Prerequisites: Docker, Foundry (`anvil`, `cast`, `forge`), `jq`, uv 0.11.3, pnpm. The repo pins uv
0.11.3: if your uv differs, prefix uv commands with `uvx uv@0.11.3 run ...` (for example
`uvx uv@0.11.3 run python infra/scripts/scenario.py list`).

1. `make bootstrap` installs Python and web dependencies.
2. `cp infra/env/.env.example infra/env/.env` and fill the required values (`make check-env` fails if the file is missing). The example ships working local defaults for `POSTGRES_*` and `MINIO_*`; for the demo you only need to set `ANTHROPIC_API_KEY` (AI extraction, D4). Everything else is optional or commented out in `infra/env/.env.example`.
3. `make dev` starts the full local stack (Postgres, Redis, MinIO, Anvil, API, workers, web). Wait until every service in `make ps` is `running`/`healthy` before continuing (repeat `make ps`; the API and web start last). `make logs` tails it. `make infra` starts only the backing services and Anvil.
4. `make seed` deploys the contracts to Anvil (via `make deploy-local`, skipped if the module is already deployed), seeds the TEST-labelled orgs, payees and invoices, and recreates the API with the new chain config.
5. `make smoke` checks the stack is healthy.
6. Web UI: both options use http://localhost:5173, so pick one. `make dev` already starts the `web` container there; use that. Use `make web-dev` (Vite hot reload) only if you stop the container first (`docker compose --env-file infra/env/.env -f infra/compose.yaml --profile local stop web`).
7. Log in with a login link printed by `make seed` (valid 12 h, regenerated on each seed run).

### Demo data (from `infra/scripts/seed_local.py`)

Ids are deterministic (uuid5), so the placeholders in the scene routes resolve to:

- `:org` = `21ca839b-a05a-56c2-a99d-cce17b1effb4` ("TreasuryPilot Demo (TEST)")
- `:t` = `d3a19bfb-3c07-5113-b9f4-f36d79b12675`
- `:r` (request): ids are `uuid5(NS, "request:INV-TEST-00N")`; open them from `/o/:org/requests`. Seeded invoices: 001 Draft, 002 AwaitingApproval, 003 Approved (800 tUSDC, used by the runner evidence), 004 Paid, 005 Rejected. Payees: Acme and Globex Active, Initech Cooling.

| User | Roles |
|---|---|
| `owner@seed.treasurypilot.test` | Owner, OrgAdmin |
| `approver@seed.treasurypilot.test` | Approver |
| `finance@seed.treasurypilot.test` | Finance, Operator |
| `auditor@seed.treasurypilot.test` | Auditor |

The seeded guardian is an Anvil EOA, account #3 (`0x90F79bf6EB2c4f870365E785982E1f101E93b906`), not a Safe. The Dashboard Pause button needs OWN or GRD (use the owner user).

## Reset between runs

- Contracts only (needed before replaying `pause`, because resume is a Safe-owner transaction): `make deploy-local`, then `make seed` to repoint the data at the new Safe addresses (each deploy creates new Safes).
- Full reset: `make down`, then repeat Setup from step 3. `make down` runs `docker compose down --remove-orphans`; it does not pass `-v`, so to wipe volumes run the same compose command with `-v` by hand.
- Evidence from earlier runs stays under `docs/evidence/scenarios/`; the runner never deletes it. That directory is **gitignored** (`.gitignore`), so nothing there is committed or reaches the PR/submission by itself.

## Running a scenario

```sh
make scenario                 # list names
make scenario NAME=pause      # run one
```

Exit codes: 0 passed, 1 failed or refused (for example a chain id outside 31337/11155111). A passed run writes
`docs/evidence/scenarios/<name>-<UTC time>/run.json` and `evidence-bundle.json`. Evidence is
written only by the runner; for manual fallbacks, take screenshots and tx hashes and store them in
the same folder layout by hand.

Submitted evidence: `docs/submission/` has no evidence folder yet (its README says public
deployment and transaction evidence must be recorded from actual artifacts). Until the M20 owners
fix a location, copy the chosen run folders and screenshots out of the gitignored directory into a
committed folder under `docs/submission/` (for example `docs/submission/demo-evidence/`), and link
it from `docs/submission/README.md`.

## Scenes

Routes are from `apps/web/src/app.tsx`; `:t` is the treasury id and `:org` the org id. What is
visible is the target state; confirm it against the running build during the dry run.

### D1 - Refill then pay (`demo-main`) - RUNNABLE (on chain)
Runner: on-chain outcome only (planner, AI and UI not driven); see `scenarios/README.md`.
- Screen: `/o/:org/t/:t/plans`, then `/o/:org/t/:t/plans/:p`: plan with a refill (Safe T to Safe O1) followed by the invoice payment, both with tx hashes.
- Must show: invoice paid once from Safe O1; evidence lists both transactions and resolves them on chain.
- Fallback: show the approved request (seeded INV-TEST-003) at `/o/:org/requests/:r`. Without the planner, `/plans` has no plan to open and shows its empty state (confirm in the dry run); say the plan and execution are pending. No `cast` fallback: refill and pay run through the executor and a Safe T move needs an owner signature, so there is no honest one-liner. Show screenshots of the request and the seeded Safe balances instead.
- Evidence: `docs/evidence/scenarios/demo-main-*/`; manual: screenshots plus both tx hashes.

### D2 - Supply surplus (`aave-supply`) - RUNNABLE (on chain)
Runner: on-chain outcome only (planner, AI and UI not driven); see `scenarios/README.md`.
- Screen: `/o/:org/t/:t/plans/:p` showing a supply of exactly the surplus above RequiredSafeReserve.
- Fallback: without the planner the plans page is empty (confirm in the dry run), so there are no plan numbers; show the Aave position on Sepolia via the block explorer and say planning and execution are pending.
- Evidence: `docs/evidence/scenarios/aave-supply-*/`; manual: screenshot of the plan, explorer link.

### D3 - Withdraw for a new invoice (`aave-withdraw`) - RUNNABLE (on chain)
Runner: on-chain outcome only (planner, AI and UI not driven); see `scenarios/README.md`.
- Screen: `/o/:org/requests/:r` (new approved invoice), then its plan with a withdraw that restores the reserve.
- Fallback: as D2 (empty plans page without the planner); show the approved request and say the withdraw plan is pending.
- Evidence: `docs/evidence/scenarios/aave-withdraw-*/`.

### D4 - Injected invoice, unknown payee (`injected-invoice`) - RUNNABLE (on chain)
Runner: on-chain outcome only (planner, AI and UI not driven); see `scenarios/README.md`.
- Screen: `/o/:org/review` (review queue) with the invoice flagged for the injected instruction and the unknown payee; `/o/:org/t/:t/payees` shows the payee is not Active.
- Must show: never paid.
- Fallback: upload the prepared injected invoice at `/o/:org/requests/upload` (or create it at `requests/new`) and show it held in review; no payment appears.
- Evidence: `docs/evidence/scenarios/injected-invoice-*/`; manual: screenshots of the flag and the empty payment list.

### D5 - Over-cap payment and owner exception (`over-cap-exception`) - RUNNABLE (on chain)
Runner: on-chain outcome only (planner, AI and UI not driven); see `scenarios/README.md`.
- Screen: `/o/:org/t/:t/mandate` (cap), `/o/:org/approvals` (exception request), then the plan page.
- Must show: blocked above the cap; one-time owner exception lets it through once.
- Fallback: show the mandate cap at `/mandate` and the approvals page. No `cast` fallback: the pay path is executor-only with typed arguments and `grantException` is a Safe-owner call, so it cannot be a safe one-liner. Describe the revert from the contract tests (`make test-contracts`) and use screenshots.
- Evidence: `docs/evidence/scenarios/over-cap-exception-*/`; manual: revert output plus the approval screenshot.

### D6 - Borrow proposal (`borrow-proposal`) - RUNNABLE (on chain)
Runner: on-chain outcome only (planner, AI and UI not driven); see `scenarios/README.md`.
- Screen: `/o/:org/t/:t/borrow/:id` with engine numbers (cost vs withdraw, health factor before and after, reason) and no executable plan.
- Fallback: show the proposal numbers from the API response or the borrow page and state that nothing executes.
- Evidence: `docs/evidence/scenarios/borrow-proposal-*/`.

### D7 - Owner-signed borrow (`borrow-execution`) - RUNNABLE (on chain)
Runner: on-chain outcome only (planner, AI and UI not driven); see `scenarios/README.md`.
- Screen: `/o/:org/t/:t/borrow/:id` after the owner signs the one-time authorization; borrowed amount equals the authorized amount.
- Fallback: skip live; show the D6 proposal and describe the authorization step (P2 scope).
- Evidence: `docs/evidence/scenarios/borrow-execution-*/`.

### D8 - Borrow repayment (`borrow-repay`, YAML D8; ADR D8 = AI outage) - RUNNABLE (on chain)
Runner: on-chain outcome only (planner, AI and UI not driven); see `scenarios/README.md`.
- Screen: `/o/:org/t/:t/borrow/:id` showing the borrow closed.
- Fallback: as D7.
- Evidence: `docs/evidence/scenarios/borrow-repay-*/`.
- Note: see Numbering; reconcile in the follow-up decision.

### D9 - Crash recovery (`crash-recovery`, YAML D9; ADR D9 = unknown tx) - RUNNABLE (on chain)
Runner: on-chain outcome only (planner, AI and UI not driven); see `scenarios/README.md`.
- Screen: `/o/:org/t/:t/plans/:p` before and after the restart; one payment, no duplicate.
- Fallback (only works once `executor-pipeline` exists; before that there is nothing executing to kill): with a plan executing, kill the core worker (celery queue `core`, compose service `worker`) and start it again:
  ```sh
  docker compose --env-file infra/env/.env -f infra/compose.yaml --profile local kill worker
  docker compose --env-file infra/env/.env -f infra/compose.yaml --profile local up -d worker
  ```
  Then show the single transaction in `/o/:org/reconciliation`. No `cast` step is needed.
- Evidence: `docs/evidence/scenarios/crash-recovery-*/`; manual: tx hash list proving one payment.

### AI outage (ADR D8) - no scenario file
- Fallback: `docker compose --env-file infra/env/.env -f infra/compose.yaml --profile local kill worker-ai`, then show that manual review still works (`/o/:org/review`, create a request at `requests/new`). Restore with `... up -d worker-ai`.
- Evidence: screenshots only.

### Unknown tx (ADR D9, `unexpected-outflow`, YAML M19-D5) - RUNNABLE (on chain)
Runner flags a transfer out of Safe O1 that bypasses the module (a stand-in for the chain-reader alert). UI fallback: show the alerts page and explain the rule; no `cast` fallback, because moving funds out of Safe T needs an owner signature.

### D10 - Guardian pause (`pause`, YAML D10) - RUNNABLE
Needs: Anvil and `make deploy-local`. The run reverts to its snapshot, so the module is Active again afterwards (use `--keep-state` for the visible pause).
- Run: `make scenario NAME=pause`.
- Screen, accurately: the runner sends `pause()` straight to the module as Anvil #3. The worker indexer's `Paused` handler (`chain/event_handlers.py`) then writes `backend_pause` with `onchain_status = Effective`; it does not set `treasuries.status`, and the dashboard badge reads `treasury.status`. So with the stack running, expect the dashboard badge to stay as is, while `GET /v1/orgs/:org/treasuries/:t/pause` reports `effective: true`. Use the runner output and `cast call` for the on-chain proof.
- For a visible UI pause, pause from the dashboard instead: sign in as the owner (OWN/GRD) and click Pause (needs the treasury status Active). Do this on a fresh module (not after the runner has paused it), since a module is paused only once.
- Must show: guardian pauses with one transaction; status Paused on chain (the step asserts both, receipt status 1 and module status).
- Fallback: if the runner fails, `make deploy-local` (then `make seed`) to get a fresh module and rerun; if it still fails, pause by hand with the unlocked Anvil guardian (#3):
  ```sh
  M=$(jq -r .module deployments/31337.json)
  cast send $M "pause()" --rpc-url http://127.0.0.1:8545 --unlocked --from 0x90F79bf6EB2c4f870365E785982E1f101E93b906
  cast call $M "status()(uint8)" --rpc-url http://127.0.0.1:8545   # 1 = Paused (0 = Active)
  ```
- Evidence: `docs/evidence/scenarios/pause-<UTC time>/run.json` and `evidence-bundle.json`.

### Not in D1-D10
`fee-spike` (YAML M19-D5) is RUNNABLE: the runner spikes the Anvil base fee and applies the fee policy math. UI fallback: show `/o/:org/t/:t/settings/fees` and explain the pause rule.

## Dry run
The acceptance criterion "a teammate who did not write this completes a dry run" is manual.

- [ ] Setup steps 1-7 completed from a clean checkout
- [ ] `make ps` all healthy; `make smoke` passes
- [ ] `make scenario` output matches the sample below 
- [ ] `make scenario NAME=pause` passes and writes `run.json` and `evidence-bundle.json`
- [ ] Each scene's screens and fallback walked through; the routes marked "confirm in the dry run" checked
- [ ] Replay of `pause` works (the runner resets Anvil itself)

| Date | Name |
|---|---|
| not yet done | |

Sample `make scenario` output (name, ADR label, chain, state):

```
aave-supply          D2     chain 31337  runnable
aave-withdraw        D3     chain 31337  runnable
borrow-execution     D7     chain 31337  runnable
borrow-proposal      D6     chain 31337  runnable
borrow-repay         D8     chain 31337  runnable
crash-recovery       D9     chain 31337  runnable
demo-main            D1     chain 31337  runnable
fee-spike            M19-D5 chain 31337  runnable
injected-invoice     D4     chain 31337  runnable
over-cap-exception   D5     chain 31337  runnable
pause                D10    chain 31337  runnable
unexpected-outflow   M19-D5 chain 31337  runnable
```
