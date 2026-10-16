"""simulation_context frames the approver signature as the module's abi.encode(address, bytes)."""

from __future__ import annotations

from types import SimpleNamespace

from eth_abi import decode

from treasurypilot_worker.executor.plan_loader import simulation_context

SIGNER = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"


def test_approver_signature_round_trips_as_abi_encoded_address_and_bytes() -> None:
    signature = bytes(range(65))
    approval = SimpleNamespace(typed={"k": 1}, signer=SIGNER, signature=signature)
    loaded = SimpleNamespace(executor=SIGNER, typed_data={"message": {}}, signature=b"\x01")
    inputs = SimpleNamespace(approval=approval, travel_rule_clear=None)

    context = simulation_context(loaded, inputs, SIGNER)  # type: ignore[arg-type]

    address, decoded = decode(["address", "bytes"], context.approver_signature)
    assert address.lower() == SIGNER.lower()
    assert decoded == signature
