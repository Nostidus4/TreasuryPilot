"""Validate committed synthetic datasets; no LLM calls or chain transactions."""

from __future__ import annotations

import hashlib
import importlib.util
import re
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
AMOUNT = re.compile(r"0|[1-9][0-9]*")
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def units(value: object) -> None:
    require(
        isinstance(value, str) and AMOUNT.fullmatch(value) is not None,
        f"Invalid base units: {value!r}",
    )


def author_module():
    spec = importlib.util.spec_from_file_location("scenario_author", ROOT / "scenarios/author.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scenarios() -> int:
    author = author_module()
    cases = sorted((ROOT / "scenarios").glob("*/*.yaml"))
    counts: Counter[str] = Counter()
    splits: dict[str, set[str]] = {"dev": set(), "heldout": set()}
    ids: set[str] = set()
    edf_optimal = 0
    for path in cases:
        s = yaml.safe_load(path.read_text(encoding="utf-8"))
        require(s["id"] == path.stem and s["id"] not in ids, f"ID mismatch/duplicate: {path}")
        ids.add(s["id"])
        require(s["as_of"] == "2026-10-14", "Authoring anchor drifted")
        require(s["treasury"]["stablecoin_decimals"] == 6, "Wrong decimals")
        family, split = s["family"], path.parent.name
        require(family in author.FAMILIES, "Unknown family")
        counts[family] += 1
        splits[split].add(family)
        for group in ("balances", "buffers", "targets", "used_today"):
            for value in s["treasury"][group].values():
                units(value)
        for limits in s["treasury"]["limits"].values():
            for value in limits.values():
                units(value)
            require(
                int(limits["per_request"]) <= int(limits["daily"]), "Undeployable mandate limits"
            )
        require(len(s["requests"]) <= 2, "Oracle bound exceeded")
        request_ids = [r["id"] for r in s["requests"]]
        require(len(request_ids) == len(set(request_ids)), "Duplicate request")
        for p in s["payees"]:
            require(ADDRESS.fullmatch(p["address"]) is not None, "Invalid synthetic address")
            date.fromisoformat(p["active_from"])
        for r in s["requests"]:
            units(r["amount"])
            date.fromisoformat(r["due"])
            if "early_amount" in r:
                units(r["early_amount"])
                require(0 < int(r["early_amount"]) <= int(r["amount"]), "Invalid early option")
                require(r["early_pay_by"] <= r["due"], "Early option after due date")
                require(
                    int(r["early_amount"])
                    == int(r["amount"]) * (10_000 - r["terms"]["discount_bps"]) // 10_000,
                    "Discount terms/option mismatch",
                )
        require(
            s["assumptions"]["review_status"] == "pending_second_person", "Unrecorded human review"
        )
        regenerated = author.build(
            family,
            (
                sorted(
                    p.stem
                    for p in cases
                    if yaml.safe_load(p.read_text(encoding="utf-8"))["family"] == family
                )
            ).index(path.stem),
            s["id"],
        )
        require(s == regenerated, f"Scenario or oracle label drifted: {path}")
        if "expected_liquidity" not in s:
            fields = ("value", "transaction_count", "missed_deadlines", "infeasible")
            edf_optimal += int(all(s["expected"][k] == s["expected_b0"][k] for k in fields))
    require(len(cases) >= 30, "Need at least 30 scenarios")
    require(sum(p.parent.name == "heldout" for p in cases) >= 10, "Need at least 10 heldout cases")
    require(all(counts[f] >= 4 for f in author.FAMILIES), "Need four per family")
    require(not splits["dev"] & splits["heldout"], "Family split leakage")
    require(edf_optimal >= 5, "Need at least five EDF-optimal cases")
    print(
        f"Scenarios: {len(cases)}, 10 families, 12 heldout, {edf_optimal} EDF-optimal non-liquidity cases"
    )
    return len(cases)


def pdf_matches(path: Path, digest: str) -> None:
    require(
        path.is_file() and path.read_bytes().startswith(b"%PDF-"), f"Missing/invalid PDF: {path}"
    )
    require(hashlib.sha256(path.read_bytes()).hexdigest() == digest, f"PDF digest mismatch: {path}")


def main() -> None:
    scenarios()
    print("Evaluation authoring validation passed; human ground-truth review remains pending")


if __name__ == "__main__":
    main()
