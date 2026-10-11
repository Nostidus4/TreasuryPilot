"""Revisions from the M07 (financial engine) grilling round, 2026-10-11. Applied after r01_m04."""
from ._base import TICKETS, T

def _rev(tid, **kw):
    t = next(x for x in TICKETS if x["id"] == tid)
    for k, v in kw.items():
        if k in ("scope", "ac", "tests"): v = [s.strip() for s in v.split(";") if s.strip()]
        if k == "deps": v = v.split()
        t[k] = v

_rev("ENG-001",
  scope="BaseUnits type (non-negative int) with parse/format using decimals;frozen Pydantic models per docs/modules/financial-engine §4: Asset, LateFee, PaymentTerms, WalletState, Limits, PolicyView, Snapshot, ApprovedRequest, RefillDecision, ScheduledItem, Infeasible, Schedule;UTC day helpers (day number, 30-minute midnight cut-over, M07-D3);JSON serialization of amounts as decimal strings")
_rev("ENG-002",
  scope="Functions available, funding_deficit, shortage, preferred_refill, source_capacity, refill_bound (amount + target − balance), cap per docs/modules/financial-engine §6;gas term fixed at 0 in M1;golden tests from §8.1",
  ac="Domain §3.4 example: Shortage 250, PreferredRefill 350, Bound 250;UC-02 example: Shortage, PreferredRefill and Bound all equal 90;All arithmetic is integer")
_rev("ENG-003", refs="BR-031, BR-033, BR-036, FR-404",
  scope="decide_refill per docs/modules/financial-engine §8.1 returning none / preferred / shortage / stop with a reason code;refill amount = min(PreferredRefill, Bound) (M07-D4);stop REFILL_BOUND when Shortage > Bound;stop SOURCE_INSUFFICIENT or OVER_REFILL_DAILY when Cap < Shortage",
  ac="The five rows of the §8.1 table return exactly the documented decision and amount;No refill is proposed only to reach target;The refill amount never exceeds the contract bound (BR-036)",
  notes="M07-D4: the other held requests in the same wallet refill for themselves when they are processed. Reason codes come from POL-001.")
_rev("ENG-004",
  scope="hypothesis strategies for wallet states, policies and requests;properties: post-plan balances ≥ buffer, refill ≤ Cap, refill ≤ Bound, no negative amounts, determinism (same input twice ⇒ identical output)")
_rev("ENG-005", refs="BR-052, BR-075, M07-D1, M07-D2",
  scope="PaymentTerms with net due day, discount bps and deadline, optional LateFee;LateFee kinds: fixed, percent per started period (simple), optional total cap (M07-D1);request_value(req, pay_day) = floor discount − late fee (M07-D2, no cost of capital);validation of ranges and day order",
  ac="Every row of docs/modules/financial-engine §8.2 returns the documented value;A percent late fee accrues per started period and stops at the cap;Invalid terms raise InvalidTerms",
  notes="Percentages as basis points (integers). Discounts round down.")
_rev("ENG-006",
  scope="schedule_edf(requests, snapshot, policy) over the rolling horizon (≤ 30 UTC days, M07-D3);order by (net_due_day, approved_seq);per-day pay and refill caps, source drawdown, payee cooling, NEEDS_EXCEPTION for over-cap requests;infeasible items with the first blocking reason",
  ac="Requests are ordered by due day then approval order;Items blocked by cooling payee, daily cap, source capacity, refill bound or per-request cap are reported with the matching reason;Output is a Schedule with solver = EDF")
_rev("ENG-007", title="Implement the terms-aware scheduler with OR-Tools CP-SAT",
  refs="BR-052, FR-405, ADR-015, M07-D5, M07-D6, M07-D7", deps="ENG-006 ENG-012",
  scope="Solver interface (EDF, CPSAT, ORACLE implementations);CP-SAT model per docs/modules/financial-engine §8.4 (x[r,d], refill vars, constraints 1–8);lexicographic objective solved in stages (deadlines → value → tx count → approval order);determinism: 1 worker, fixed seed, sorted inputs;5 s time limit split across stages;EDF fallback with status FALLBACK;bounds guard (< 2^63) before model build;add ortools to py-core (pinned)",
  oos="AI proposals (AGT-008). Oi→Oj refills (ENG-L01).",
  notes="ADR-015. Split into two PRs (model + staged objective) if it exceeds 2 days.",
  ac="CP-SAT objective equals the oracle objective on all generated cases with N ≤ 8;It never schedules an item that the validator would block;It is never worse than EDF on the objective;Same input twice gives byte-identical output;A forced 1 ms limit returns the EDF schedule with status FALLBACK",
  tests="Unit: hand-computed optimum cases; property: oracle equivalence, never worse than EDF, determinism; timeout fallback")
_rev("ENG-008",
  scope="score(plan, requests, snapshot, policy) → (violations, missed feasible deadlines, −value, tx count);binding_constraints(plan) → list (daily pay cap, daily refill cap, buffer, source capacity, refill bound, cooling, deadline) with the binding numbers;value lost by NEEDS_EXCEPTION items if granted (M07-D9);comparison helper used for AI proposals")
_rev("ENG-010", title="Build EIP-712 typed data for payment approvals and attestations",
  scope="Builders for PaymentApproval (11 fields, docs/modules/contracts §6.1) and the plan attestation struct;verify_signature helpers including ERC-1271 call hook;tests against the golden vectors from SC-017",
  notes="M04-D3: exceptions and duplicate overrides are Safe governance transactions, not EIP-712 structs. Use eth-account. Never sign JSON directly.")
_rev("ENG-011",
  scope="forecast(snapshot, requests, policy, days=7) → daily projected balances per wallet, buffer-hit days, suggested refills within limits and the refill bound;approved obligations only, drafts optional behind a flag")

T("ENG-012","Implement the exhaustive oracle scheduler for tests","M1","P0","S","F-052, F-092","BR-052, ADR-015, M07-D8","ENG-006",
  "A brute-force solver that proves the CP-SAT scheduler returns the true optimum on small cases.",
  "schedule_oracle(requests, snapshot, policy) enumerating every day assignment for N ≤ 8 and horizon ≤ 5;same constraint checks and score() as the other solvers;hypothesis generator of small instances shared with ENG-007",
  "Use in production paths (tests and the benchmark only).",
  "Raises if N > 8 or horizon > 5. Shares the feasibility checker with EDF so all three solvers agree on what is feasible.",
  "On hand-computed cases it returns the known optimum;It refuses inputs above its limits;It runs 1,000 generated cases in under 60 s",
  "Unit: optimum cases; generator smoke test")
