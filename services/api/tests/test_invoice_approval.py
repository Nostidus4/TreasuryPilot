from __future__ import annotations

import pytest

from treasurypilot_api.invoices.approval import build_approval_typed_data
from treasurypilot_core.eip712 import PAYMENT_APPROVAL_TYPE
from treasurypilot_core.policy.context import RequestView

MODULE = "0x1111111111111111111111111111111111111111"
WALLET = "0x2222222222222222222222222222222222222222"
ASSET = "0x3333333333333333333333333333333333333333"
PAYEE = "0x4444444444444444444444444444444444444444"


def _request(**overrides: object) -> RequestView:
    data: dict[str, object] = {
        "request_id": bytes.fromhex("01" * 32),
        "status": "AwaitingApproval",
        "invoice_hash": bytes.fromhex("02" * 32),
        "fingerprint": bytes.fromhex("03" * 32),
        "terms_hash": bytes.fromhex("04" * 32),
        "paying_wallet": WALLET,
        "payee": PAYEE,
        "amount": 100_000,
        "early_amount": 95_000,
        "early_pay_by": 1_800_000_000,
        "deadline": 1_800_100_000,
    }
    data.update(overrides)
    return RequestView.model_validate(data)


def test_builds_exact_contract_typed_data_and_caps_expiry() -> None:
    typed = build_approval_typed_data(
        _request(),
        chain_id=84532,
        module_address=MODULE,
        now=1_800_000_100,
        approval_max_age=5_000_000,
        asset=ASSET,
    )

    message = typed["message"]
    assert typed["primaryType"] == "PaymentApproval"
    assert typed["domain"] == {
        "name": "TreasuryPilot",
        "version": "1",
        "chainId": 84532,
        "verifyingContract": MODULE,
    }
    assert isinstance(message, dict)
    assert tuple(message) == tuple(field["name"] for field in PAYMENT_APPROVAL_TYPE)
    assert message == {
        "requestId": "0x" + "01" * 32,
        "invoiceHash": "0x" + "02" * 32,
        "fingerprint": "0x" + "03" * 32,
        "treasury": MODULE,
        "payingWallet": WALLET,
        "asset": ASSET,
        "payee": PAYEE,
        "amount": "100000",
        "earlyAmount": "95000",
        "earlyPayBy": 1_800_000_000,
        "deadline": 1_800_100_000,
        "termsHash": "0x" + "04" * 32,
        "expiry": 1_801_309_600,
    }


def test_expiry_is_capped_by_mandate_max_age() -> None:
    typed = build_approval_typed_data(
        _request(),
        chain_id=84532,
        module_address=MODULE,
        now=1_800_000_100,
        approval_max_age=86_400,
        asset=ASSET,
    )

    assert typed["message"]["expiry"] == 1_800_086_500  # type: ignore[index]


@pytest.mark.parametrize(
    ("overrides", "kwargs", "error"),
    [
        ({"status": "Draft"}, {}, "AwaitingApproval"),
        ({}, {"approval_max_age": 0}, "approval_max_age"),
        ({"deadline": 1_700_000_000}, {}, "approval window has closed"),
        ({"deadline": 0}, {}, "deadline must be positive"),
        ({"early_amount": 100_001}, {}, "early_amount"),
        ({"deadline": 2**64}, {}, "uint64"),
        ({"early_pay_by": 2**64}, {}, "uint64"),
        ({}, {"approval_max_age": 86_399}, "approval_max_age"),
        ({}, {"approval_max_age": 60 * 86_400 + 1}, "approval_max_age"),
        ({}, {"now": -1}, "now must"),
        ({}, {"chain_id": 0}, "chain_id"),
        ({}, {"module_address": "0x1234"}, "String should match"),
        ({}, {"asset": "not-an-address"}, "String should match"),
    ],
)
def test_refuses_invalid_approval_inputs(
    overrides: dict[str, object], kwargs: dict[str, object], error: str
) -> None:
    args: dict[str, object] = {
        "chain_id": 84532,
        "module_address": MODULE,
        "now": 1_800_000_100,
        "approval_max_age": 86_400,
        "asset": ASSET,
    }
    args.update(kwargs)
    with pytest.raises(ValueError, match=error):
        build_approval_typed_data(_request(**overrides), **args)  # type: ignore[arg-type]


def test_grace_window_boundary() -> None:
    args: dict[str, object] = {
        "chain_id": 84532,
        "module_address": MODULE,
        "approval_max_age": 86_400,
        "asset": ASSET,
    }
    deadline_end = 1_800_100_000 + 14 * 86_400
    build_approval_typed_data(_request(), now=deadline_end - 1, **args)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="approval window has closed"):
        build_approval_typed_data(_request(), now=deadline_end, **args)  # type: ignore[arg-type]
