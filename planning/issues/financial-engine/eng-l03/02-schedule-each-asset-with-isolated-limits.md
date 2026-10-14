# [ENGINE] Schedule each asset with isolated limits

| Field | Value |
|---|---|
| **ID** | ENG-L03b |
| **Parent** | [ENG-L03](../l03-extend-the-scheduler-to-multiple-assets.md) |
| **Phase / Priority** | Later / - |
| **Size** | M (1.5 days) |
| **Status** | Accepted |
| **Depends on** | ENG-L03a |

Use the existing deterministic solver independently for each asset's requests, wallet/source balances, and policy. Merge results into a deterministic plan, aggregating objective terms and infeasible/binding reasons without sharing liquidity or limits across assets.

Acceptance: each asset's schedule respects only its own balance and limits; combined results are deterministically ordered and scored.
