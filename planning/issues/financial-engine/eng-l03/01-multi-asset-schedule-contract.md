# [ENGINE] Define the multi-asset schedule contract

| Field | Value |
|---|---|
| **ID** | ENG-L03a |
| **Parent** | [ENG-L03](../l03-extend-the-scheduler-to-multiple-assets.md) |
| **Phase / Priority** | Later / - |
| **Size** | S (0.5 day) |
| **Status** | Accepted |
| **Depends on** | ENG-007 |

Define an explicit multi-asset scheduling input keyed by asset, with each asset carrying its requests, snapshot, and policy. Scheduled items must carry asset identity. Validate that request IDs are unique across the combined plan and asset groupings are consistent.

Acceptance: existing single-asset callers retain behavior; invalid or ambiguous multi-asset inputs fail clearly; monetary values use `BaseUnits`.
