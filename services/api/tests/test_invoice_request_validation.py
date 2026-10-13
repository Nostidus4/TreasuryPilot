from __future__ import annotations

import uuid
from datetime import date

import pytest

from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.invoices.requests import _amount, _request_id, _validate_dates


def test_manual_request_amount_uses_asset_precision_without_rounding() -> None:
    assert _amount("12.30", 2) == 1230
    with pytest.raises(AuthFailure) as error:
        _amount("12.301", 2)
    assert error.value.code == "AMOUNT_PRECISION"


def test_manual_request_amount_must_be_positive() -> None:
    with pytest.raises(AuthFailure) as error:
        _amount("0", 6)
    assert error.value.code == "AMOUNT_NOT_POSITIVE"


def test_manual_request_due_date_cannot_precede_issue_date() -> None:
    with pytest.raises(AuthFailure) as error:
        _validate_dates(date(2026, 10, 2), date(2026, 10, 1))
    assert error.value.code == "DATE_INVALID"


def test_onchain_request_id_is_stable_bytes32_for_org_and_request() -> None:
    organization_id = uuid.UUID("00000000-0000-7000-8000-000000000010")
    request_id = uuid.UUID("00000000-0000-7000-8000-000000000020")
    digest = _request_id(organization_id, request_id)
    assert len(digest) == 32
    assert digest == _request_id(organization_id, request_id)
    assert digest != _request_id(organization_id, uuid.uuid4())
