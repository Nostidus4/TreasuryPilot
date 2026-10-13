from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from treasurypilot_api.audit import ZERO_HASH, AuditLog, chain, compute_hash
from treasurypilot_api.audit.api import AuditRecordView


def _dump(path: Path) -> list[str]:
    org_id = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
    previous = ZERO_HASH
    lines = []
    for seq in (3, 5, 9):
        row = AuditLog(
            seq=seq,
            org_id=org_id,
            at=datetime(2026, 10, 13, 1, 2, seq, 250000, tzinfo=UTC),
            actor_type="USER",
            actor_id="u-1",
            action="request.approve",
            entity_type="request",
            entity_id=f"r-{seq}",
            data={"amount": "100", "memo": "café"},
            prev_hash=previous,
        )
        row.hash = previous = compute_hash(row)
        lines.append(AuditRecordView.from_row(row).model_dump_json(by_alias=True))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


def _verify(path: Path) -> subprocess.CompletedProcess[str]:
    # -I -S: no site-packages and no repo on the path, so the script runs on the stdlib alone.
    return subprocess.run(
        [sys.executable, "-I", "-S", chain.__file__, "verify", "--dump", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_offline_verify_accepts_an_intact_dump_and_reports_the_first_edited_record(
    tmp_path: Path,
) -> None:
    dump = tmp_path / "audit.jsonl"
    lines = _dump(dump)

    intact = _verify(dump)
    assert intact.returncode == 0, intact.stderr
    assert json.loads(intact.stdout) == {"status": "INTACT", "checked": 3, "brokenAt": None}

    lines[1] = lines[1].replace('"amount":"100"', '"amount":"900"')
    dump.write_text("\n".join(lines) + "\n", encoding="utf-8")
    broken = _verify(dump)
    assert broken.returncode == 1
    assert json.loads(broken.stdout) == {"status": "BROKEN", "checked": 2, "brokenAt": 5}

    dump.write_text("not json\n", encoding="utf-8")
    malformed = _verify(dump)
    assert malformed.returncode == 2
    assert "line 1" in malformed.stderr
