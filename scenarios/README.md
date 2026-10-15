# Reproducible scenarios

One YAML file per named scenario (DEV-007, ADR-019 D1-D10 plus the M19-D5 extras). Run with:

```sh
uv run python infra/scripts/scenario.py list
uv run python infra/scripts/scenario.py run demo-main    # needs Anvil and `make deploy-local`
```

Fields: `name` (= file name), `adr019` (D-id), `chain_id` (must be in the allowlist: 31337, 11155111;
the live RPC chain id must match, anything else such as mainnet is refused with exit 1), `requires`
(capabilities, checked against the step functions in `infra/scripts/scenario_steps.py`), `steps`
(non-empty), `must_show` (documentation; each step asserts its own outcome and fails the run if it
does not hold).

| Scenario | ADR-019 | Step | What it asserts on Anvil |
|---|---|---|---|
| `demo-main` | D1 | `refill_then_pay` | refill Safe O1, pay once, replay rejected |
| `aave-supply` | D2 | `supply_surplus` | surplus supplied, reserve intact, aToken minted |
| `aave-withdraw` | D3 | `withdraw_for_invoice` | Aave cash withdrawn into Safe T, then the invoice is paid |
| `injected-invoice` | D4 | `unknown_payee_blocked` | `PayeeUnknown`, no funds move |
| `over-cap-exception` | D5 | `over_cap_exception` | `OverPerRequestLimit`, then one owner exception pays once |
| `borrow-proposal` | D6 | `borrow_unauthorized` | `BorrowNotAuthorized`, no debt |
| `borrow-execution` | D7 | `owner_borrow` | exactly the authorized amount, one time |
| `borrow-repay` | D8 | `owner_borrow_repay` | debt closed by the authorized repayment |
| `crash-recovery` | D9 | `crash_after_refill` | refill-only crash, retry refused, recovery pays once |
| `pause` | D10 | `guardian_pause` | guardian pause, status Paused |
| `unexpected-outflow` | M19-D5 | `outflow_alert` | transfer bypassing the module flagged, module payment not |
| `fee-spike` | M19-D5 | `fee_spike_defers` | 100x base fee gives DEFER `FEE_ABOVE_THRESHOLD`, nothing sent, pays once it clears |

Every run signs payment approvals with the demo approver key, sends real transactions from the
Anvil demo identities, snapshots Anvil first and reverts afterwards (`--keep-state` leaves the
result in place; replaying then needs a fresh deployment), and writes
`docs/evidence/scenarios/<name>-<UTC time>/run.json` plus `evidence-bundle.json`
(evidence-bundle.v1, validated before it is written; blocked-action scenarios mine no transaction).

Aave scenarios use the TEST-only `MockAavePool` that `Deploy.s.sol` deploys on Anvil, not a fork.

## Stand-ins (known gaps)

The runner plays the contract and policy layers directly. The planner, sequencer, AI extraction,
outbox/tracker, chain-reader alerting and fee-policy services are not started: their outcomes are
asserted from chain state and `treasurypilot_core` fee math (so D4 does not exercise injection
flagging, D9 does not kill a worker, and the unexpected-outflow alert is computed by the runner from
Transfer logs). The evidence bundle subject is the seeded TEST invoice, not a request persisted by
the pipeline.

For the demo scene-by-scene script (setup, reset, fallbacks, evidence) see [docs/demo-runbook.md](../docs/demo-runbook.md).
