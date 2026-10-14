# M07 · Financial Engine (`py-core`)

**Status:** Detailed (grilling round M07, 2026-10-11) · **Path:** `docs/modules/financial-engine/` · **Code:** `packages/py-core/src/treasurypilot_core/{money,domain,engine}` · **Epic:** `[EPIC] M07 · Financial Engine (py-core)`
**ADRs:** ADR-014 (money), **ADR-015 (CP-SAT solver, new)** · **Decisions:** M07-D1 … M07-D9 (§14)

---

## 1. Purpose and boundaries

The engine is the **only place where amounts and schedules are computed** (BR-034). It is pure: no database, network, chain or LLM access. API, worker, validator, AI tools (`simulate_schedule`) and the benchmark all call the same functions.

| In scope (M1) | Out of scope |
|---|---|
| Money type (integer base units), domain models | Reading chain state (M06), persisting (API/worker) |
| Liquidity calculator: Available, FundingDeficit, Shortage, PreferredRefill, SourceCapacity, Cap, refill decision | Deciding *whether* a step is allowed (M08 validator does that, using engine numbers) |
| Payment-terms model and value function (discounts, late fees) | Extracting terms from text (M09) |
| Scheduler: B1 baseline (EDF) and B2 optimizer (CP-SAT) + exhaustive oracle for tests | Calling the LLM; the AI proposes orderings that the engine scores (M09 → M07) |
| Plan scoring, binding constraints, infeasibility reasons; pure FX conversion and depeg guard (F-041) | Multi-asset (F-015, Later), Oi→Oj refills (F-059, Later) |
| 7-day forecast (P2) | |

## 2. Features, requirements and rules

| Feature | FR | BR |
|---|---|---|
| F-051 Liquidity calculator | FR-403, FR-404 | BR-030–BR-036 |
| F-052 Terms-aware scheduler | FR-405 (revised) | BR-052 (revised) |
| F-035 Terms (model side) | FR-310, FR-311 | BR-075 |
| F-037 Fingerprint | FR-314 | BR-071 |
| F-058 Forecast | FR-415 | — |
| F-092 Benchmark (B1/B2 objective) | FR-805 | BR-052 |

## 3. Concepts

| Term | Definition |
|---|---|
| **BaseUnits** | Non-negative `int` in the asset's smallest unit. Never `float`. |
| **Day** | UTC calendar day `d = unix_seconds // 86400`. **Cut-over:** if `now` is within 30 min of the next UTC midnight, "today" is treated as the next day (M07-D3). |
| **Horizon** | Days `today … today + H`, `H = min(30, max due-day − today + 1)` (M07-D3). |
| **Execution window** | Only actions assigned to *today* are executed; later days are a projection, re-planned every cycle (rolling horizon). |
| **Value** | `discount captured − late fees incurred` for a request paid on a given day (M07-D2: no cost of capital). |
| **Feasible deadline** | A request can be confirmed on-chain on or before its due day (OQ-16), given limits, liquidity, cooling and exceptions. |

## 4. Data model (Pydantic, frozen)

```python
class Asset(BaseModel):          chain_id: int; address: str; decimals: int; symbol: str; is_test: bool
class LateFee(BaseModel):
    kind: Literal["fixed", "percent_per_period"]
    amount: BaseUnits | None = None        # fixed
    rate_bps: int | None = None            # percent_per_period, e.g. 150 = 1.5 %
    period_days: int | None = None         # e.g. 7
    cap: BaseUnits | None = None           # optional total cap (M07-D1)
class PaymentTerms(BaseModel):
    net_due_day: int                       # UTC day number
    discount_bps: int = 0                  # 200 = 2 %
    discount_deadline_day: int | None = None
    late_fee: LateFee | None = None
    priority_note: str | None = None       # free text; the engine ignores it (AI may use it)
class WalletState(BaseModel):    address: str; balance: BaseUnits; buffer: BaseUnits; target: BaseUnits
class Limits(BaseModel):         per_request: BaseUnits; daily: BaseUnits
class PolicyView(BaseModel):     pay: Limits; refill: Limits; cooling_seconds: int
class Snapshot(BaseModel):
    day: int; source: WalletState; operational: dict[str, WalletState]
    used_today: dict[Literal["pay", "refill"], BaseUnits]
    payee_active_day: dict[str, int]       # payee address → first day it can be paid
class ApprovedRequest(BaseModel):
    id: str; paying_wallet: str; payee: str; amount: BaseUnits
    approved_seq: int                      # approval order (tie-break)
    terms: PaymentTerms                    # confirmed terms only (BR-075)
    early_amount: BaseUnits | None = None  # exact signed option; positive when present (ADR-019)
    early_pay_by: int | None = None        # paired with early_amount; UTC day
    exception_granted: bool = False        # Owner grant exists on-chain (M04-D3)
class RefillDecision(BaseModel):
    kind: Literal["none", "preferred", "shortage", "stop"]; amount: BaseUnits; reason: ReasonCode
class ScheduledItem(BaseModel):  request_id: str; day: int; refill: BaseUnits; value: int
class Infeasible(BaseModel):     request_id: str; reason: ReasonCode; detail: str
class Schedule(BaseModel):
    items: list[ScheduledItem]; infeasible: list[Infeasible]
    objective: tuple[int, int, int, int]   # (violations, missed_feasible_deadlines, -value, tx_count) — lexicographic, lower is better
    binding: list[BindingConstraint]; solver: Literal["EDF", "CPSAT", "ORACLE"]; status: Literal["OPTIMAL", "FEASIBLE", "FALLBACK"]
```

All models are immutable; serialization writes `BaseUnits` as decimal strings (ADR-014).

## 5. State

The engine is stateless. Inputs fully determine outputs; identical inputs ⇒ byte-identical outputs (M07-D7).

## 6. Public API (Python, no HTTP)

| Function | Returns | Notes |
|---|---|---|
| `available(w, protected_other) → BaseUnits` | `max(0, B − R − L − F)` | Domain §3.1 |
| `funding_deficit(w, protected_other) → BaseUnits` | `max(0, R + L + F − B)` | |
| `shortage(w, demand, protected_other) → BaseUnits` | `max(0, P_o + D + F − B)` | |
| `preferred_refill(w, demand, protected_other) → BaseUnits` | `max(0, P_o + D + H − B)` | |
| `source_capacity(source, protected_other) → BaseUnits` | `max(0, B_T − R_T − L_T − F_T)` | gas term = 0 in M1 (M04-D10) |
| `decide_refill(req, wallet, source, policy, used_today, protected_other, *, source_protected) → RefillDecision` | see §8.1 | applies the contract bound (M07-D4); `source_protected` = `R_T + L_T` |
| `liquidity_position(snapshot, requests, schedule, policy) → LiquidityPosition` | payment reserve, Safe floor, holds and available liquidity | approved unpaid requests due, or scheduled to be paid, on or before `today + reserve_horizon_days` (1–30, inclusive); `snapshot.source` must be Safe T (`source.balance == safe_usdc`) |
| `decide_liquidity(snapshot, requests, schedule, policy) → LiquidityDecision` | `NONE`, `SUPPLY`, `WITHDRAW`, or `INSUFFICIENT_LIQUIDITY` | `min_supply` is compared with AvailableForSupply, then the supply caps (`used_today["supply"]`) bound the amount; never a zero SUPPLY/WITHDRAW; no SUPPLY on a day with a WITHDRAW (`used_today["withdraw"]`); borrow is never authorized here |
| `request_value(req, pay_day, *, fee_in_asset=0, supply_rate_bps=0) → int` | exact saving − late fee − early-payment costs | §8.2, §15 |
| `schedule_edf(requests, snapshot, policy) → Schedule` | B1 baseline | |
| `schedule_optimal(requests, snapshot, policy, time_limit_s=5) → Schedule` | B2 via CP-SAT | falls back to EDF on solver error/timeout without solution |
| `schedule_cpsat_multi_asset({asset_id: AssetScheduleInput}) → Schedule` | Independent B2 run per asset | Each input owns its balances, usage counters, and policy; scheduled and infeasible results carry `asset_id` |

| `schedule_oracle(requests, snapshot, policy) → Schedule` | exhaustive, ≤ 8 requests and a ≤ 5-day horizon (through the latest due or payee activation day) | **tests and benchmarks only** |
| `score(plan, requests, snapshot, policy) → (violations, missed_deadlines, −value, tx_count)` | lexicographic tuple, lower is better; values are recomputed from confirmed terms | shared by deterministic schedules and AI proposals (AGT-009) |
| `compare_plans(left, right, …) → -1, 0, or 1` | deterministic comparison using `score` | choose between proposals |
| `binding_constraints(plan, …) → BindingConstraintDetail[]` | constraint name, request, day, observed value and limit | shown in the "Why" panel |
| `exception_values(requests, snapshot, policy) → ExceptionValue[]` | potential request value when the Owner grants the required per-request exception | M07-D9 exception drafts |
| `forecast(snapshot, requests, policy, days=7) → Forecast` | daily projections, buffer-hit days, suggested refills | P2 |
| `fingerprint(vendor_id, invoice_no, amount, asset) → bytes32` | §8.5 | must equal the contract's value |
| `propose_fiat_payment(approval, quote, policy, now_timestamp) → BaseUnits` | §8.7 | blocks stale/out-of-tolerance/depegged quotes or amounts above the approved maximum |

The multi-asset entry point optimizes each asset independently, so balances and limits cannot cross assets. `AssetScheduleInput.objective_value_scale` converts native base-unit savings into a common integer unit for the combined objective (for example, scale a 6-decimal stablecoin by `10**12` to report in 18-decimal units). The caller must use one common target unit for every asset. Cross-asset conversion, FX, and depeg checks remain out of scope.

Errors are typed (`InvalidTerms`, `InvalidSnapshot`, `NegativeAmount`) and never return partial results.
Pydantic raises `ValidationError` while constructing input models; engine entry points defensively
revalidate unchecked model instances and surface the corresponding typed domain error.

## 7. Main flows

```mermaid
sequenceDiagram
  participant W as worker (planning task)
  participant E as engine
  participant S as CP-SAT
  participant A as agent (worker-ai)
  W->>E: schedule_edf(requests, snapshot, policy)
  E-->>W: B1 schedule
  W->>E: schedule_optimal(...)
  E->>S: build model, solve (≤ 5 s, 1 worker, fixed seed)
  S-->>E: solution / timeout
  E-->>W: B2 schedule (OPTIMAL / FEASIBLE / FALLBACK=EDF)
  W->>A: propose ordering + rationale (gets B2 + binding constraints)
  A-->>W: proposal
  W->>E: score(proposal) vs score(B2)
  E-->>W: objective tuples → pick lower; today's items go to the validator
```

## 8. Algorithms and worked examples

### 8.1 Refill decision (BR-032/033/036, M07-D4)

```
D        = amount of this request (gas term 0 in M1)
Shortage = max(0, P_o + D + F − B)
Pref     = max(0, P_o + D + H − B)
Bound    = max(0, D + H − B)                  # contract: balance after refill ≤ amount + target
Cap      = min(SourceCapacity, refill.per_request, refill.daily − used_today.refill)
if Shortage == 0:                 → none
elif Shortage > Bound:            → stop (REFILL_BOUND)        # buffer/other holds exceed target
elif Cap ≥ min(Pref, Bound):      → preferred, amount = min(Pref, Bound)
elif Cap ≥ Shortage:              → shortage,  amount = Shortage   (report TARGET_NOT_REACHED)
else:                             → stop (OVER_REFILL_DAILY, else OVER_REFILL_PER_REQUEST, else SOURCE_INSUFFICIENT)
```

| Example | B | P_o | D | F | H | Shortage | Pref | Bound | Cap | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| UC-02 | 20 | 0 | 100 | 10 | 10 | 90 | 90 | 90 | 2,500 | preferred 90 |
| Domain §3.4 a | 300 | 100 | 400 | 50 | 150 | 250 | 350 | 250 | 350 | preferred **250** (bound caps 350 → 250) |
| Domain §3.4 b | 300 | 100 | 400 | 50 | 150 | 250 | 350 | 250 | 300 | preferred 250 |
| Domain §3.4 c | 300 | 100 | 400 | 50 | 150 | 250 | 350 | 250 | 200 | stop SOURCE_INSUFFICIENT |
| Bound stop | 0 | 300 | 50 | 40 | 60 | 390 | 410 | 110 | 2,500 | stop REFILL_BOUND |

Note on row a: the source document expected 350; with the contract bound (M04-D4) the engine refills 250 and the other held request refills for itself when it is processed. The goldens in ENG-002/ENG-003 use these updated values.

### 8.2 Value of paying on day `p` (M07-D1, D2)

```
discount(p) = floor(amount · discount_bps / 10000)  if discount_deadline_day and p ≤ discount_deadline_day else 0
late(p):
  if p ≤ net_due_day or no late_fee: 0
  fixed:               amount_fee
  percent_per_period:  periods = ceil((p − net_due_day) / period_days)
                       floor(amount · rate_bps · periods / 10000)
  then min(late, cap) if cap is set
value(p) = discount(p) − late(p)
```

**Fee term (FEE-2, added in M03):** when choosing *early* payment for a discount, the optimizer uses `discount(p) − feeInAsset` where `feeInAsset = estimatedPlanFeeWei × reference_eth_price / 1e18` (treasury fee policy; reference price is a labelled setting in M1). If `discount ≤ feeInAsset`, paying early brings no value and the request is scheduled by its due day. Today's fee hold (threshold / budget) is applied by M10 before attestation; days marked held become infeasible for today only.

| Invoice | Terms | Pay day (relative to issue) | Value |
|---|---|---|---|
| 1,000 | 2/10 net 30 | day 8 | +20 |
| 1,000 | 2/10 net 30 | day 12 | 0 |
| 1,000 | net 30, 1.5 %/7 days | day 31 | −15 (1 period) |
| 1,000 | net 30, 1.5 %/7 days | day 45 | −45 (3 periods) |
| 1,000 | net 30, fixed 25, cap 25 | day 60 | −25 |

### 8.3 Baseline B1 — EDF

Sort by `(net_due_day, approved_seq, id)` (the id keeps ties deterministic, M07-D7). For each day of the 30-day rolling horizon from today, take requests in order while: payee known (else `PAYEE_UNKNOWN`) and active that day, per-request cap respected for the amount actually paid that day, i.e. `pay_amount(r, d)` with early or legacy-discount amounts (or exception granted, else `NEEDS_EXCEPTION`), daily pay cap not exceeded (`OVER_DAILY_LIMIT`), refill feasible (§8.1) with the cumulative source drawdown. Unplaced requests roll to the next day, including past their due day; anything not placed in the horizon is `Infeasible` with its first blocking reason. The objective's second term counts only deadlines some schedule could meet: payee known and active by the due day, due day not already past, and no exception needed.

### 8.4 Optimizer B2 — CP-SAT model (M07-D5)

**Variables:** `x[r,d] ∈ {0,1}` request `r` paid on day `d` (d in horizon); `u[r] = 1 − Σ_d x[r,d]` (unscheduled); `ref[r] ∈ [0, Bound_r]` refill amount (int).

**Constraints**
1. `Σ_d x[r,d] ≤ 1`.
2. Cooling: `x[r,d] = 0` if `d < payee_active_day[payee(r)]`.
3. Per-request cap: if `amount_r > pay.per_request` and no exception → `x[r,·] = 0` (reported `NEEDS_EXCEPTION`).
4. Daily pay cap: `Σ_r amount_r · x[r,d] ≤ pay.daily − used_today.pay·[d = today]`.
5. Daily refill cap: `Σ_r ref_r(d) ≤ refill.daily − used_today.refill·[d = today]`, where `ref_r(d)` is the refill attributed to day d.
6. Source: cumulative refills up to day d ≤ `SourceCapacity`.
7. Wallet buffer: for each operational wallet w and day d, `B_w + Σ refills into w (≤ d) − Σ payments from w (≤ d) ≥ F_w`.
8. Refill bound per request: `ref[r] ≤ amount_r + H_w − B_w(at payment)` (linearized with the cumulative balance).

**Objective (lexicographic, solved in stages, M07-D6)**
1. Maximize the number of requests paid by their due day (among those that can be).
2. Maximize total value `Σ value(r,d)·x[r,d]`.
3. Minimize the number of transactions (pays + refills > 0).
4. Tie-break: earlier `approved_seq` first (deterministic secondary key).

Stage *k* adds the optimum of stage *k−1* as a constraint. Each stage gets a share of the time limit (default 5 s total). **Determinism:** `num_workers = 1`, fixed `random_seed`, inputs sorted by id (M07-D7). **Fallback:** status `UNKNOWN`/error/no solution in time ⇒ return EDF with `status = FALLBACK` and log it.

**Implementation notes (ENG-007, `engine/cpsat.py`):** payments are ordered into slots (days non-decreasing, order inside a day free) so wallet balances, the daily pay/refill counters and the source drawdown are exact. `ref[r]` is restricted to the two BR-032 outcomes, the shortage or the bounded top-up to target when the refill caps allow it, which is the oracle's search space, so objectives match it exactly. Inputs whose magnitudes could overflow 64 bits, solver errors, an exhausted `time_limit_seconds` (budget for the whole call, split evenly over the four stages), or a result worse than EDF return the EDF schedule with `FALLBACK`; a stage that stops with a solution that is not proven optimal yields `FEASIBLE`. Optional `fee_in_asset` / `fee_hold_today` implement the fee term of section 8.2. The approval-order tie-break uses exact lexicographic weights and degrades to a linear rank when they would not fit in 64 bits (approval-order dominance is then no longer strict). The slot model has O(N^2) booleans and constraints, so large batches are expected to exhaust the time limit and return the EDF fallback.

**Oracle (tests and benchmarks):** search, with memoized dynamic programming, every assignment of at most 8 requests to a day through the latest due or payee activation day (maximum 5 days) or to the unscheduled set, every same-day payment order, and for each payment both BR-032 refill outcomes (`preferred` top-up or `shortage` only). Refill amounts between those two (for example pre-funding a later request) are not searched. Inputs outside either bound are rejected. The oracle shares EDF's payment feasibility transition and BR-052 scoring helper. Reusable bounded Hypothesis inputs for the oracle and ENG-007 equivalence tests live in `packages/py-core/tests/strategies/financial_engine.py`; the oracle is never called from production paths.

### 8.5 Fingerprint

`normalize(s) = s.strip().casefold()` then remove Unicode whitespace and `-`, `_`, `/`, `.`, `#`. Leading zeros are preserved. `fingerprint = keccak256(abi.encode(normalize(vendor_id), normalize(invoice_no), amount, asset))`, where `amount` is integer base units encoded as `uint256` and `asset` is an EVM `address`. Vectors are shared with the contracts (SC-017) and the web.

### 8.7 Fiat FX safety core (ENG-L02)

`FiatApproval` binds the fiat amount in minor units, the reference `FxRate`, the
maximum stablecoin amount in token base units and the tolerated rate deviation in
basis points. `FxRate` is an exact rational number of stablecoin base units per fiat
minor unit. `FxPolicy` names the configured source, maximum quote age and USD peg
deviation. `FxQuote` supplies that source's observed rate, timestamp and stablecoin
USD price in microdollars per whole token (1,000,000 = $1).

At the execution boundary, the caller obtains a fresh quote and invokes
`propose_fiat_payment`. It rejects a mismatched source/pair, future or stale quote,
rate outside `abs(execution_rate / approved_rate - 1) ≤ tolerance_bps / 10000`,
and `abs(USD price - $1) > depeg_threshold_bps / 10000`. Rational comparison uses
integer cross multiplication. Conversion is `ceil(fiat_minor_amount × quote_rate)`
to token base units. If that exceeds the approved token maximum, the function
raises `FiatPaymentBlocked(APPROVED_MAX_EXCEEDED)` instead of clipping the payment.
The caller must route any block to review, bind the returned token amount to the
approval, and repeat this check immediately before PAY. Wrong argument types raise
`TypeError` and malformed values raise `ValidationError`/`ValueError`;
`FiatPaymentBlocked` is not a `ValueError`, so callers can tell bad input from a review
block. The depeg guard assumes a USD-pegged stablecoin (USDC). Invoice persistence,
approval signing and payment orchestration belong to INV-L04.

### 8.6 Seven-day liquidity forecast

`forecast(snapshot, requests, policy, days=7)` runs the deterministic EDF schedule and
replays its payments and refills in scheduler order. It returns each wallet's end-of-day
balance, days when a wallet is below its buffer, and the refills selected by the same
source-buffer, refill-bound, per-request, and daily-limit rules as scheduling. The
window can be set from 1 to 30 days. Approved obligations that remain unpaid after
their due day are reported as `unpaid_due` (`amount_due`: the payable amount plus any
accrued late fee) and `shortfall_days`, and count against their paying wallet when
deciding buffer hits, so a wallet that cannot cover an upcoming invoice shows up even
though the scheduler never plans that payment. `snapshot.source` must be Safe T; scheduled payments
outside the requested window are listed in `deferred_request_ids`.

## 9. Configuration and defaults

| Parameter | Default | Where |
|---|---|---|
| Horizon cap | 30 days | engine constant (overridable for tests) |
| Midnight cut-over | 30 minutes | engine constant |
| CP-SAT time limit | 5 s per cycle (split across stages) | worker config |
| CP-SAT workers / seed | 1 / 42 | engine constant |
| Oracle limit | N ≤ 8, horizon ≤ 5 | tests |
| Discount rounding | floor | engine |
| Forecast window | 7 days | API query param |

## 10. Security and correctness

| Risk | Control | Proof |
|---|---|---|
| Float rounding on money | `BaseUnits` type rejects floats; CP-SAT is integer-only | type tests; ruff rule banning `float(` in engine |
| LLM-supplied numbers | Engine ignores any amount from AI; AI proposals are reorderings scored by the engine | AGT-009 tests |
| Plan violates a hard rule | Constraints mirror BR-013/022/030/036; validator re-checks; contract enforces | property tests + POL-004 differential |
| Non-determinism (benchmark noise) | 1 worker, fixed seed, sorted inputs | determinism test: same input twice ⇒ same output |
| Solver hang | Time limit + EDF fallback | timeout test |
| Overflow | Python ints unbounded; CP-SAT bounds checked (< 2⁶³) before model build | guard test |

## 11. Failure scenarios

| Failure | Behaviour |
|---|---|
| Invalid terms (negative, dates out of order) | `InvalidTerms`; the request is excluded with reason `TERMS_INVALID` (should not happen: validated at confirmation) |
| Snapshot stale/partial | Engine refuses (`InvalidSnapshot`); validator will BLOCK |
| CP-SAT not installed / crashes | EDF fallback, `status = FALLBACK`, metric + log |
| Everything infeasible | Empty schedule; every request listed in `infeasible` with a reason → review items |

## 12. Test plan

| Level | Content | Ticket |
|---|---|---|
| Golden | Domain §3.4 rows (updated per §8.1), UC-02, value table §8.2 | ENG-002, ENG-003, ENG-005 |
| Property (hypothesis, ≥ 1,000 cases) | no buffer breach, refill ≤ bound and ≤ Cap, schedule respects caps/cooling, CP-SAT never worse than EDF | ENG-004, ENG-007 |
| Oracle equivalence | CP-SAT objective == oracle objective for N ≤ 8 | ENG-012 |
| Determinism | identical input ⇒ identical output | ENG-007 |
| Timeout/fallback | forced tiny limit ⇒ FALLBACK = EDF | ENG-007 |
| Vectors | fingerprint matches Solidity | ENG-009 |
| Forecast | hand-computed balances; refills within source buffer and refill limits | ENG-011 |
| Coverage | ≥ 85 % lines (NFR-MAINT-03) | CI |

## 13. Tickets (order of work)

ENG-001 money & models → ENG-002 calculator → ENG-003 refill decision (with bound) → ENG-004 property tests → ENG-005 terms & value (3 late-fee kinds) → ENG-006 EDF → **ENG-012 exhaustive oracle (new)** → ENG-007 CP-SAT optimizer → ENG-008 scoring & binding constraints → ENG-009 fingerprint → ENG-010 EIP-712 builders → ENG-011 forecast (P2).

## 14. Decisions and open questions

| ID | Decision |
|---|---|
| M07-D1 | Late fees: **fixed**, **percent per started period (simple)**, optional **total cap**. No compounding. |
| M07-D2 | Value = discount captured − late fees. **No cost of capital.** |
| M07-D3 | **Rolling horizon** in UTC days, up to 30 days; only today's items execute; 30-minute cut-over before UTC midnight. |
| M07-D4 | Refill amount is capped by the contract bound `amount + target − balance`; if even the Shortage exceeds it → STOP `REFILL_BOUND`. |
| M07-D5 | Optimizer: **Google OR-Tools CP-SAT**, behind a `Solver` interface (ADR-015). |
| M07-D6 | Lexicographic objective solved in stages: deadlines met → value → transaction count → approval order. |
| M07-D7 | Deterministic solving: 1 worker, fixed seed, sorted inputs. |
| M07-D8 | Exhaustive **oracle** solver (N ≤ 8) used only in tests to prove optimality. |
| M07-D9 | Requests above the per-request cap without an Owner grant are excluded and reported `NEEDS_EXCEPTION`; the scheduler also reports the value they would add if granted (input for the AI exception draft). |
| M07-D10 | Gas is a cost in the value of early payment (FEE-2); an early payment whose discount does not exceed the fee is not preferred. |

| Open | Question | Owner |
|---|---|---|
| M07-Q1 | Should incoming receivables (future inflows) enter the forecast? (Later: needs an AR data source) | Product, Later |

## 15. v0.3 changes (ADR-019) — these supersede earlier sections where they differ

**Liquidity position.** `Snapshot` gains `safe_usdc`, `a_usdc`, `pool_available`, `supply_rate_bps`, `borrow_rate_bps`, `health_factor` (when debt exists), `debt`.

```
PaymentReserve       = Σ pay_amount(r) for approved, unpaid requests with due day ≤ today + 30
RequiredSafeReserve  = PaymentReserve + safe_floor + DebtServiceReserve + ExecutionHolds
AvailableForSupply   = max(0, safe_usdc − RequiredSafeReserve)
AccessibleLiquidity  = safe_usdc + min(a_usdc, pool_available)
```
`pay_amount(r)` = early amount if the schedule pays by `earlyPayBy`, else the standard amount.

**decide_liquidity(snapshot, schedule) → NONE | SUPPLY x | WITHDRAW y** (one per cycle):
- deficit `d = RequiredSafeReserve − safe_usdc > 0` → `WITHDRAW min(a_usdc, pool_available, ceil(d × 1.05))`; if still short → `INSUFFICIENT_LIQUIDITY` and a borrow proposal (F-069).
- else if `AvailableForSupply ≥ min_supply` → `SUPPLY min(AvailableForSupply, supply caps remaining)`.
- else NONE. Inside a request plan a WITHDRAW step is placed before REFILL when Safe T cannot fund the refill without breaking the reserve.

Example: Safe 6,000, aUSDC 0, floor 1,000, approved unpaid 2,000 → Required 3,000, Available 3,000 ≥ 500 → SUPPLY 3,000 (D2). A new invoice of 2,500 is approved → Required 5,500, Safe 3,000 → deficit 2,500 → WITHDRAW 2,625 (D3).

**Value of paying on day p (replaces §8.2's discount term):** `saving(p) = amount − pay_amount(p)` (exact, from the approval) minus late fees; early payment is preferred only if `saving − fee_in_asset − lost_supply_interest > 0`, where `lost_supply_interest = floor(pay_amount × supply_rate_bps × days_earlier / (10000 × 365))`. The CP-SAT objective keeps its order (deadlines → value → transactions → approval order) with value now = savings − late fees − gas − lost interest + expected supply interest of the cash kept supplied.

**Borrow proposal (F-069):** `propose_borrow(snapshot, deficit, until_day)` returns a `BorrowProposal` with amount, borrow cost to repayment `= amount × borrow_rate_bps × days / (10000 × 365)`, estimated supply interest lost by withdrawing the same amount, and the health factor before/after borrowing. Health factor after borrowing is estimated as `health_factor_before × debt / (debt + amount)` when an existing debt position is present; otherwise it stays unknown. The reason always states whether borrowing costs less or more than withdrawing, then adds a note when the health factor after borrowing is unknown, below 1.0 (risk review required), or below 1.1 (advisory liquidation-risk warning; it changes no decision). The proposal is a separate analysis model and cannot be inserted into `Schedule.items`; it never creates a transaction. Borrow execution requires a separate owner authorization (BR-044).

**Tickets:** ENG-013 reserve and liquidity decision, ENG-014 borrow proposal; ENG-001/005/007/011 revised.
