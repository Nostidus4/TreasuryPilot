"""Compare two Forge JSON runs so a pinned fork must have repeatable outcomes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def summary(path: Path) -> dict[str, tuple[str, int | None]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    results: dict[str, Any] = {}
    if isinstance(data.get("test_results"), dict):
        results.update(data["test_results"])
    else:
        for suite_name, suite in data.items():
            if isinstance(suite, dict) and isinstance(suite.get("test_results"), dict):
                results.update(
                    {
                        f"{suite_name}:{name}": result
                        for name, result in suite["test_results"].items()
                    }
                )
    if not results:
        raise ValueError(f"{path} has no Forge test results")
    parsed: dict[str, tuple[str, int | None]] = {}
    for name, result in results.items():
        if not isinstance(result, dict):
            raise ValueError(f"Malformed test result: {name}")
        status = str(result.get("status", ""))
        gas = result.get("gas_used", result.get("gasUsed"))
        kind = result.get("kind")
        if gas is None and isinstance(kind, dict):
            case = next(iter(kind.values()), None)
            if isinstance(case, dict):
                gas = case.get("gas")
        gas_used = int(gas) if isinstance(gas, int | str) else None
        if status != "Success":
            raise ValueError(f"Fork test failed: {name}: {status} {result.get('reason', '')}")
        parsed[name] = (status, gas_used)
    return parsed


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python tools/compare_fork_runs.py FIRST.json SECOND.json", file=sys.stderr)
        return 2
    try:
        first, second = summary(Path(sys.argv[1])), summary(Path(sys.argv[2]))
        if first != second:
            raise ValueError("Pinned Sepolia fork results differ between runs")
        if len(first) != 4:
            raise ValueError(f"Expected four fork cases, found {len(first)}")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Pinned Sepolia fork is repeatable: {len(first)} passing cases, matching gas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
