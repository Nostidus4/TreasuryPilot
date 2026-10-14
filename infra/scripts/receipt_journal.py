"""Durable per-request submission state: an ambiguous send is never retried blindly."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import cast


def load_journal(path: Path, identity: dict[str, object]) -> dict[str, object] | None:
    if not path.exists():
        return None
    stored = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(stored, dict) or stored.get("identity") != identity:
        raise ValueError("Receipt journal does not match this request and payload")
    return cast(dict[str, object], stored)


def write_journal(path: Path, identity: dict[str, object], **state: object) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as output:
            temporary = Path(output.name)
            json.dump({"identity": identity, **state}, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
