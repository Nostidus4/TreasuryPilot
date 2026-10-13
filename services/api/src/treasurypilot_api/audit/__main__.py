"""Offline audit chain verification: ``python -m treasurypilot_api.audit verify --dump FILE``.

The dump is JSON Lines of ``GET /v1/orgs/{o}/audit-log`` items in ``seq`` order, e.g.
``curl ... | jq -c '.items[]' >> audit.jsonl`` for every page. Exit code 0 means intact,
1 broken, 2 an unreadable dump. A dump has no chain head, so records missing from its
end go unnoticed here; ``GET /audit-log/verify`` also checks the head.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

from treasurypilot_api.audit.api import AuditRecordView, AuditVerifyResponse
from treasurypilot_api.audit.models import AuditLog
from treasurypilot_api.audit.verify import verify_chain


class UnreadableDump(Exception):
    pass


def _rows(path: Path) -> Iterator[AuditLog]:
    with path.open(encoding="utf-8") as lines:
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                yield AuditRecordView.model_validate_json(line).to_row()
            except ValueError as exc:
                raise UnreadableDump(
                    f"{path}: line {number} is not an audit record: {exc}"
                ) from None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m treasurypilot_api.audit")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="Verify the hash chain of an audit log dump.")
    verify.add_argument("--dump", type=Path, required=True, help="JSON Lines audit records.")
    arguments = parser.parse_args(argv)

    try:
        result = verify_chain(_rows(arguments.dump))
    except (UnreadableDump, OSError) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(AuditVerifyResponse.from_result(result).model_dump_json(by_alias=True))
    return 0 if result.status == "INTACT" else 1


if __name__ == "__main__":
    sys.exit(main())
