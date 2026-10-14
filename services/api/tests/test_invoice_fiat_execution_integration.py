from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from eth_abi import decode

from treasurypilot_api.invoices.fx import propose_request_payment
from treasurypilot_core.domain import FxPolicy, FxQuote, FxRate
from treasurypilot_core.domain.models import BaseUnits
from treasurypilot_core.eip712 import PAYMENT_APPROVAL_TYPE, PLAN_ATTESTATION_TYPE
from treasurypilot_core.policy import Action, PlanStep
from treasurypilot_worker.chain.rpc import RpcClient, RpcProvider
from treasurypilot_worker.executor.simulation import SimulationContext, simulate

ASSET = "0x" + "11" * 20
EXECUTOR = "0x" + "e1" * 20
TARGET = "0x" + "e2" * 20
WALLET = "0x" + "b2" * 20
PAYEE = "0x" + "c1" * 20
STEP_ID = bytes.fromhex("5e" * 32)
POLICY = FxPolicy(source_id="approved-feed", max_quote_age_seconds=60, depeg_threshold_bps=100)


def _quote(units: int) -> FxQuote:
    return FxQuote(
        source_id="approved-feed",
        rate=FxRate(
            fiat_currency="EUR",
            stablecoin_asset=ASSET,
            stablecoin_units=units,
            fiat_minor_units=100,
        ),
        observed_at=110,
        stablecoin_usd_price_micros=1_000_000,
    )


@dataclass
class _FiatRequest:
    amount: int = 120  # Signed stablecoin maximum, not the fresh execution amount.
    fiat_amount_minor_units: int | None = 100
    fiat_currency: str | None = "EUR"
    fx_reference_quote: dict[str, object] | None = None
    fx_tolerance_bps: int | None = 500

    def __post_init__(self) -> None:
        if self.fx_reference_quote is None:
            self.fx_reference_quote = _quote(100).model_dump(mode="json")


class _Provider:
    async def quote(self, **_: object) -> FxQuote:
        return _quote(101)


class _RpcNode:
    def __init__(self) -> None:
        self.requests: list[tuple[str, Any]] = []

    async def make_request(self, method: str, params: Any) -> dict[str, Any]:
        self.requests.append((method, params))
        result = "0x01" if method == "eth_getCode" else "0x"
        return {"jsonrpc": "2.0", "id": 1, "result": result}


def test_fresh_quote_to_pre_signing_calldata_preserves_the_approved_cap() -> None:
    request = _FiatRequest()
    proposed = asyncio.run(
        propose_request_payment(request, _Provider(), policy=POLICY, now_timestamp=110)
    )
    step = PlanStep(
        seq=0,
        step_id=STEP_ID,
        action=Action.PAY,
        from_wallet=WALLET,
        to=PAYEE,
        asset=ASSET,
        amount=proposed,
    )
    approval = {
        "requestId": "0x" + "01" * 32,
        "invoiceHash": "0x" + "02" * 32,
        "fingerprint": "0x" + "03" * 32,
        "treasury": TARGET,
        "payingWallet": WALLET,
        "asset": ASSET,
        "payee": PAYEE,
        "amount": request.amount,
        "earlyAmount": 0,
        "earlyPayBy": 0,
        "deadline": 2_000_000_000,
        "termsHash": "0x" + "04" * 32,
        "expiry": 2_000_000_000,
    }
    attestation = {
        "planHash": "0x" + "05" * 32,
        "requestId": approval["requestId"],
        "stepIds": ["0x" + STEP_ID.hex()],
        "policyVersion": "0x" + "06" * 32,
        "executor": EXECUTOR,
        "validUntil": 2_000_000_000,
        "nonce": 7,
        "evidenceDigest": "0x" + "07" * 32,
    }
    context = SimulationContext(
        executor=EXECUTOR,
        target=TARGET,
        attestation=attestation,
        attestation_signature=b"\x11" * 65,
        policy_version=b"\x06" * 32,
        snapshot_block=42,
        approval=approval,
        approver_signature=b"\x22" * 64,
    )
    node = _RpcNode()
    decision = asyncio.run(simulate(RpcClient([RpcProvider("fixture", node)]), step, context))

    approval_type = "(" + ",".join(field["type"] for field in PAYMENT_APPROVAL_TYPE) + ")"
    attestation_type = "(" + ",".join(field["type"] for field in PLAN_ATTESTATION_TYPE) + ")"
    calldata = bytes.fromhex(node.requests[1][1][0]["data"].removeprefix("0x"))
    decoded = decode(
        [approval_type, "bytes", "bytes32", "uint256", attestation_type, "bytes"],
        calldata[4:],
    )

    assert decision.decision == "ALLOW"
    assert proposed == BaseUnits(101)
    assert decoded[0][7] == request.amount == 120
    assert decoded[3] == proposed == 101
