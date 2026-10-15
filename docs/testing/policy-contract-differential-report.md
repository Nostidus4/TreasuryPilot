# POL-004 policy and contract differential report

The pytest validator suite and Foundry module suite read the same case manifest at
`contracts/test/vectors/policy_contract_differential.json`. Python checks each
`validate_step` decision and primary reason code; Foundry checks module success or
the exact custom-error selector. The expected result column below is the contract
side of that shared manifest.

| Case | Scenario | Validator result | Primary code | Module result |
|---|---|---|---|---|
| `valid_pay` | Approved payment | ALLOW | — | success |
| `cap_exact` | Payment exactly at per-request cap | ALLOW | — | success |
| `cap_plus_one` | Payment one base unit above cap | NEEDS_APPROVAL | `OVER_PER_REQUEST_LIMIT` | `OverPerRequestLimit()` |
| `daily_limit` | Payment crosses remaining daily limit | BLOCK | `OVER_DAILY_LIMIT` | `OverDailyLimit()` |
| `unknown_payee` | Payee is not registered | BLOCK | `PAYEE_UNKNOWN` | `PayeeUnknown()` |
| `cooling_before_edge` | Payee is one second before activation | BLOCK | `PAYEE_COOLING` | `PayeeCooling()` |
| `cooling_at_edge` | Payment at the activation timestamp | ALLOW | — | success |
| `mandate_paused` | Mandate is paused | BLOCK | `MANDATE_PAUSED` | `MandatePaused()` |
| `approval_expired` | Signed approval expired | BLOCK | `APPROVAL_EXPIRED` | `ApprovalExpired()` |
| `refill_bound` | Refill would exceed request plus target bound | BLOCK | `REFILL_EXCEEDS_NEED` | `RefillExceedsNeed()` |
| `valid_exception` | Owner exception exactly matches payment | ALLOW | — | success |
| `invalid_exception` | Owner exception amount differs from payment | BLOCK | `EXCEPTION_INVALID` | `ExceptionInvalid()` |
| `duplicate_blocked` | Reused fingerprint without allowance | BLOCK | `DUPLICATE_FINGERPRINT` | `DuplicateFingerprint()` |
| `duplicate_allowed` | Reused fingerprint with request-specific allowance | ALLOW | — | success |
| `mandate_revoked` | Mandate is revoked | BLOCK | `MANDATE_REVOKED` | `MandateRevoked()` |
| `mandate_expired` | Mandate expired | BLOCK | `MANDATE_EXPIRED` | `MandateExpired()` |
| `mandate_not_started` | Mandate not yet valid | BLOCK | `MANDATE_NOT_ACTIVE` | `NotActive()` |
| `mandate_revoked_and_expired` | Revoked and expired: revoked wins | BLOCK | `MANDATE_REVOKED` | `MandateRevoked()` |
| `mandate_paused_and_expired` | Paused and expired: paused wins | BLOCK | `MANDATE_PAUSED` | `MandatePaused()` |

`cap_plus_one` is intentionally `NEEDS_APPROVAL`: it is not executable under the
current mandate, and the module rejects it until an owner exception is granted.

## Traceability

| POL-004 acceptance criterion | Evidence |
|---|---|
| Validator ALLOW equals contract success | `test_validator_matches_contract_differential_matrix` and `PolicyContractDifferentialTest` share the manifest |
| Revert selector equals validator primary code | same pytest (`decode_revert`) and the selector check in `_compare` |
| Report lists the cases | this file; `test_report_lists_every_manifest_case` fails on drift |
| CI | `contract-integration.yml`, step "Differential policy validator and contract cases (POL-004)" |
