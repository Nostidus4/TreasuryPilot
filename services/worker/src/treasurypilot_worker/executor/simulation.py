"""Pre-signing `eth_call` simulation of one plan step (POL-007, M08 §6.2).

Catches validator/contract drift on fresh state. Any revert or RPC failure is a BLOCK; the
caller must not retry a blocked step into ALLOW within the same cycle.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
from eth_abi import encode

from treasurypilot_core.eip712 import PAYMENT_APPROVAL_TYPE, PLAN_ATTESTATION_TYPE
from treasurypilot_core.ids import uuid7
from treasurypilot_core.policy import (
    Action,
    Check,
    Decision,
    PlanStep,
    PolicyReasonCode,
    aggregate,
    decode_revert,
    error_selector,
)
from treasurypilot_worker.chain.rpc import RpcClient, RpcError, RpcResponseError

_APPROVAL = "(" + ",".join(f["type"] for f in PAYMENT_APPROVAL_TYPE) + ")"
_ATTESTATION = "(" + ",".join(f["type"] for f in PLAN_ATTESTATION_TYPE) + ")"


@dataclass(frozen=True)
class SimulationContext:
    """What the signer will send, plus the decision metadata of the step's PRE_STEP snapshot."""

    executor: str  # eth_call `from`: the operator address the signer signs with
    target: str  # the module's mandate executor contract (PlanAttestedExecutor)
    attestation: Mapping[str, Any]  # the PlanAttestation message, EIP-712 field names
    attestation_signature: bytes
    policy_version: bytes
    snapshot_block: int
    # Required for PAY and REFILL; the PaymentApproval message and its wire-format signature.
    approval: Mapping[str, Any] | None = None
    approver_signature: bytes = b""


def _struct(fields: Sequence[Mapping[str, str]], message: Mapping[str, Any]) -> tuple[Any, ...]:
    def coerce(kind: str, value: Any) -> Any:
        if kind == "bytes32[]":
            return [coerce("bytes32", item) for item in value]
        if kind == "bytes32" and isinstance(value, str):
            return bytes.fromhex(value.removeprefix("0x"))
        return value

    return tuple(coerce(f["type"], message[f["name"]]) for f in fields)


def build_calldata(step: PlanStep, ctx: SimulationContext) -> bytes:
    """ABI calldata of the executor function for this step, as the signer sends it."""

    attestation = _struct(PLAN_ATTESTATION_TYPE, ctx.attestation)
    types: list[str]
    args: list[Any]
    if step.action in (Action.PAY, Action.REFILL):
        if ctx.approval is None:
            raise ValueError(f"a {step.action} step needs the approval it was planned with")
        types = [_APPROVAL, "bytes", "bytes32"]
        args = [_struct(PAYMENT_APPROVAL_TYPE, ctx.approval), ctx.approver_signature, step.step_id]
        if step.action is Action.PAY:
            # Fiat payment plans use the fresh-quote amount while the approval carries its cap.
            types, args = [*types, "uint256"], [*args, int(step.amount)]
        else:
            types, args = [*types, "address", "uint256"], [*args, step.to, int(step.amount)]
    elif step.action in (Action.SUPPLY, Action.WITHDRAW):
        # attestation[1] is requestId (0x0 for a liquidity plan), as the executor expects.
        types, args = (
            ["bytes32", "bytes32", "uint256"],
            [attestation[1], step.step_id, int(step.amount)],
        )
    else:
        raise ValueError(f"{step.action} steps cannot be simulated")
    types = [*types, _ATTESTATION, "bytes"]
    args = [*args, attestation, ctx.attestation_signature]
    name = step.action.lower()
    return error_selector(f"{name}({','.join(types)})") + encode(types, args)


def _revert_data(error: RpcResponseError) -> bytes | None:
    """Revert data when the node reports a revert; None for any other JSON-RPC error."""

    if isinstance(error.data, str):
        try:
            return bytes.fromhex(error.data.removeprefix("0x"))
        except ValueError:
            return b""  # a revert whose data the node mangled is still a revert
    return b"" if "revert" in str(error).lower() else None


async def simulate(rpc: RpcClient, step: PlanStep, ctx: SimulationContext) -> Decision:
    """`eth_call` the step from the executor at `latest`; revert or RPC failure is BLOCK."""

    call = {"from": ctx.executor, "to": ctx.target, "data": "0x" + build_calldata(step, ctx).hex()}
    codes: tuple[PolicyReasonCode, ...] = ()
    observed = None
    try:
        # An eth_call to an address without code succeeds with 0x, which must not read as ALLOW.
        if await rpc.call("eth_getCode", [ctx.target, "latest"]) in (None, "", "0x"):
            raise RpcError("no code at target")
        # A revert is authoritative: another provider must not turn it into ALLOW.
        await rpc.call(
            "eth_call",
            [call, "latest"],
            is_final=lambda error: _revert_data(error) is not None,
        )
    except RpcResponseError as error:
        revert = _revert_data(error)
        if revert is None:
            codes, observed = (PolicyReasonCode.SIMULATION_UNAVAILABLE,), f"JSON-RPC {error.code}"
        else:
            codes, observed = decode_revert(revert), "0x" + revert[:4].hex()
    except RpcError as error:
        codes, observed = (PolicyReasonCode.SIMULATION_UNAVAILABLE,), type(error).__name__
    checks = (
        [Check(name="simulation", passed=True, code=None, expected=None, observed=None)]
        if not codes
        else [
            Check(
                name="simulation", passed=False, code=code, expected="no revert", observed=observed
            )
            for code in codes
        ]
    )
    outcome, primary = aggregate(codes)
    return Decision(
        decision=outcome,
        primary=primary,
        codes=list(codes),
        warnings=[],
        checks=checks,
        stage="SIMULATION",
        step_seq=step.seq,
        policy_version=ctx.policy_version,
        snapshot_block=ctx.snapshot_block,
    )


async def record_validation(pool: asyncpg.Pool, plan_id: UUID, decision: Decision) -> None:
    """Append the decision to `validations`; a failed write propagates so the step is not signed."""

    await pool.execute(
        "INSERT INTO validations (id, plan_id, step_seq, stage, decision, primary_code,"
        " reason_codes, warnings, checks, policy_version, snapshot_block)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11)",
        uuid7(),
        plan_id,
        decision.step_seq,
        decision.stage,
        decision.decision,
        decision.primary,
        [str(code) for code in decision.codes],
        [str(code) for code in decision.warnings],
        json.dumps([check.model_dump(mode="json") for check in decision.checks]),
        decision.policy_version,
        decision.snapshot_block,
    )
