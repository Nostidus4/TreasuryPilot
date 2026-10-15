# Demo runbook (D1-D10)

Step-by-step script for the 5-minute judge demo (DEV-008, #68). Scenes follow ADR-019 D1-D10 and
each one names its scenario file in `scenarios/` (DEV-007 runner). Scene timing and narrative:
`docs/research/TreasuryPilot-Ke-hoach-nang-diem-80-90.md` section 7.

**Status today:** only `pause` (D10) is runnable end to end. Every other scene is `NOT_RUNNABLE`
(the runner exits 2 and writes no evidence); use the manual fallback given per scene. Re-check with
`make scenario`, which lists every scenario as `runnable` or `not runnable yet`.

## Setup

Prerequisites: Docker, Foundry (`anvil`, `cast`, `forge`), uv 0.11.3, pnpm.

1. `make bootstrap` installs Python and web dependencies.
2. `cp infra/env/.env.example infra/env/.env` and fill the required values (`make check-env` fails if the file is missing).
3. `make dev` starts the full local stack (Postgres, Redis, MinIO, Anvil, API, workers, web). `make ps` shows state, `make logs` tails it. `make infra` starts only the backing services and Anvil.
4. `make seed` deploys the contracts to Anvil (via `make deploy-local`, skipped if the module is already deployed), seeds the TEST-labelled orgs, payees and invoices, and recreates the API with the new chain config.
5. `make smoke` checks the stack is healthy.
6. Web UI: `make web-dev` (Vite, http://localhost:5173) or the `web` container from `make dev`.

## Reset between runs

- Contracts only (needed before replaying `pause`, because resume is a Safe-owner transaction): `make deploy-local`, then `make seed` to repoint the data at the new Safe addresses (each deploy creates new Safes).
- Full reset: `make down`, then repeat Setup from step 3. `make down` runs `docker compose down --remove-orphans`; it does not pass `-v`, so to wipe volumes run the same compose command with `-v` by hand.
- Evidence from earlier runs stays under `docs/evidence/scenarios/`; the runner never deletes it.

## Running a scenario

```sh
make scenario                 # list names and runnable state
make scenario NAME=pause      # run one
```

Exit codes: 0 passed, 2 `NOT_RUNNABLE`, anything else failed. A passed run writes
`docs/evidence/scenarios/<name>-<UTC time>/run.json` and `evidence-bundle.json`. Evidence is
written only by the runner; for manual fallbacks, take screenshots and tx hashes and store them in
the same folder layout by hand.

## Scenes

Routes are from `apps/web/src/app.tsx`; `:t` is the treasury id and `:org` the org id. What is
visible is the target state; confirm it against the running build during the dry run.

### D1 - Refill then pay (`demo-main`) - NOT_RUNNABLE
Waits on: `planner`, `sequencer` (#65), `executor-pipeline`.
- Screen: `/o/:org/t/:t/plans`, then `/o/:org/t/:t/plans/:p`: plan with a refill (Safe T to Safe O1) followed by the invoice payment, both with tx hashes.
- Must show: invoice paid once from Safe O1; evidence lists both transactions and resolves them on chain.
- Fallback: show the approved request at `/o/:org/requests/:r`, move the funds by hand with `cast send` on Anvil (refill, then pay), and show the hashes next to the plan page.
- Evidence: `docs/evidence/scenarios/demo-main-*/`; manual: screenshots plus both tx hashes.

### D2 - Supply surplus (`aave-supply`) - NOT_RUNNABLE (Sepolia)
Waits on: `planner`, `aave-adapter`, `executor-pipeline`.
- Screen: `/o/:org/t/:t/plans/:p` showing a supply of exactly the surplus above RequiredSafeReserve.
- Fallback: present the plan numbers from the plans page and the Aave position on Sepolia via the block explorer; say execution is pending.
- Evidence: `docs/evidence/scenarios/aave-supply-*/`; manual: screenshot of the plan, explorer link.

### D3 - Withdraw for a new invoice (`aave-withdraw`) - NOT_RUNNABLE (Sepolia)
Waits on: `planner`, `aave-adapter`, `executor-pipeline`.
- Screen: `/o/:org/requests/:r` (new approved invoice), then its plan with a withdraw that restores the reserve.
- Fallback: as D2, with the withdraw shown as plan numbers only.
- Evidence: `docs/evidence/scenarios/aave-withdraw-*/`.

### D4 - Injected invoice, unknown payee (`injected-invoice`) - NOT_RUNNABLE
Waits on: `ai-extraction`, `planner`.
- Screen: `/o/:org/review` (review queue) with the invoice flagged for the injected instruction and the unknown payee; `/o/:org/t/:t/payees` shows the payee is not Active.
- Must show: never paid.
- Fallback: upload the prepared injected invoice at `/o/:org/requests/upload` (or create it at `requests/new`) and show it held in review; no payment appears.
- Evidence: `docs/evidence/scenarios/injected-invoice-*/`; manual: screenshots of the flag and the empty payment list.

### D5 - Over-cap payment and owner exception (`over-cap-exception`) - NOT_RUNNABLE
Waits on: `planner`, `executor-pipeline`.
- Screen: `/o/:org/t/:t/mandate` (cap), `/o/:org/approvals` (exception request), then the plan page.
- Must show: blocked above the cap; one-time owner exception lets it through once.
- Fallback: show the mandate cap, attempt the payment by hand with `cast send` against the module on Anvil and show the revert, then show the exception on the approvals page.
- Evidence: `docs/evidence/scenarios/over-cap-exception-*/`; manual: revert output plus the approval screenshot.

### D6 - Borrow proposal (`borrow-proposal`) - NOT_RUNNABLE (Sepolia)
Waits on: `planner`, `aave-adapter`.
- Screen: `/o/:org/t/:t/borrow/:id` with engine numbers (cost vs withdraw, health factor before and after, reason) and no executable plan.
- Fallback: show the proposal numbers from the API response or the borrow page and state that nothing executes.
- Evidence: `docs/evidence/scenarios/borrow-proposal-*/`.

### D7 - Owner-signed borrow (`borrow-execution`) - NOT_RUNNABLE (Sepolia, P2)
Waits on: `planner`, `aave-adapter`, `executor-pipeline`, `borrow-authorization`.
- Screen: `/o/:org/t/:t/borrow/:id` after the owner signs the one-time authorization; borrowed amount equals the authorized amount.
- Fallback: skip live; show the D6 proposal and describe the authorization step (P2 scope).
- Evidence: `docs/evidence/scenarios/borrow-execution-*/`.

### D8 - Borrow repayment (`borrow-repay`) - NOT_RUNNABLE (Sepolia, P2, name provisional)
Waits on: `planner`, `aave-adapter`, `executor-pipeline`, `borrow-authorization`.
- Screen: `/o/:org/t/:t/borrow/:id` showing the borrow closed.
- Fallback: as D7.
- Evidence: `docs/evidence/scenarios/borrow-repay-*/`.
- Note: ADR-019 V3-12 lists D8 as "AI outage"; `scenarios/borrow-repay.yaml` uses D8 for repayment. Reconcile when the AI-outage scenario is written (no scenario file exists for it yet).

### D9 - Crash recovery (`crash-recovery`) - NOT_RUNNABLE
Waits on: `executor-pipeline`, `outbox-recovery`.
- Screen: `/o/:org/t/:t/plans/:p` before and after the restart; one payment, no duplicate.
- Fallback: with a plan executing, `docker compose --env-file infra/env/.env -f infra/compose.yaml --profile local stop <executor service>` (see `make ps` for the name), start it again, then show the single transaction in `/o/:org/reconciliation`.
- Evidence: `docs/evidence/scenarios/crash-recovery-*/`; manual: tx hash list proving one payment.
- Note: ADR-019 V3-12 lists D9 as "unknown tx"; the related `unexpected-outflow` scenario (M19-D5, `chain-reader-alerts`, also NOT_RUNNABLE) covers that. Fallback for it: send a transfer from Safe T with `cast send` outside the app and show the alert.

### D10 - Guardian pause (`pause`) - RUNNABLE
Needs: Anvil and a fresh deployment (`make deploy-local`; resume is a Safe-owner transaction).
- Run: `make scenario NAME=pause`.
- Screen: `/o/:org/t/:t` (dashboard status banner) reads Paused after the run; the module status also reads Paused on chain.
- Must show: guardian pauses with one transaction; status Paused on chain (the step asserts both, receipt status 1 and module status).
- Fallback: if the runner fails, `make deploy-local` to get a fresh module and rerun; if it still fails, call `pause()` on the module from the guardian account with `cast send` and show `cast call` status.
- Evidence: `docs/evidence/scenarios/pause-<UTC time>/run.json` and `evidence-bundle.json`.

### Not in D1-D10
`fee-spike` (M19-D5, `fee-policy-runtime`) is NOT_RUNNABLE; fallback: show `/o/:org/t/:t/settings/fees` and explain the pause rule.

## Dry run
The acceptance criterion "a teammate who did not write this completes a dry run" is manual. Record
the date and person here after it is done: not yet done.
