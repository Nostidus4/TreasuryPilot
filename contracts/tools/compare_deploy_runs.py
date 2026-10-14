"""Check deterministic local deployments generated on fresh Anvil instances."""

from __future__ import annotations

import json
import sys
from pathlib import Path

DETERMINISTIC_FIELDS = (
    "implementation",
    "implementationCodeHash",
    "factory",
    "factoryCodeHash",
    "testToken",
    "testTokenCodeHash",
    "module",
    "moduleCodeHash",
    "safeT",
    "safeO1",
    "safeO2",
    "safeSingleton",
    "safeProxyFactory",
    "multiSend",
    "easSchemaUid",
)


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python tools/compare_deploy_runs.py FIRST.json SECOND.json", file=sys.stderr)
        return 2
    first = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    second = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    differences = [field for field in DETERMINISTIC_FIELDS if first.get(field) != second.get(field)]
    if differences:
        print(f"Fresh Anvil deployments differ in: {', '.join(differences)}", file=sys.stderr)
        return 1
    print("Fresh dry runs reproduce all CREATE2/code-hash and demo addresses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
