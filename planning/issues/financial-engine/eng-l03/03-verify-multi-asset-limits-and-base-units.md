# [ENGINE] Verify multi-asset limits and base-unit arithmetic

| Field | Value |
|---|---|
| **ID** | ENG-L03c |
| **Parent** | [ENG-L03](../l03-extend-the-scheduler-to-multiple-assets.md) |
| **Phase / Priority** | Later / - |
| **Size** | S (1 day) |
| **Status** | Accepted |
| **Depends on** | ENG-L03b |

Add unit and property tests proving independent per-asset pay/refill caps and balances, stable combined ordering/objectives, and integer `BaseUnits` outputs under generated amounts and policy limits.

Acceptance: tests cover assets with different caps and liquidity, including one asset exhausted while another remains schedulable; no float conversion or cross-asset capacity leakage occurs.
