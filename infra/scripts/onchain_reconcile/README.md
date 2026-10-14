# On-chain / off-chain reconciliation smoke

A small devex tool that proves a Postgres ledger and a chain can be reconciled. It is a smoke
test, not product code: it touches only schema `sandbox` (never `public`) and a throwaway
`TestUSDC` token. The real execution pipeline (operations table with `tx_hash`) is not on `main`
yet; this tool shows the pattern that pipeline should follow.

What it does:

1. `deploy_token.py` deploys `contracts/src/test-assets/TestUSDC.sol` with `forge create` (the
   repo's own remappings) and records it in `sandbox.test_tokens`.
2. `send_transfers.py` uses the outbox pattern: commit a `pending` row, broadcast, then update
   the row from the receipt (1 mint and 3 transfers, integer base units).
3. `reconcile.py` is read-only. DB to chain: receipt status, block, and exactly one `Transfer`
   log with matching from, to and amount. Chain to DB: every `Transfer` since the deploy block
   (`eth_getLogs`, chunked at 2000 blocks, auto-shrunk when a provider caps the range, e.g. 10 on Alchemy's free tier) must map to a row. Exit code 1 on any mismatch.

The comparison rules live in `logic.py` (pure, unit-tested in `../tests/test_onchain_reconcile.py`).

## Setup

- Foundry on `PATH` (`forge`, `cast`) and `pnpm install` at the repo root (OpenZeppelin lands in
  `contracts/node_modules`).
- `uv sync`, then run from the repo root.
- Env, read from the environment only and never printed:
  `RPC_URL`, `PRIVATE_KEY` (deploy and send only), and `DATABASE_URL` or `SUPABASE_DATABASE_URL`.
  Foundry has no env var for raw keys, so the key is passed as `--private-key` to the child process
  (visible in `ps` briefly): use throwaway Anvil or testnet keys only. The tool never prints it.

## Run

    export RPC_URL=... DATABASE_URL=...
    read -rs PRIVATE_KEY && export PRIVATE_KEY      # funded test key; use Anvil or Sepolia only
    cd infra/scripts/onchain_reconcile
    uv run --frozen python deploy_token.py
    uv run --frozen python send_transfers.py
    uv run --frozen python reconcile.py             # exit 0 = in sync

Stale rows (for example after restarting Anvil, which redeploys to the same address) will report
mismatches; delete that chain's rows from `sandbox.test_transfers` and `sandbox.test_tokens`.
