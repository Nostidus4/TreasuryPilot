# Synthetic planner scenarios (DOM-005 / #177)

40 UTF-8 YAML cases: four per M20/v0.3 family. Dev contains 28 cases in seven
families; heldout contains 12 in cooling-payee, late-fee-triage and
new-obligation-withdraw. Families do not overlap across splits. All amounts are
integer base-unit strings, dates are UTC ISO strings, addresses are synthetic.

## Ground truth and model

`author.py` imports no production engine. It enumerates all ordered schedules
within 30 UTC days for at most two requests, conserving T/O1 cash and applying
current-day usage, daily resets, caps, cooling, exact early amounts, request-bound
refills, source/destination floors and already-granted exceptions. No inflows,
new approval/exception, external priority weight, gas fee or price changes are
assumed. Percentage late fees use integer floors, ceiling period count and caps;
early-option value includes forgone simple interest when the input rate is nonzero.

Complete service of approved requests is required whenever a complete feasible
schedule exists. If it does not, maximize completed requests; then minimize
missed non-past deadlines, maximize discounts minus modeled fees/interest,
minimize transactions and tie-break by day/approval sequence/request ID. This
small reference model is not a production optimizer or a full ADR-019 cost model.
It does not assign economic weights to qualitative priority notes. Already-late
requests must not be omitted merely to report zero fees.

`expected` stores schedule, blockers, value, refill trace, final balances and
transaction/deadline counts. Liquidity families have `liquidity` inputs and
`expected_liquidity`: static floor plus approved payment reserve, 500-token
minSupply, fixed supply caps, or bounded deficit + 5% withdrawal. Scheduling
uses the post-liquidity-action T balance, and insufficiency remains blocked; a borrow
proposal is not a new executable grant. `expected_b0` is an independently replayed
**EDF/no-lending reference**: due/approval/ID order, retry on future days. Its values
are synthetic fixture expectations, not measured runtime or AI benchmark results.

Required expected fields follow M20. Extensions `approved_seq`, `early_amount`,
`early_pay_by`, `exception_granted`, `rates`, `assumptions`, `liquidity`,
`expected_liquidity` and `expected_b0` make v0.3 options and modelling assumptions
explicit. Each family includes a boundary/blocking variant, not only easy success.

Run authoring with `uv run python evals/scenarios/author.py`. It regenerates the
committed cases deterministically; label changes require review. Numeric examples
are synthetic, not recommendations for live treasury policy.

## Exposure and review

These cases were authored by the same AI assistant and are public. `heldout` is
a family partition for a harness, **not a claim of independent authorship or an
unseen test set**. A second advisor must check labels, particularly economic
assumptions. For a defensible AI benchmark, independently author/freeze a separate
unexposed holdout, deny tuning access and record access history. Do not copy these
answers into model prompts and then report held-out performance.

The simple-refill, idle-cash and already-granted/blocked single-request families
provide more than five cases where EDF can attain the reference objective; no
AI benefit is assumed. Ground-truth review and actual B0/B1/B2 measurements remain
pending. Authoring these labels does not complete AGT-014.
