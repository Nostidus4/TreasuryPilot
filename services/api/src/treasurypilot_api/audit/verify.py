from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from treasurypilot_api.audit.models import AuditHead, AuditLog
from treasurypilot_api.audit.writer import ZERO_HASH, compute_hash


@dataclass(frozen=True, slots=True)
class ChainVerification:
    status: Literal["INTACT", "BROKEN"]
    checked: int
    broken_at: int | None = None


def verify_chain(rows: Iterable[AuditLog], head: AuditHead | None = None) -> ChainVerification:
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
