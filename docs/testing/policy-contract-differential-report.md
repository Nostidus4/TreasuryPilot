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
| `approval_payee_changed` | Payee changed after approval (signature no longer matches) | BLOCK | `APPROVAL_STALE` | `ApprovalInvalid()` |
| `approval_missing` | Request not approved: no approval signature | BLOCK | `NOT_APPROVED` | `ApprovalInvalid()` |
| `approval_bad_signature` | Signature does not match the approval | BLOCK | `APPROVAL_INVALID` | `ApprovalInvalid()` |
| `approval_signer_not_approver` | Valid signature from a signer outside the approver set | BLOCK | `NOT_IN_APPROVER_SET` | `NotApprover()` |
| `buffer_breach` | Payment would leave the paying wallet below its buffer | BLOCK | `BUFFER_BREACH` | `BufferBreach()` |
| `source_buffer_breach` | Refill would leave Safe T below its buffer | BLOCK | `SOURCE_BUFFER_BREACH` | `SourceBufferBreach()` |
| `daily_exact` | Payment exactly fills the daily limit | ALLOW | — | success |
| `refill_bound_exact` | Refill lands exactly on request plus target bound | ALLOW | — | success |
| `refill_per_request` | Refill one base unit above the per-request refill limit | BLOCK | `OVER_REFILL_PER_REQUEST` | `OverRefillPerRequest()` |
| `refill_daily` | Refill after the daily refill limit is used | BLOCK | `OVER_REFILL_DAILY` | `OverRefillDaily()` |
| `wrong_payment_option` | Paid amount differs from the signed option | BLOCK | `WRONG_PAYMENT_OPTION` | `WrongPaymentOption()` |
| `request_already_paid` | Request already paid | BLOCK | `REQUEST_ALREADY_PAID` | `RequestAlreadyPaid()` |
| `request_cancelled` | Request cancelled on chain | BLOCK | `REQUEST_CANCELLED` | `RequestCancelled()` |
| `step_already_executed` | Step id already used | BLOCK | `STEP_ALREADY_EXECUTED` | `StepAlreadyExecuted()` |
| `refill_already_done` | Second refill for the same request and wallet | BLOCK | `ALREADY_REFILLED_FOR_REQUEST` | `AlreadyRefilledForRequest()` |
| `not_executor` | Caller is not the mandate executor | BLOCK | `EXECUTOR_MISMATCH` | `NotExecutor()` |

`approval_payee_changed` and `approval_missing` are off-chain-only codes
(`APPROVAL_STALE`, `NOT_APPROVED`): the module cannot see a stale request or a missing
approval, so it rejects the call as `ApprovalInvalid()` (manifest key `contract_code`).
Both sides block; only the label differs, as the policy-engine README catalogue states.

The Foundry suite runs on the in-process Foundry EVM, which stands in for Anvil: it is the
same EVM semantics without a separate node process.

Not covered (SHOULD): `WrongRefillTarget` and `NotOperationalWallet`. `validate_step` has no
step-level check for either (the planner and the plan-shape rule catch them), so a
single-step differential would compare different layers; see the PR for the follow-up.

`cap_plus_one` is intentionally `NEEDS_APPROVAL`: it is not executable under the
current mandate, and the module rejects it until an owner exception is granted.

## Traceability

| POL-004 acceptance criterion | Evidence |
|---|---|
| Validator ALLOW equals contract success | `test_validator_matches_contract_differential_matrix` and `PolicyContractDifferentialTest` share the manifest |
| Revert selector equals validator primary code | same pytest (`decode_revert`) and the selector check in `_compare` |
| Report lists the cases | this file; `test_report_lists_every_manifest_case` fails on drift |
| CI | `contract-integration.yml`, step "Differential policy validator and contract cases (POL-004)" |
