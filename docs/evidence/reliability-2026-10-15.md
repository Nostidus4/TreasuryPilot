# Reliability report 2026-10-15

Scenario `demo-main`; fees in wei (gasUsed x effectiveGasPrice).

## Anvil (local)

- Runs: 30, completed: 30, completion: 100.0%
- Median fee per run: 717747444568550 wei; total: 21531656553692776 wei
- Failure categories: none

`tx:*` rows are individual transactions nested inside the step rows.

| Phase | Median latency (ms) |
|---|---|
| tx:refill | 215.9 |
| tx:pay | 217.7 |
| refill_then_pay | 469.4 |
| evidence_bundle | 3.1 |

## Sepolia (testnet)

Not run (0 runs requested).

