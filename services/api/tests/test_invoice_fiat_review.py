from __future__ import annotations

import asyncio
import re
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from eth_abi import encode
from eth_utils import keccak
from pydantic import ValidationError

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.invoices.fx import propose_request_payment
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.invoices.requests import (
    _capture_fiat_reference,
    _fiat_recapture_needed,
    _hashes,
)
from treasurypilot_api.main import create_app
from treasurypilot_api.treasury.models import Asset
from treasurypilot_core.domain import FxPolicy
from treasurypilot_core.fingerprint import normalize

_FIAT = {
    "fiat_amount_minor_units": 100,
    "fiat_currency": "EUR",
    "fx_reference_quote": {"a": 1},
    "fx_tolerance_bps": 50,
}
_POLICY = FxPolicy(source_id="feed", max_quote_age_seconds=60, depeg_threshold_bps=100)


def _row(**fiat: object) -> PaymentRequest:
    return PaymentRequest(
        invoice_no="INV-1",
        amount=1_000,
        issue_date=date(2026, 10, 1),
        due_at=date(2026, 10, 2),
        **fiat,
    )


def test_non_fiat_invoice_hash_keeps_original_seven_field_encoding() -> None:
    address = b"\x11" * 20
    row = _row()
    _hashes(row, "vendor", address)
    legacy = keccak(
        encode(
            ["string", "string", "uint256", "address", "string", "string", "bytes32"],
            [
                normalize("vendor"),
                normalize("INV-1"),
                1_000,
                address,
                "2026-10-01",
                "2026-10-02",
                bytes(32),
            ],
        )
    )
    assert row.invoice_hash == legacy
    fiat = _row(**_FIAT)
    _hashes(fiat, "vendor", address)
    assert fiat.invoice_hash != legacy


def test_fiat_constraint_requires_every_fiat_column_to_be_not_null() -> None:
    migration = next(
        Path(__file__).parents[1].glob("migrations/versions/*_fiat_request_amounts.py")
    ).read_text()
    model_sql = next(
        c.sqltext.text
        for c in PaymentRequest.__table__.constraints
        if getattr(c, "name", None) == "ck_payment_requests_fiat_fx_pair"
    )
    for sql in (model_sql, re.sub(r'"\s*\n\s*"', "", migration)):
        fiat_branch = sql.split(") OR (")[1]
        for column in _FIAT:
            assert f"{column} IS NOT NULL" in fiat_branch


def test_fiat_recapture_only_when_priced_fields_change() -> None:
    asset_id = uuid.uuid4()
    asset = Asset(id=asset_id, decimals=6)
    row = _row(**_FIAT)
    row.asset_id = asset_id
    row.amount = 1_000_000
    # Unrelated bound edits and same-value amounts keep the stored quote.
    assert not _fiat_recapture_needed(row, {"invoice_no": "X"}, 100, "EUR", asset)
    assert not _fiat_recapture_needed(row, {"amount": "1.000000"}, 100, "EUR", asset)
    assert _fiat_recapture_needed(row, {"amount": "2"}, 100, "EUR", asset)
    assert _fiat_recapture_needed(row, {}, 101, "EUR", asset)
    assert _fiat_recapture_needed(row, {}, 100, "USD", asset)
    assert _fiat_recapture_needed(row, {}, 100, "EUR", Asset(id=uuid.uuid4(), decimals=6))


def test_fx_settings_are_wired_into_app_state_and_validated() -> None:
    app = create_app(
        settings=Settings(fx_source_id="feed", fx_tolerance_bps=25, fx_max_quote_age_seconds=60)
    )
    assert app.state.fx_tolerance_bps == 25
    assert app.state.fx_policy == _POLICY
    assert create_app(settings=Settings()).state.fx_policy is None
    with pytest.raises(ValidationError):
        Settings(fx_tolerance_bps=10_001)


def test_fiat_request_rejects_bad_tolerance_and_addressless_asset() -> None:
    def call(tolerance: object, address: bytes | None) -> AuthFailure:
        state = SimpleNamespace(
            fx_quote_provider=object(), fx_policy=_POLICY, fx_tolerance_bps=tolerance
        )
        request = SimpleNamespace(app=SimpleNamespace(state=state))
        with pytest.raises(AuthFailure) as error:
            asyncio.run(
                _capture_fiat_reference(
                    request,  # type: ignore[arg-type]
                    currency="EUR",
                    fiat_amount_minor_units=100,
                    max_stablecoin_amount=1,
                    asset=Asset(decimals=6, address=address),
                )
            )
        return error.value

    for bad in (True, -1, 10_001):
        assert call(bad, b"\x11" * 20).code == "FX_UNAVAILABLE"
    assert call(50, b"\x11" * 19).code == "ASSET_NOT_PAYMENT_STABLECOIN"
    assert call(50, None).code == "ASSET_NOT_PAYMENT_STABLECOIN"


def test_inconsistent_fiat_fields_are_rejected_not_treated_as_non_fiat() -> None:
    row = SimpleNamespace(
        amount=1,
        fiat_amount_minor_units=None,
        fiat_currency=None,
        fx_reference_quote={"a": 1},
        fx_tolerance_bps=None,
    )
    with pytest.raises(ValueError, match="missing its captured FX approval data"):
        asyncio.run(
            propose_request_payment(row, object(), policy=_POLICY, now_timestamp=1)  # type: ignore[arg-type]
        )
