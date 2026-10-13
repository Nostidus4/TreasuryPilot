from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from treasurypilot_api.audit import ZERO_HASH, AuditLog, compute_hash
from treasurypilot_api.audit.writer import _json_value


def test_integral_decimals_have_one_canonical_form() -> None:
    assert _json_value(Decimal("1500")) == _json_value(Decimal("1.5E3")) == "1500"
    assert _json_value(Decimal("2.00")) == "2"


@pytest.mark.parametrize(
    "value",
    [Decimal("0.5"), Decimal("NaN"), 1e16, 0.5, {"fee": 1.0}, "nul\x00", {"k\x00": 1}],
)
def test_values_that_cannot_round_trip_through_jsonb_are_rejected(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _json_value(value)


def test_hash_covers_the_previous_hash_and_every_field() -> None:
    row = AuditLog(
        seq=1,
        org_id=uuid.uuid4(),
        at=datetime(2026, 10, 13, tzinfo=UTC),
        actor_type="SYSTEM",
        actor_id=None,
        action="org.created",
        entity_type="organization",
        entity_id=None,
        data={"amount": "100"},
        prev_hash=ZERO_HASH,
    )
    original = compute_hash(row)
    row.prev_hash = bytes([1]) * 32
    assert compute_hash(row) != original
    row.prev_hash = ZERO_HASH
    row.data = {"amount": "101"}
    assert compute_hash(row) != original
