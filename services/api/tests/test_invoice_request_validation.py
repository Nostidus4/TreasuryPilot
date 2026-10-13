from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy.dialects import postgresql

from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.invoices.fingerprints import find_active_duplicate
from treasurypilot_api.invoices.requests import (
    _amount,
    _duplicate_fingerprint,
    _request_id,
)


def test_manual_request_amount_uses_asset_precision_without_rounding() -> None:
    assert _amount("12.30", 2) == 1230
    with pytest.raises(AuthFailure) as error:
        _amount("12.301", 2)
    assert error.value.code == "AMOUNT_PRECISION"


def test_manual_request_amount_must_be_positive() -> None:
    with pytest.raises(AuthFailure) as error:
        _amount("0", 6)
    assert error.value.code == "AMOUNT_NOT_POSITIVE"


def test_onchain_request_id_is_stable_bytes32_for_org_and_request() -> None:
    organization_id = uuid.UUID("00000000-0000-7000-8000-000000000010")
    request_id = uuid.UUID("00000000-0000-7000-8000-000000000020")
    digest = _request_id(organization_id, request_id)
    assert len(digest) == 32
    assert digest == _request_id(organization_id, request_id)
    assert digest != _request_id(organization_id, uuid.uuid4())


@dataclass
class _CaptureSession:
    statement: object | None = None

    async def scalar(self, statement: object) -> None:
        self.statement = statement
        return None


def test_duplicate_query_is_scoped_to_treasury_and_excludes_terminal_requests() -> None:
    treasury_id = uuid.uuid4()
    request_id = uuid.uuid4()
    session = _CaptureSession()
    duplicate = asyncio.run(
        find_active_duplicate(
            session,  # type: ignore[arg-type]
            treasury_id=treasury_id,
            value=bytes.fromhex("ab" * 32),
            exclude_request_id=request_id,
        )
    )

    assert duplicate is None
    assert session.statement is not None
    compiled = str(session.statement.compile(dialect=postgresql.dialect()))
    assert "payment_requests.treasury_id =" in compiled
    assert "payment_requests.id !=" in compiled
    assert "payment_requests.status NOT IN" in compiled


def test_duplicate_error_exposes_existing_request_id_extension() -> None:
    existing = uuid.uuid4()

    error = _duplicate_fingerprint(existing)

    assert error.status == 409
    assert error.code == "DUPLICATE_FINGERPRINT"
    assert error.extensions["existingRequestId"] == str(existing)
