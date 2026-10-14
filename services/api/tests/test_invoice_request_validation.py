from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.dialects import postgresql

from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.invoices.fingerprints import (
    DuplicateFingerprintConflict,
    find_active_duplicate,
)
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.invoices.requests import (
    RequestCreate,
    RequestPatch,
    _active_mandate_config_stmt,
    _amount,
    _asset_pay_limit,
    _request_id,
    _validate_dates,
    _validated_terms,
    confirmed_payment_terms,
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


def test_secondary_asset_requires_its_own_active_pay_policy_and_limit() -> None:
    asset_id = uuid.uuid4()
    other_asset_id = uuid.uuid4()
    window = {
        "validFrom": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        "expiresAt": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    config = {
        **window,
        "assetPolicies": [
            {
                "assetId": str(asset_id),
                "limits": {"PAY": {"perRequest": "5000", "daily": "10000"}},
            }
        ],
    }
    assert _asset_pay_limit(config, asset_id) == 5000
    assert _asset_pay_limit(config, other_asset_id) is None
    assert _asset_pay_limit({**config, "expiresAt": window["validFrom"]}, asset_id) is None
    assert _asset_pay_limit({"assetPolicies": []}, asset_id) is None
    assert (
        _asset_pay_limit(
            {
                **window,
                "assetPolicies": [
                    {"assetId": str(asset_id), "limits": {"PAY": {"perRequest": "NaN"}}}
                ],
            },
            asset_id,
        )
        is None
    )


def test_active_asset_policy_lookup_is_scoped_to_treasury() -> None:
    treasury_id = uuid.uuid4()
    statement = _active_mandate_config_stmt(treasury_id)
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "mandate_versions.treasury_id =" in compiled
    assert "mandate_versions.status =" in compiled
    assert "mandate_versions.version DESC" in compiled


def test_fiat_fields_must_be_supplied_as_a_pair_and_use_minor_units() -> None:
    common = {
        "treasury_id": uuid.uuid4(),
        "vendor_id": uuid.uuid4(),
        "payee_id": uuid.uuid4(),
        "invoice_no": "INV-1",
        "issue_date": date(2026, 10, 1),
        "due_date": date(2026, 10, 2),
        "amount": "100.00",
        "asset_id": uuid.uuid4(),
    }
    with pytest.raises(ValueError, match="supplied together"):
        RequestCreate.model_validate({**common, "fiat_currency": "EUR"})
    with pytest.raises(ValueError):
        RequestCreate.model_validate(
            {**common, "fiat_currency": "EUR", "fiat_amount_minor_units": "01"}
        )
    request = RequestCreate.model_validate(
        {**common, "fiat_currency": "EUR", "fiat_amount_minor_units": "12345"}
    )
    assert request.fiat_amount_minor_units == "12345"


def test_fiat_patch_can_clear_both_fields_together() -> None:
    patch = RequestPatch.model_validate({"fiat_currency": None, "fiat_amount_minor_units": None})
    assert patch.model_dump(exclude_unset=True) == {
        "fiat_currency": None,
        "fiat_amount_minor_units": None,
    }


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

    error = DuplicateFingerprintConflict(existing)

    assert error.status == 409
    assert error.code == "DUPLICATE_FINGERPRINT"
    assert error.extensions["existingRequestId"] == str(existing)


def test_confirmed_discount_terms_derive_exact_integer_approval_option() -> None:
    stored, digest, early = _validated_terms(
        {"netDueDay": 21_000, "discountBps": 250, "discountDeadlineDay": 20_990},
        1_001,
    )
    assert early is not None
    early_amount, early_pay_by = early
    assert stored["net_due_day"] == 21_000
    assert len(digest) == 32
    assert early_amount == 976  # 1001 - floor(1001 * 250 / 10000)
    assert early_pay_by == 20_990 * 86_400 + 86_399


def test_invalid_terms_return_domain_error() -> None:
    with pytest.raises(AuthFailure) as error:
        _validated_terms({"netDueDay": 21_000, "discountBps": 250}, 1_000)
    assert error.value.code == "TERMS_INVALID"
    with pytest.raises(AuthFailure) as error:
        _validated_terms(
            {"netDueDay": 21_000, "discountBps": 10_000, "discountDeadlineDay": 20_990},
            1_000,
        )
    assert error.value.code == "TERMS_INVALID"


def test_camel_case_late_fee_is_validated_by_engine_model() -> None:
    stored, _, early = _validated_terms(
        {
            "netDueDay": 21_000,
            "lateFee": {"kind": "percent_per_period", "rateBps": 100, "periodDays": 7},
        },
        1_000,
    )
    assert stored["late_fee"]["period_days"] == 7
    assert early is None


def test_late_fee_amount_accepts_decimal_string() -> None:
    stored, _, _ = _validated_terms(
        {"netDueDay": 21_000, "lateFee": {"kind": "fixed", "amount": "12345678901234567890"}},
        1_000,
    )
    # BaseUnits accepts canonical integer strings and stores them as strings (JS-safe).
    assert stored["late_fee"]["amount"] == "12345678901234567890"


def test_scheduler_only_sees_confirmed_terms() -> None:
    row = PaymentRequest(terms={"net_due_day": 21_000})
    assert confirmed_payment_terms(row) is None
    row.terms_confirmed_by = uuid.uuid4()
    assert confirmed_payment_terms(row).net_due_day == 21_000
