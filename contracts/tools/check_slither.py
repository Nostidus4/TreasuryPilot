"""Fail on unreviewed High/Medium findings; never blanket-exclude a detector."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


def fingerprint(description: str) -> str:
    # Line movement must not invalidate an otherwise identical triage entry.
    normalized = re.sub(r"#\d+(?:-\d+)?", "", description)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


def check(report_path: Path, triage_path: Path) -> list[str]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("success") is not True:
        return ["Slither did not complete successfully"]
    findings = report.get("results", {}).get("detectors")
    if not isinstance(findings, list):
        return ["Slither report is missing detector results"]
    triage = json.loads(triage_path.read_text(encoding="utf-8"))
    accepted = {
        (entry["check"], entry["impact"], entry["fingerprint"]): entry
        for entry in triage["accepted"]
        if entry.get("reason") and entry.get("evidence")
    }
    errors = []
    for finding in findings:
        if finding["impact"] not in {"High", "Medium"}:
            continue
        identity = (finding["check"], finding["impact"], fingerprint(finding["description"]))
        if identity not in accepted:
            errors.append(f"Untriaged {finding['impact']} {finding['check']}: {finding['description']}")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/check_slither.py slither.json", file=sys.stderr)
        return 2
    errors = check(Path(sys.argv[1]), Path(__file__).with_name("slither-triage.json"))
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print("Slither: no untriaged High or Medium findings")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
