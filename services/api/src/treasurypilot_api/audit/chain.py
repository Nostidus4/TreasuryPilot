"""Audit hash chain: canonical hashing and verification, standard library only.

The API writes and verifies with this module, and auditors run the same file offline
without installing anything: ``python chain.py verify --dump audit.jsonl``. The dump is
JSON Lines of ``GET /v1/orgs/{o}/audit-log`` items in ``seq`` order, e.g.
``curl ... | jq -c '.items[]' >> audit.jsonl`` for every page. Exit code 0 means intact,
1 broken, 2 an unreadable dump. A dump has no chain head, so records missing from its
end go unnoticed here; ``GET /audit-log/verify`` also checks the head.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol

ZERO_HASH = bytes(32)


class ChainRecord(Protocol):
    @property
    def seq(self) -> int: ...
    @property
    def org_id(self) -> uuid.UUID: ...
    @property
    def at(self) -> datetime: ...
    @property
    def actor_type(self) -> str: ...
    @property
    def actor_id(self) -> str | None: ...
    @property
    def action(self) -> str: ...
    @property
    def entity_type(self) -> str: ...
    @property
    def entity_id(self) -> str | None: ...
    @property
    def data(self) -> dict[str, Any]: ...
    @property
    def prev_hash(self) -> bytes: ...
    @property
    def hash(self) -> bytes: ...


class ChainHead(Protocol):
    @property
    def org_id(self) -> uuid.UUID: ...
    @property
    def last_seq(self) -> int | None: ...
    @property
    def last_hash(self) -> bytes: ...


def _text(value: str) -> str:
    # Postgres JSONB rejects U+0000; fail here instead of aborting the caller's transaction.
    if "\x00" in value:
        raise ValueError("audit data cannot contain NUL characters")
    return value


def _json_value(value: Any) -> Any:
    """Normalize ``value`` to JSON that survives the JSONB round trip unchanged.

    Hashes are recomputed from stored rows, so every value must read back exactly as
    it was hashed: floats are rejected (JSONB renormalizes them) and Decimals must be
    integral (amounts are integer base units) and are written as plain digit strings.
    """

    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("audit timestamps must include a timezone")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise ValueError("audit decimals must be integral base units")
        return str(int(value))
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("audit data object keys must be strings")
        return {_text(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, float):
        raise TypeError("audit data cannot contain floats; pass amounts as strings")
    if isinstance(value, str):
        return _text(value)
    if value is None or isinstance(value, int | bool):
        return value
    raise TypeError(f"unsupported audit data value: {type(value).__name__}")


def _canonical_json(value: Mapping[str, object]) -> bytes:
    normalized = _json_value(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def compute_hash(row: ChainRecord) -> bytes:
    """Return the chain hash of ``row``; verifiers recompute it from stored rows."""

    record = {
        "seq": row.seq,
        "org_id": str(row.org_id),
        "at": row.at,
        "actor_type": row.actor_type,
        "actor_id": row.actor_id,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "data": row.data,
        "prev_hash": row.prev_hash.hex(),
    }
    return hashlib.sha256(_canonical_json(record)).digest()


@dataclass(frozen=True, slots=True)
class ChainVerification:
    status: Literal["INTACT", "BROKEN"]
    checked: int
    broken_at: int | None = None


def verify_chain(rows: Iterable[ChainRecord], head: ChainHead | None = None) -> ChainVerification:
    """Check records given in ``seq`` order and report the first one that breaks its chain.

    Each org's chain starts at ``ZERO_HASH``. With ``head`` (the org's stored head), pass
    only that org's rows: the chain must end at the head, which catches records appended
    past it or a removed tail (then ``broken_at`` is the head's ``last_seq``). Without a
    head, a removed tail cannot be detected.
    """

    last: dict[uuid.UUID, bytes] = {}
    checked = 0
    for row in rows:
        checked += 1
        beyond_head = head is not None and row.seq > (head.last_seq or 0)
        try:
            valid = (
                not beyond_head
                and row.prev_hash == last.get(row.org_id, ZERO_HASH)
                and compute_hash(row) == row.hash
            )
        except (TypeError, ValueError):  # tampered data the writer would never have hashed
            valid = False
        if not valid:
            return ChainVerification("BROKEN", checked, row.seq)
        last[row.org_id] = row.hash
    if head is not None and last.get(head.org_id, ZERO_HASH) != head.last_hash:
        return ChainVerification("BROKEN", checked, head.last_seq)
    return ChainVerification("INTACT", checked)


@dataclass(frozen=True, slots=True)
class DumpRecord:
    """One ``audit-log`` API item read back from a dump."""

    seq: int
    org_id: uuid.UUID
    at: datetime
    actor_type: str
    actor_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    data: dict[str, Any]
    prev_hash: bytes
    hash: bytes

    @classmethod
    def from_json(cls, line: str) -> DumpRecord:
        item = json.loads(line)
        at = datetime.fromisoformat(item["at"])
        if not isinstance(item["seq"], int) or isinstance(item["seq"], bool):
            raise ValueError("seq must be an integer")
        if at.utcoffset() is None:
            raise ValueError("at must include a timezone")
        if not isinstance(item["data"], dict):
            raise ValueError("data must be an object")
        return cls(
            seq=item["seq"],
            org_id=uuid.UUID(item["orgId"]),
            at=at,
            actor_type=item["actorType"],
            actor_id=item["actorId"],
            action=item["action"],
            entity_type=item["entityType"],
            entity_id=item["entityId"],
            data=item["data"],
            prev_hash=bytes.fromhex(item["prevHash"].removeprefix("0x")),
            hash=bytes.fromhex(item["hash"].removeprefix("0x")),
        )


class UnreadableDump(Exception):
    pass


def _read_dump(path: Path) -> Iterator[DumpRecord]:
    with path.open(encoding="utf-8") as lines:
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                yield DumpRecord.from_json(line)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise UnreadableDump(
                    f"{path}: line {number} is not an audit record: {exc!r}"
                ) from None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chain.py")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="Verify the hash chain of an audit log dump.")
    verify.add_argument("--dump", type=Path, required=True, help="JSON Lines audit records.")
    arguments = parser.parse_args(argv)

    try:
        result = verify_chain(_read_dump(arguments.dump))
    except (UnreadableDump, OSError) as exc:
        print(exc, file=sys.stderr)
        return 2
    output = {"status": result.status, "checked": result.checked, "brokenAt": result.broken_at}
    print(json.dumps(output))
    return 0 if result.status == "INTACT" else 1


if __name__ == "__main__":
    sys.exit(main())
