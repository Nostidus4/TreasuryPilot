"""Load `evals/scenarios` and turn each case into engine inputs.

Only the *input* sections of a case become engine objects or prompt material. The `expected*`
sections (ground truth, M09-D14) are kept apart in `Scenario.ground_truth` and are read only by
scoring code, never by anything that builds a prompt or a tool result.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from treasurypilot_core.domain import (
    ApprovedRequest,
    LateFee,
    Limits,
    LiquidityPolicy,
    PaymentTerms,
    PolicyView,
    Snapshot,
    WalletState,
)
from treasurypilot_core.money import BaseUnits
from treasurypilot_worker.agent.plan_proposer import needs_full_proposal

SPLITS = ("dev", "heldout")
_EPOCH = date(1970, 1, 1)
_GROUND_TRUTH_KEYS = ("expected", "expected_b0", "expected_liquidity")
_INPUT_KEYS = ("treasury", "rates", "payees", "requests", "liquidity", "as_of")


class ScenarioError(ValueError):
    """A scenario file cannot be mapped to engine inputs."""


def day_number(value: str | date) -> int:
    """UTC calendar day number (days since 1970-01-01)."""

    parsed = date.fromisoformat(value) if isinstance(value, str) else value
    return (parsed - _EPOCH).days


@dataclass(frozen=True)
class Scenario:
    id: str
    split: str
    family: str
    as_of: date
    horizon_days: int
    requests: tuple[ApprovedRequest, ...]
    snapshot: Snapshot
    policy: PolicyView
    liquidity: LiquidityPolicy
    has_liquidity_block: bool
    inputs_sha256: str  # digest of the input sections only; recordings are bound to it
    ground_truth: dict[str, Any]


def _money(value: object) -> BaseUnits:
    return BaseUnits(int(str(value)))


def _limits(raw: dict[str, Any]) -> Limits:
    return Limits(per_request=_money(raw["per_request"]), daily=_money(raw["daily"]))


def _late_fee(raw: dict[str, Any]) -> LateFee:
    if raw["type"] == "fixed":
        return LateFee(kind="fixed", amount=_money(raw["amount"]))
    return LateFee(
        kind="percent_per_period",
        rate_bps=raw["rate_bps"],
        period_days=raw["period_days"],
        cap=_money(raw["cap"]) if "cap" in raw else None,
    )


def _request(raw: dict[str, Any]) -> ApprovedRequest:
    terms = raw["terms"]
    parsed = PaymentTerms(
        net_due_day=day_number(raw["due"]),
        discount_bps=terms.get("discount_bps", 0),
        discount_deadline_day=(
            day_number(terms["discount_deadline"]) if "discount_deadline" in terms else None
        ),
        late_fee=_late_fee(terms["late_fee"]) if "late_fee" in terms else None,
        priority_note=terms.get("priority_note"),
    )
    early_amount = _money(raw["early_amount"]) if "early_amount" in raw else None
    early_pay_by = day_number(raw["early_pay_by"]) if "early_pay_by" in raw else None
    return ApprovedRequest(
        id=raw["id"],
        paying_wallet=raw["wallet"],
        payee=raw["payee"],
        amount=_money(raw["amount"]),
        approved_seq=raw["approved_seq"],
        terms=parsed,
        exception_granted=bool(raw.get("exception_granted", False)),
        early_amount=early_amount,
        early_pay_by=early_pay_by,
    )


def _wallet(name: str, treasury: dict[str, Any]) -> WalletState:
    balance = _money(treasury["balances"][name])
    buffer = _money(treasury["buffers"][name])
    target = _money(treasury["targets"].get(name, max(int(balance), int(buffer))))
    return WalletState(address=name, balance=balance, buffer=buffer, target=target)


def _snapshot(raw: dict[str, Any]) -> Snapshot:
    treasury, liquidity = raw["treasury"], raw.get("liquidity")
    source = _wallet("T", treasury)
    zero = BaseUnits(0)
    return Snapshot(
        day=day_number(raw["as_of"]),
        source=source,
        operational={n: _wallet(n, treasury) for n in treasury["balances"] if n != "T"},
        used_today={k: _money(v) for k, v in treasury["used_today"].items()},
        payee_active_day={p["id"]: day_number(p["active_from"]) for p in raw["payees"]},
        safe_usdc=_money(liquidity["safe_usdc"]) if liquidity else source.balance,
        a_usdc=_money(liquidity["a_usdc"]) if liquidity else zero,
        pool_available=_money(liquidity["pool_available"]) if liquidity else zero,
        supply_rate_bps=raw["rates"]["supply_rate_bps"],
        borrow_rate_bps=raw["rates"]["borrow_rate_bps"],
        debt=zero,
    )


def _liquidity_policy(raw: dict[str, Any]) -> LiquidityPolicy:
    liquidity = raw.get("liquidity")
    if liquidity is None:
        # No Aave position in this case: nothing can be supplied or withdrawn.
        zero = BaseUnits(0)
        return LiquidityPolicy(supply=Limits(per_request=zero, daily=zero), min_supply=zero)
    return LiquidityPolicy(
        supply=_limits(liquidity["supply"]),
        min_supply=_money(liquidity["min_supply"]),
        debt_service_reserve=_money(liquidity["debt_service_reserve"]),
        execution_holds=_money(liquidity["execution_holds"]),
    )


def to_scenario(raw: dict[str, Any], split: str) -> Scenario:
    try:
        treasury = raw["treasury"]
        if treasury["stablecoin_decimals"] != 6:
            raise ScenarioError(f"{raw['id']}: only six-decimal assets are supported")
        policy = PolicyView(
            pay=_limits(treasury["limits"]["pay"]),
            refill=_limits(treasury["limits"]["refill"]),
            cooling_seconds=0,  # a cooling payee is modelled by its active_from day
        )
        inputs = {key: raw[key] for key in _INPUT_KEYS if key in raw}
        digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        return Scenario(
            id=raw["id"],
            split=split,
            family=raw["family"],
            as_of=date.fromisoformat(raw["as_of"]),
            horizon_days=int(raw["assumptions"]["horizon_days"]),
            requests=tuple(_request(r) for r in raw["requests"]),
            snapshot=_snapshot(raw),
            policy=policy,
            liquidity=_liquidity_policy(raw),
            has_liquidity_block="liquidity" in raw,
            inputs_sha256=digest,
            ground_truth={k: raw[k] for k in _GROUND_TRUTH_KEYS if k in raw},
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, ScenarioError):
            raise
        raise ScenarioError(f"{raw.get('id', '?')}: cannot map scenario ({error!r})") from error


def proposal_needed(scenario: Scenario) -> bool:
    """The production trigger rule (M09-D6): otherwise the deterministic plan is only explained."""

    terms_matter = any(
        r.terms.discount_bps
        or r.terms.late_fee is not None
        or r.terms.priority_note
        or r.early_amount is not None
        for r in scenario.requests
    )
    return needs_full_proposal(
        eligible_requests=len(scenario.requests), terms_or_deferrals_matter=bool(terms_matter)
    )


def load_scenarios(root: Path, split: str = "all") -> list[Scenario]:
    """Scenarios of one split (or both), ordered by id."""

    names = SPLITS if split == "all" else (split,)
    if any(name not in SPLITS for name in names):
        raise ScenarioError(f"unknown split {split!r}")
    loaded = [
        to_scenario(yaml.safe_load(path.read_text(encoding="utf-8")), name)
        for name in names
        for path in sorted((root / name).glob("*.yaml"))
    ]
    if not loaded:
        raise ScenarioError(f"no scenarios under {root}")
    return sorted(loaded, key=lambda s: s.id)
