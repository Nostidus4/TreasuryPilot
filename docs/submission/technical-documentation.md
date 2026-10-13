# TreasuryPilot technical documentation

DOM-012 / #236. Baseline: main `4b2ee5e89763450078767d564a07f73fabfe2d63`,
2026-10-14. Status: **submission draft; feature-freeze and developer review pending**.
Scope: synthetic testnet treasury evaluation. This baseline is explicitly
identified because several target workflows are still under implementation.

## 1. Problem and scope

Treasury operations combine invoice authenticity, human payment authorization,
wallet liquidity, daily budgets, deadlines and payment evidence. TreasuryPilot
delegates bounded actions from owner-controlled Safes through a custom module.
AI proposes document fields and plans; deterministic code computes money and
validates feasibility; humans approve obligations and govern the mandate.

M1 targets one treasury stablecoin, Safe T plus one operational wallet in the
Sepolia demo, Aave supply/withdraw and borrowing proposals. Owner-authorized
borrow/repay execution and a labelled test router are P2 contract paths. The
local fixture can use two operational wallets to exercise shared counters.
Mainnet, speculative trading and unrestricted execution are outside this demo.

## 2. Architecture and trust boundaries

```mermaid
flowchart LR
  U[Operator and approver] --> API[API: identity and treasury]
  O[Owner wallet] --> ST[Safe T governance]
  API --> DB[(Postgres: org data and audit)]
  API --> Q[Redis queues]
  Q --> AI[AI worker: proposals]
  Q --> W[Core worker: deterministic orchestration]
  AI --> L[External LLM provider]
  W --> E[py-core engine and policy]
  W -.target execution flow.-> S[Internal signer]
  S -.target typed submissions.-> M[TreasuryPilotModule]
  ST --> M
  M --> OW[Operational Safe]
  M --> P[Fixed Aave pool]
  H[Receipt helper] --> EAS[EAS receipt record]
```

Dashed edges identify target integrations absent at this baseline. The signer
service currently exposes health only. The core worker tasks are infrastructure
probes; they do not implement the diagram's payment loop. The AI process has an
explicit environment allowlist without policy/executor keys. This is a deployed
configuration boundary, not proof against compromise of the common host.

| Component | Implemented baseline                                                                                                                                         | Remaining target integration                                                                       |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| Contracts | Clone/factory, governance, PAY/REFILL, budgets/floors/replay, fixed Aave supply/withdraw and owner grants for borrow/repay                                   | Public deployment/verification and application integration                                         |
| py-core   | Strict integer money/domain models, refill formulas, EDF scheduler, payment-option/value functions, forecast, reserve/liquidity decision and borrow proposal | CP-SAT optimizer and exhaustive scheduler oracle are not on this main baseline                     |
| API       | Session/auth and org RBAC, identity/treasury repositories/routes, asset configuration, audit primitives                                                      | Complete invoice approval, maker-checker and policy/execution/reconciliation endpoints             |
| Worker/AI | Queue/environment separation, RPC health/pool primitives, logging/metrics/locks, model adapter/failover/budgets, input sanitization/detector                 | Full extraction/planner/tool/evaluation flow, trigger/executor/recovery and business notifications |
| Signer    | Internal health service                                                                                                                                      | Attestation verification, fresh simulation and typed signing endpoint                              |
| Evidence  | Verified mined-state publisher, schema/receipt helpers, local journals, static/test reports                                                                  | Public Sepolia/EASScan evidence and production reconciliation/uniqueness                           |

See [system architecture](../SYSTEM_ARCHITECTURE.md),
[AI design](../AI_AGENT_ARCHITECTURE.md) and the [security self-assessment](security-self-assessment.md)
for the target design and its present implementation qualifications.

## 3. Money and payment authorization

Money is an integer count of asset base units. For a six-decimal test token,
`"25000000"` represents 25 tokens, not a fiat valuation. Dataset/API serialization
uses decimal strings; the engine uses strict `BaseUnits`, Solidity uses integer
amounts. Asset identity is chain/address; decimals are reviewed against chain state.

PaymentApproval has 13 fields, including exact standard/early options, request,
fingerprint, treasury/wallet, asset/payee, confirmed-term hashes and expiry. EIP-712
binds the chain and module. The contract checks a current approver through EOA
or ERC-1271 verification. While an early option is active, PAY consumes that exact
early amount; otherwise the standard amount. A successful request is consumed
once. A backend approved flag and an AI confidence score do not substitute for
the signature.

Governance requires Safe T as caller; its human threshold is enforced by Safe.
An exact one-time exception can lift the per-request cap, while daily budgets,
floors, allowlist/cooling and expiry remain. Pause/revoke prevent subsequent
module execution after mining and cannot reverse completed transfers. Direct
owner transactions remain a separate Safe authority path.

## 4. Deterministic financial algorithms

### 4.1 Request-bound refill

For destination balance B, hard floor F, soft target H, current demand D and
other protected funds R, the engine computes:

```text
Shortage  = max(0, R + D + F - B)
Preferred = max(0, R + D + H - B)
Bound     = max(0, D + H - B)
Capacity  = max(0, SourceBalance - SourceProtected - SourceFloor)
Cap       = min(Capacity, RemainingRefillDaily, PerRefillLimit)
```

If Shortage is zero, no refill occurs solely to reach H. If Shortage exceeds
Bound, stop. Otherwise use bounded Preferred when it fits Cap, or Shortage when
that fits; if neither fits, stop without partial payment. PAY and REFILL have
separate daily counters. The module additionally binds destination and refill
count to the approved request and checks exact source/destination balance deltas.

### 4.2 Scheduler, payment value and forecast

The implemented `schedule_edf` sorts by due UTC day, approval sequence and request
ID. It iterates 30 days, resets simulated counters at UTC day boundaries, carries
wallet/source cash forward, rechecks cooling and caps, and applies request-bound
refill decisions. A request blocked today can remain eligible on later days.
It returns scheduled items, remaining blockers and an objective tuple:
`(0, missed_deadlines, -total_value, transaction_count)`.

EDF returns a feasible heuristic result, not a global optimum certificate.
The older source calls it B1; ADR-019 benchmark naming is B0 manual/EDF with idle
cash, B1 deterministic optimizer, B2 AI plus optimizer. Reports must use the
ADR-019 labels with explicit algorithm identities and must not relabel EDF as
implemented CP-SAT. The open optimizer/oracle work is excluded here.

For a confirmed early option, value is exact standard-minus-early saving less
estimated execution fee and simple supply interest forgone until due date;
accrued late fees reduce value. Percentage fees use integer basis points and
ceiling period count, then floor monetary division and apply any configured cap.
Late-fee valuation does not authorize a PAY larger than the signed options.
EDF currently supplies rate to valuation but no per-request fee parameter;
benchmark inputs must disclose the resulting zero-fee assumption.

Forecast replays EDF payment/refill order with conserved balances. It reports
due-but-unpaid obligations and their modeled late fees, buffer-hit and shortfall
days. A forecast is conditional on approved inputs and fixed assumptions, not
guaranteed future liquidity.

### 4.3 Idle cash and debt proposal

```text
RequiredSafeReserve = PaymentReserve + SafeFloor + DebtServiceReserve + ExecutionHolds
AvailableForSupply  = max(0, SafeUSDC - RequiredSafeReserve)
AccessibleLiquidity = SafeUSDC + min(aUSDC, PoolAvailableUSDC)
Deficit             = max(0, RequiredSafeReserve - SafeUSDC)
WithdrawTarget      = ceil(Deficit * 105 / 100)
```

PaymentReserve includes approved unpaid obligations due or scheduled within the
configured inclusive reserve horizon; the chosen early amount is used when known,
otherwise standard amount. Supply requires minSupply and respects per-call/daily
caps. A prior withdrawal suppresses supply that day. Withdrawal is bounded by
aToken balance and available pool cash; any remaining deficit yields
INSUFFICIENT_LIQUIDITY rather than an automatic borrow transaction.

The module enforces static floor and supply caps; dynamic reserve calculation is
an off-chain responsibility. Simple-interest borrow proposals use current rate,
amount and repayment interval. Estimated post-borrow HF is unknown without an
existing debt position; current/future rate and liquidation behavior require
review. P2 execution needs an unused, unexpired owner grant and instantaneous
rate/HF checks, not merely an AI recommendation or proposal.

## 5. Validation and proposed execution lifecycle

```mermaid
sequenceDiagram
  participant H as Human
  participant E as Engine/validator
  participant S as Signer (target)
  participant M as Module
  participant R as Tracker/recovery (target)
  H->>H: Confirm invoice and sign exact approval
  E->>E: Fresh snapshot, deterministic plan, policy decision
  E-->>S: Exact attested typed step
  S->>S: Verify policy/signature and simulate fresh state
  S->>M: Submit fixed entry point
  M->>M: Recheck current authority and constraints
  M-->>R: Transaction and receipt/state evidence
  R->>R: Confirm, reconcile, or block while Unknown
```

This sequence describes required end-to-end integration, not a measured runtime
flow in this baseline. Sequential execution, fresh re-reads before each step,
outbox writes, post-conditions and Unknown recovery remain necessary. Completed
steps in a non-atomic sequence must be recorded and not repeated.

## 6. Security and evidence

The [self-assessment](security-self-assessment.md) gives all five permission tiers
and [known risks](../security/known-risks.md) records 25 architectural residuals.
Independent audit, full backend integration and public acceptance remain open.

Contracts match the sources checked by [main CI 6b97124](https://github.com/Nostidus4/TreasuryPilot/actions/runs/38360625984):
86 passing Foundry tests, including aggregate invariant execution. The
[security workflow](https://github.com/Nostidus4/TreasuryPilot/actions/runs/38360626051)
passes I1-I16 at 10,000 runs/depth 32/320,000 calls, detects isolated step/borrow
mutations and passes the exact Slither triage gate. These are bounded tests, not
formal proofs. Seven historical Aave fork cases and local deployment/receipt
evidence are recorded in [test-evidence](../security/test-evidence.md).

Receipt helpers require successful canonical PAY and finalized Sepolia state,
expected schema and configured trusted attester. Invoice/approval/plan/policy
hashes remain backend assertions. Persistent local journals reduce duplicate
sends; production reconciliation still needs database uniqueness.

## 7. Evaluation status and reporting protocol

No extraction accuracy, AI planner uplift, customer-validation count or full
red-team pass rate is established by this document. A dataset authoring artifact
is not a measured benchmark result. Publish measured results only with:

- Dataset and code revision, asset scale, UTC horizon and split/exposure history.
- Actual B0/B1/B2 implementations, fees/rates and failure/fallback behavior.
- Feasibility violations, deadline misses, net modeled value, transaction count,
  latency/cost and sample denominators; include cases where EDF is optimal.
- Independent ground-truth review and protected held-out evaluation. Synthetic
  examples in the public repo are accessible and must not be called unseen.
- Explicit limits: simplified static scenario assumptions, external provider
  availability, no mainnet performance or guaranteed yield extrapolation.

## 8. Deployment and feature-freeze handoff

Follow [DEPLOYMENT](../../contracts/docs/DEPLOYMENT.md). Keep predictions separate
from the published mined-state manifest. Verify canonical Safe infrastructure,
chain/asset/decimals, actual operational list, owner/threshold, module enablement,
pool/aToken and dedicated attester. Demo topology is T/O1; Anvil T/O1/O2 is a
test fixture. Public #70/#31/#84 acceptance remains separate from local forks.
Recheck Aave USDC headroom and current EVM gas behavior before public broadcast.

At feature freeze, update the baseline and implementation/evidence tables, attach
actual benchmark results and public evidence when available, obtain developer
review and export the reviewed Markdown if a PDF is required. This draft exposes
the present gaps so they can be reviewed rather than filled with invented results.
