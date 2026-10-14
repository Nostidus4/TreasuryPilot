"""Author synthetic M20 scenarios with a small independent exhaustive oracle.

The oracle imports no production engine. Its model and tie rules are documented
in README.md; labels are review candidates, not evidence of independent review.
"""

from __future__ import annotations

import itertools
import json
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
AS_OF = date(2026, 10, 14)
UNIT = 1_000_000
FAMILIES = (
    "simple-refill",
    "discount-vs-deadline",
    "daily-cap-spill",
    "source-shortage",
    "cooling-payee",
    "over-cap-exception",
    "late-fee-triage",
    "ambiguous-priority",
    "idle-cash-supply",
    "new-obligation-withdraw",
)
HELDOUT = {"cooling-payee", "late-fee-triage", "new-obligation-withdraw"}


def money(tokens: int) -> str:
    return str(tokens * UNIT)


def iso(offset: int) -> str:
    return (AS_OF + timedelta(days=offset)).isoformat()


def offset(day: str) -> int:
    return (date.fromisoformat(day) - AS_OF).days


def request(identifier: str, amount: int, due: int, payee: str = "vendor-a") -> dict:
    return {
        "id": identifier,
        "payee": payee,
        "wallet": "O1",
        "amount": money(amount),
        "due": iso(due),
        "approved_seq": int(identifier[1:]),
        "terms": {},
    }


def pay_amount(r: dict, day: int) -> int:
    if r.get("early_amount") is not None and day <= offset(r["early_pay_by"]):
        return int(r["early_amount"])
    return int(r["amount"])


def value(r: dict, day: int, rate: int) -> int:
    amount = pay_amount(r, day)
    due = offset(r["due"])
    saving = int(r["amount"]) - amount
    result = saving
    if saving:
        result -= amount * rate * max(0, due - day) // (10_000 * 365)
    late = r["terms"].get("late_fee")
    if late and day > due:
        if late["type"] == "fixed":
            fee = int(late["amount"])
        else:
            periods = (day - due + late["period_days"] - 1) // late["period_days"]
            fee = int(r["amount"]) * late["rate_bps"] * periods // 10_000
        result -= min(fee, int(late.get("cap", str(fee))))
    return result


def replay(s: dict, steps: list[tuple[int, dict]]) -> dict | None:
    t = s["treasury"]
    balances = {key: int(amount) for key, amount in t["balances"].items()}
    floors = {key: int(amount) for key, amount in t["buffers"].items()}
    targets = {key: int(amount) for key, amount in t["targets"].items()}
    active = {p["id"]: offset(p["active_from"]) for p in s["payees"]}
    used = {0: {key: int(amount) for key, amount in t["used_today"].items()}}
    refills, total_value, txs, missed = [], 0, 0, 0
    for day, r in steps:
        if not 0 <= day < 30 or day < active.get(r["payee"], 999):
            return None
        amount = pay_amount(r, day)
        limits = t["limits"]
        daily = used.setdefault(day, {"pay": 0, "refill": 0})
        if amount > int(limits["pay"]["per_request"]) and not r.get("exception_granted"):
            return None
        if daily["pay"] + amount > int(limits["pay"]["daily"]):
            return None
        wallet = r["wallet"]
        shortage = max(0, amount + floors[wallet] - balances[wallet])
        bound = max(0, int(r["amount"]) + targets[wallet] - balances[wallet])
        preferred = max(0, amount + targets[wallet] - balances[wallet])
        refill_cap = min(
            balances["T"] - floors["T"],
            int(limits["refill"]["per_request"]),
            int(limits["refill"]["daily"]) - daily["refill"],
        )
        if shortage > bound or shortage > refill_cap:
            return None
        refill = (
            0
            if shortage == 0
            else min(preferred, bound)
            if refill_cap >= min(preferred, bound)
            else shortage
        )
        balances["T"] -= refill
        balances[wallet] += refill - amount
        daily["pay"] += amount
        daily["refill"] += refill
        if refill:
            refills.append({"request": r["id"], "day": iso(day), "amount": str(refill)})
        total_value += value(r, day, s["rates"]["supply_rate_bps"])
        txs += 1 + int(refill > 0)
        missed += int(offset(r["due"]) >= 0 and day > offset(r["due"]))
    # Unserved requests whose deadline has not passed are missed deadlines too, so
    # the metric is comparable between planners that omit different requests.
    served = {r["id"] for _, r in steps}
    missed += sum(1 for r in s["requests"] if r["id"] not in served and offset(r["due"]) >= 0)
    return {
        "value": str(total_value),
        "transaction_count": txs,
        "missed_deadlines": missed,
        "refills": refills,
        "balances_after": {k: str(v) for k, v in balances.items()},
    }


def optimum(s: dict) -> dict:
    requests = s["requests"]
    best, result, best_steps = None, None, []
    # Includes omission only when no complete feasible schedule exists. Completion
    # is compared before deadline/value/tx, preventing a late-fee skip from winning.
    for order in itertools.permutations(requests):
        for days in itertools.product(range(-1, 30), repeat=len(requests)):
            steps = [(d, r) for d, r in zip(days, order, strict=True) if d >= 0]
            if any(a[0] > b[0] for a, b in itertools.pairwise(steps)):
                continue
            candidate = replay(s, steps)
            if candidate is None:
                continue
            tie = tuple((d, r["approved_seq"], r["id"]) for d, r in steps)
            score = (
                len(requests) - len(steps),
                candidate["missed_deadlines"],
                -int(candidate["value"]),
                candidate["transaction_count"],
                tie,
            )
            if best is None or score < best:
                best, result, best_steps = score, candidate, steps
    assert result is not None
    schedule: dict[str, list[str]] = {}
    for day, r in best_steps:
        schedule.setdefault(iso(day), []).append(r["id"])
    selected = {r["id"] for _, r in best_steps}
    result.update(
        schedule=schedule,
        violations=0,
        infeasible=[
            {
                "id": r["id"],
                "reason": "NEEDS_EXCEPTION"
                if int(r["amount"]) > int(s["treasury"]["limits"]["pay"]["per_request"])
                and not r.get("exception_granted")
                else "SOURCE_INSUFFICIENT",
            }
            for r in requests
            if r["id"] not in selected
        ],
    )
    result["explanation"] = (
        "Independent enumeration of ordered feasible 30-day schedules. Maximize completion, "
        "then minimize missed deadlines, maximize modeled value, minimize transactions; "
        "ties use day/approval sequence/request ID. No future inflows or AI priority weight."
    )
    return result


def edf(s: dict) -> dict:
    remaining = sorted(s["requests"], key=lambda r: (r["due"], r["approved_seq"], r["id"]))
    steps: list[tuple[int, dict]] = []
    for day in range(30):
        later = []
        for r in remaining:
            if replay(s, steps + [(day, r)]) is None:
                later.append(r)
            else:
                steps.append((day, r))
        remaining = later
    result = replay(s, steps)
    assert result is not None
    schedule: dict[str, list[str]] = {}
    for day, r in steps:
        schedule.setdefault(iso(day), []).append(r["id"])
    result.update(
        schedule=schedule,
        violations=0,
        infeasible=[
            {
                "id": r["id"],
                "reason": "NEEDS_EXCEPTION"
                if int(r["amount"]) > int(s["treasury"]["limits"]["pay"]["per_request"])
                and not r.get("exception_granted")
                else "SOURCE_INSUFFICIENT",
            }
            for r in remaining
        ],
        liquidity_action="NONE",
        explanation="Independent EDF reference; idle cash and no lending actions.",
    )
    return result


def build(family: str, variant: int, identifier: str) -> dict:
    t = {
        "stablecoin_decimals": 6,
        "balances": {"T": money(10_000), "O1": money(20)},
        "buffers": {"T": money(1_000), "O1": money(10)},
        "targets": {"O1": money(150)},
        "limits": {
            "pay": {"per_request": money(2_000), "daily": money(10_000)},
            "refill": {"per_request": money(2_500), "daily": money(12_000)},
        },
        "used_today": {"pay": "0", "refill": "0"},
    }
    s = {
        "id": identifier,
        "family": family,
        "as_of": AS_OF.isoformat(),
        "treasury": t,
        "rates": {"supply_rate_bps": 0, "borrow_rate_bps": 800},
        "payees": [
            {"id": "vendor-a", "address": "0x" + "11" * 20, "active_from": iso(-10)},
            {"id": "vendor-b", "address": "0x" + "22" * 20, "active_from": iso(-10)},
        ],
        "requests": [],
        "assumptions": {
            "synthetic": True,
            "horizon_days": 30,
            "future_inflows": [],
            "estimated_execution_fee": "0",
            "other_holds": "0",
            "all_requests_human_approved": True,
            "review_status": "pending_second_person",
            "authoring_exposure": "AI-authored and public; not an unseen evaluation set",
        },
    }
    r1, r2 = request("r1", 100 + variant * 50, 2), request("r2", 200 + variant * 50, 4, "vendor-b")
    if family == "simple-refill":
        if variant == 1:
            t["balances"]["O1"] = money(500)  # no shortage: never refill only to target
        elif variant == 2:
            t["balances"]["T"] = money(1_200)  # minimum fits; preferred does not
        elif variant == 3:
            t["limits"]["refill"].update(daily=money(400), per_request=money(400))
            t["used_today"]["refill"] = money(380)  # next-day reset
        s["requests"] = [r1]
    elif family == "discount-vs-deadline":
        r1["due"], r2["due"] = iso(0), iso(3)
        r2.update(early_amount=str(int(r2["amount"]) * 9_000 // 10_000), early_pay_by=iso(0))
        r2["terms"] = {"discount_bps": 1_000, "discount_deadline": iso(0)}
        s["rates"]["supply_rate_bps"] = 500 if variant >= 2 else 0
        # Cap admits r1 or discounted r2 on the discount day, never both; r1 is
        # due that day. Face-value r2 stays within per_request (no exception).
        t["limits"]["pay"].update(daily=r2["amount"], per_request=r2["amount"])
        s["requests"] = [r1, r2]
    elif family == "daily-cap-spill":
        r1["due"], r2["due"] = iso(0), iso(1)
        t["limits"]["pay"].update(
            daily=money(350 + variant * 50), per_request=money(350 + variant * 50)
        )
        t["used_today"]["pay"] = money(250 + variant * 50)
        s["requests"] = [r1, r2]
    elif family == "source-shortage":
        t["balances"]["T"] = money(1_050 + variant * 10)
        s["requests"] = [r1]  # permanent cash shortfall: no partial refill/payment
    elif family == "cooling-payee":
        s["payees"][1]["active_from"] = iso(variant + 1)
        r2["due"] = iso(variant)
        s["requests"] = [r1, r2]
    elif family == "over-cap-exception":
        r1["amount"] = money(2_100 + variant * 100)
        if variant % 2:
            r1["exception_granted"] = True  # pre-existing exact owner grant, not auto-granted
        s["requests"] = [r1]
    elif family == "late-fee-triage":
        r1["due"], r2["due"] = iso(-1), iso(-2)
        r1["terms"] = {
            "late_fee": {"type": "percent_per_period", "rate_bps": 100, "period_days": 1}
        }
        r2["terms"] = {
            "late_fee": {
                "type": "percent_per_period",
                "rate_bps": 300,
                "period_days": 1,
                "cap": money(50),
            }
        }
        if variant == 1:
            r2["terms"]["late_fee"]["period_days"] = 7
        elif variant == 2:
            r2["terms"]["late_fee"]["cap"] = money(2)
        elif variant == 3:
            r1["terms"]["late_fee"] = {"type": "fixed", "amount": money(5)}
        t["limits"]["pay"].update(
            daily=money(350 + variant * 50), per_request=money(350 + variant * 50)
        )
        s["requests"] = [r1, r2]
    elif family == "ambiguous-priority":
        r1["due"], r2["due"] = iso(1), iso(1)
        r1["terms"]["priority_note"] = "Critical vendor; please prioritize."
        r2["terms"]["priority_note"] = "Urgent: standard service invoice."
        t["limits"]["pay"].update(
            daily=money(350 + variant * 50), per_request=money(350 + variant * 50)
        )
        s["requests"] = [r1, r2]  # text conveys no new permission/numeric objective
    else:
        s["requests"] = [] if family == "idle-cash-supply" and variant < 2 else [r1]
        t["balances"]["T"] = (
            money(2_000 + variant * 500) if family == "idle-cash-supply" else money(1_000)
        )
        s["liquidity"] = {
            "safe_usdc": t["balances"]["T"],
            "a_usdc": money(2_000),
            "pool_available": money(2_000 if variant != 3 else 50),
            "min_supply": money(500),
            "debt_service_reserve": "0",
            "execution_holds": "0",
            "supply": {"per_request": money(5_000), "daily": money(20_000)},
        }
        # Liquidity action is evaluated before scheduling. Withdrawal adds the
        # bounded cash amount to T; it never creates a borrow grant.
        payment_reserve = sum(int(r["amount"]) for r in s["requests"])
        required = payment_reserve + int(t["buffers"]["T"])
        safe = int(t["balances"]["T"])
        deficit = max(0, required - safe)
        withdrawal = min(
            (deficit * 105 + 99) // 100,
            int(s["liquidity"]["a_usdc"]),
            int(s["liquidity"]["pool_available"]),
        )
        available = max(0, safe - required)
        kind = (
            "INSUFFICIENT_LIQUIDITY"
            if withdrawal < deficit
            else "WITHDRAW"
            if deficit
            else "SUPPLY"
            if available >= 500 * UNIT
            else "NONE"
        )
        supply_cap = min(
            int(s["liquidity"]["supply"]["per_request"]), int(s["liquidity"]["supply"]["daily"])
        )
        amount = withdrawal if deficit else min(available, supply_cap) if kind == "SUPPLY" else 0
        s["assumptions"]["liquidity_model"] = (
            "Withdrawal is capped by a_usdc and pool_available, and a partial withdrawal is "
            "still executed when it cannot cover the deficit (INSUFFICIENT_LIQUIDITY; requests "
            "stay blocked, e.g. sc-112). Supply is capped by supply.per_request/daily; "
            "pool_available is a withdrawal-side limit only and does not bound SUPPLY."
        )
        s["expected_liquidity"] = {
            "kind": kind,
            "amount": str(amount),
            "shortfall": str(max(0, deficit - withdrawal)),
            "payment_reserve": str(payment_reserve),
            "required_safe_reserve": str(required),
        }
    # Real mandate configuration requires per-request <= daily. Each family must
    # choose deployable limits explicitly; nothing is clamped silently.
    for name, limits in t["limits"].items():
        assert int(limits["per_request"]) <= int(limits["daily"]), (identifier, name)
    oracle_input = json.loads(json.dumps(s))
    if s.get("expected_liquidity", {}).get("kind") in {"WITHDRAW", "INSUFFICIENT_LIQUIDITY"}:
        oracle_input["treasury"]["balances"]["T"] = str(
            int(t["balances"]["T"]) + int(s["expected_liquidity"]["amount"])
        )
    elif s.get("expected_liquidity", {}).get("kind") == "SUPPLY":
        oracle_input["treasury"]["balances"]["T"] = str(
            int(t["balances"]["T"]) - int(s["expected_liquidity"]["amount"])
        )
    s["expected"] = optimum(oracle_input)
    # B0 shares PAY constraints but leaves cash idle and never withdraws/supplies.
    s["expected_b0"] = edf(s)
    return s


def main() -> None:
    dev_id, held_id = 1, 101
    for family in FAMILIES:
        split = "heldout" if family in HELDOUT else "dev"
        directory = ROOT / split
        directory.mkdir(exist_ok=True)
        for variant in range(4):
            number = held_id if split == "heldout" else dev_id
            identifier = f"sc-{number:03d}"
            if split == "heldout":
                held_id += 1
            else:
                dev_id += 1
            scenario = build(family, variant, identifier)
            (directory / f"{identifier}.yaml").write_text(
                yaml.safe_dump(scenario, sort_keys=False, allow_unicode=True), encoding="utf-8"
            )
    print("Authored 40 scenarios: 28 dev, 12 heldout, 10 disjoint families")


if __name__ == "__main__":
    main()
