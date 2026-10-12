# M1 contract rule evidence

Scope: the final PR stack, real Safe 1.4.1 calls, synthetic assets and the pinned
Aave forks. Test names below identify direct module calls (executor or attacker)
except governance, which belongs to Safe T. Backend-only conditions and Later
features are listed separately; a passing contract test does not prove them.

| C-rule or contract portion | Test / property | Expected boundary |
| --- | --- | --- |
| BR-001/003/004 | `testDirectUnsignedApprovalCannotMoveTreasuryFunds`, `testDirectAlteredPayeeAmountAssetAndRequestFailCryptographicProof`, 13-field fuzz; domain/current-approver tests | ApprovalInvalid, NotApprover, ApprovalExpired |
| BR-010 | direct paused/cooling/cancelled suite; mandate window test | NotActive, MandateExpired, RequestCancelled |
| BR-011 | `testDirectArbitrarySelectorsAndNativeValueCannotExecute`, fixed pool/pair unit tests, I13 | no generic selector, native value or arbitrary target |
| BR-012/019 | direct refill destination test, `testPayOnlyOperationalWalletAndExecutor` | WrongRefillTarget, NotOperationalWallet, NotExecutor |
| BR-013/017 | cooling/reactivation tests; `testDirectExceptionCannotLiftPayeeRules` | PayeeUnknown, PayeeCooling even with an exception |
| BR-014/015/016 | mandate validation/role/version tests, I8/I9 | InvalidMandate, NotOwner; counters persist |
| BR-020/083 | six-decimal USDC fork, typed integer vectors and publisher config tests | integer base units and reviewed decimals/reserve identity |
| BR-021/022/026 | shared O1/O2 daily test; `testDirectPreviouslySignedStepUsesExecutionDayBudget`, I3/I8 | OverDailyLimit; mined execution day, persistent prior counters |
| BR-023 | `testDirectRefillCapsAndExactDailyBoundaryWithRollback`, I3 | OverRefillPerRequest, OverRefillDaily; separate PAY/REFILL counters |
| BR-024 | early boundary/single-option fuzz, I14 and its prior mutation evidence | exact approved option, WrongPaymentOption |
| BR-025 | malicious-token rollback, cap/exception rollback assertions | no balance/counter/replay/grant effects on revert |
| BR-030 | buffer boundary, direct refill source-floor test, AT11/AT12, I4 | BufferBreach, SourceBufferBreach |
| BR-036 | refill bound/replay/destination unit tests, I10 | RefillExceedsNeed, AlreadyRefilledForRequest, WrongRefillTarget |
| BR-037 | supply floor/per-tx/daily/rounding/rollback tests, I12/I13 | SupplyFloorBreach, OverSupplyPerTx, OverSupplyDaily; static floor only |
| BR-038 | supply/withdraw exact-cash test and USDC D3 fork | withdrawal returns exactly to Safe T |
| BR-040/041/042/043 | exception wrong-payee/expiry/request/revoke matrix, amount/version/daily tests, AT11, I6 | ExceptionInvalid, OverPerRequestLimit, OverDailyLimit, BufferBreach, NotOwner |
| BR-044 (P2) | unauthorized/expired/reused grant and pre/post HF/rate tests; I15, isolated used-guard mutation | BorrowNotAuthorized, AuthorizationExpired, HealthFactorTooLow, BorrowRateTooHigh; opaque owner-reviewed plan hash |
| BR-060/061 | request/step replay units; replay handler + isolated step-guard mutation, I5 | RequestAlreadyPaid, StepAlreadyExecuted; no second execution |
| BR-062/064 | permanent revoke and guardian role tests, I7 | NotActive, NotOwner; configure cannot revive revoked module |
| BR-068 | `testGuardianSafeOneOfTwoCanPauseButCannotResume` | real Guardian Safe pause path; resume only Safe T |
| BR-071 | exact-request duplicate override unit and direct duplicate case, I5 | DuplicateFingerprint; one matching override |
| BR-072 (registry portion) | deactivate/reactivate/cooling tests | old/deactivated payee cannot PAY; new entry cools |
| BR-077 | cancellation unit/direct cases and I11 | RequestCancelled, NotOwnerOrApprover, AlreadyPaid |
| BR-080 | native-value rejection and test-router ERC20 output test | no native transfers from module routes |
| BR-081/082 (test router) | fixed-pair/minOut/budget/allowance tests | RouterNotAllowed, OverSwapPerTx/Daily, TransferFailed; allowance zero |
| BR-090/091 | module fixed-call ABI, clone identity, factory/owner tests, I13/I15 | fixed asset/pool/Safes; P2 borrowing only under owner grant |
| FR-510 / SC-021 | `testBorrowEventMatchesChainReaderTopicAndPayload`, `testFactoryEventContainsCallingSafeCloneAndAsset` | canonical BorrowExecuted and factory event topics/fields |

## Ownership beyond contract tests

BR-018 coverage acknowledgments, BR-035 dynamic holds, the PaymentReserve portion
of BR-037/038, BR-059 policy attestation checks, provider outcome reconciliation
in BR-060, BR-063 backend stop, BR-067 simulation, BR-072 invoice anomaly detection,
production quote freshness/slippage in BR-081 and runtime decimals/configuration
outside the deployment publisher require their backend/signer/chain-reader suites.
The contract stores a plan hash and checks instantaneous rate/HF, not future
financing cost or a recomputed snapshot. On-chain policy verification and
multi-asset/n-of-m approval rules are Later. Public testnet evidence and external
audit are separate acceptance work.
