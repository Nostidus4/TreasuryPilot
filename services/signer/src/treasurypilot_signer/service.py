from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from eth_abi import decode
from eth_abi.exceptions import DecodingError
from eth_account.signers.local import LocalAccount
from eth_hash.auto import keccak

from treasurypilot_core.eip712 import (
    PAY,
    REFILL,
    SUPPLY,
    WITHDRAW,
    plan_hash,
)
from treasurypilot_core.policy.attestation import (
    verify_attestation,
)
from treasurypilot_signer.config import Settings
from treasurypilot_signer.models import SignRequest, SignResponse
from treasurypilot_signer.rpc import RpcFailure
from treasurypilot_signer.store import NonceAlreadyBound, StepAlreadyUsed

_APPROVAL = "(bytes32,bytes32,bytes32,address,address,address,address,uint256,uint256,uint64,uint64,bytes32,uint64)"
_ATTESTATION = "(bytes32,bytes32,bytes32[],bytes32,address,uint64,uint256,bytes32)"
_MANDATE_OUTPUTS = [
    "uint64",
    "uint64",
    "uint64",
    "uint32",
    "address",
    "address",
    "(uint128,uint128)",
    "(uint128,uint128)",
    "uint32",
    "(uint128,uint128)",
]
_FUNCTIONS: dict[int, tuple[str, Sequence[str]]] = {
    PAY: ("pay", (_APPROVAL, "bytes", "bytes32", _ATTESTATION, "bytes")),
    REFILL: (
        "refill",
        (_APPROVAL, "bytes", "bytes32", "address", "uint256", _ATTESTATION, "bytes"),
    ),
    SUPPLY: ("supply", ("bytes32", "bytes32", "uint256", _ATTESTATION, "bytes")),
    WITHDRAW: ("withdraw", ("bytes32", "bytes32", "uint256", _ATTESTATION, "bytes")),
}
_ACTION_NAMES = {"PAY": PAY, "REFILL": REFILL, "SUPPLY": SUPPLY, "WITHDRAW": WITHDRAW}


class SignerFault(Exception):
    def __init__(self, code: str, status_code: int = 422) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class Store(Protocol):
    async def reserve(
        self,
        *,
        attestation_nonce: int,
        plan_hash: bytes,
        step_id: bytes,
        payload_hash: bytes,
        executor: bytes,
        pending_nonce: int,
    ) -> Any: ...


class Rpc(Protocol):
    async def call(self, method: str, params: Sequence[Any]) -> Any: ...


def _bytes32(value: Any) -> bytes:
    if isinstance(value, bytes) and len(value) == 32:
        return value
    if isinstance(value, str) and value.startswith("0x") and len(value) == 66:
        result = bytes.fromhex(value[2:])
        if len(result) == 32:
            return result
    raise ValueError("invalid bytes32")


def _address(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 42 or not value.startswith("0x"):
        raise ValueError("invalid address")
    bytes.fromhex(value[2:])
    return value.lower()


def _action(step: Mapping[str, Any]) -> int:
    value = step["action"]
    if isinstance(value, str) and not value.isdecimal():
        return int(_ACTION_NAMES[value.upper()])
    return int(value)


def _check_embedded_attestation(encoded: Sequence[Any], message: Mapping[str, Any]) -> None:
    expected = (
        _bytes32(message["planHash"]),
        _bytes32(message["requestId"]),
        [_bytes32(item) for item in message["stepIds"]],
        _bytes32(message["policyVersion"]),
        _address(message["executor"]),
        int(message["validUntil"]),
        int(message["nonce"]),
        _bytes32(message["evidenceDigest"]),
    )
    actual = (
        bytes(encoded[0]),
        bytes(encoded[1]),
        [bytes(item) for item in encoded[2]],
        bytes(encoded[3]),
        str(encoded[4]).lower(),
        int(encoded[5]),
        int(encoded[6]),
        bytes(encoded[7]),
    )
    if actual != expected:
        raise SignerFault("PAYLOAD_MISMATCH")


def _check_payload(request: SignRequest, step: Mapping[str, Any]) -> None:
    try:
        action = _action(step)
    except (KeyError, TypeError, ValueError) as error:
        raise SignerFault("PAYLOAD_MISMATCH") from error
    if action not in _FUNCTIONS:
        raise SignerFault("PAYLOAD_MISMATCH")
    function, abi_types = _FUNCTIONS[action]
    signature = f"{function}({','.join(abi_types)})".encode()
    calldata = bytes.fromhex(request.payload.data[2:])
    if len(calldata) < 4 or calldata[:4] != keccak(signature)[:4]:
        raise SignerFault("PAYLOAD_MISMATCH")
    try:
        args = decode(list(abi_types), calldata[4:], strict=True)
        typed_data = request.typed_data
        message = typed_data["message"]
        step_id = _bytes32(step["stepId"])
        step_amount = int(step["amount"])
        step_from = _address(step["from"])
        step_to = _address(step["to"])
        step_asset = _address(step["asset"])
        request_id = _bytes32(request.plan["requestId"])
        module = _address(request.plan["treasury"])
    except (KeyError, IndexError, TypeError, ValueError, DecodingError, OverflowError) as error:
        raise SignerFault("PAYLOAD_MISMATCH") from error

    checks: Sequence[bool]
    if action in (PAY, REFILL):
        approval = args[0]
        # PaymentApproval: requestId, invoiceHash, fingerprint, treasury, payingWallet,
        # asset, payee, amount, earlyAmount, earlyPayBy, deadline, termsHash, expiry.
        if action == PAY:
            checks = (
                bytes(approval[0]) == request_id,
                _address(approval[3]) == module,
                _address(approval[4]) == step_from,
                _address(approval[5]) == step_asset,
                bytes(args[2]) == step_id,
                int(approval[7]) == step_amount,
                _address(approval[6]) == step_to,
            )
        else:
            # REFILL transfers from the module's Safe T to an operational wallet. Its
            # PaymentApproval.amount describes the later invoice payment, while the refill
            # amount is a separate argument.
            checks = (
                bytes(approval[0]) == request_id,
                _address(approval[3]) == module,
                _address(approval[4]) == step_to,
                _address(approval[5]) == step_asset,
                bytes(args[2]) == step_id,
                _address(args[3]) == step_to,
                int(args[4]) == step_amount,
            )
        attestation_position = 3 if action == PAY else 5
    else:
        checks = (
            bytes(args[0]) == request_id,
            bytes(args[1]) == step_id,
            int(args[2]) == step_amount,
        )
        attestation_position = 3
    if not all(checks):
        raise SignerFault("PAYLOAD_MISMATCH")
    _check_embedded_attestation(args[attestation_position], message)
    if args[-1] != bytes.fromhex(request.signature[2:]):
        raise SignerFault("PAYLOAD_MISMATCH")


class SigningService:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        rpc: Rpc,
        resolve_account: Callable[[str], LocalAccount],
    ) -> None:
        self._settings = settings
        self._store = store
        self._rpc = rpc
        self._resolve_account = resolve_account

    async def sign_and_send(self, request: SignRequest) -> SignResponse:
        plan = request.plan
        try:
            chain_id = int(plan["chainId"])
            treasury = _address(plan["treasury"])
            steps = plan["steps"]
            step = next(item for item in steps if int(item["seq"]) == request.step_seq)
            typed_data = request.typed_data
            attestation_message = typed_data["message"]
        except (KeyError, TypeError, ValueError, StopIteration) as error:
            raise SignerFault("PAYLOAD_MISMATCH") from error
        if chain_id not in self._settings.allowed_chain_ids:
            raise SignerFault("CHAIN_NOT_ALLOWED")
        treasury_id = request.resolved_treasury_id
        if treasury_id is None:
            raise SignerFault("PAYLOAD_MISMATCH")

        try:
            reason = verify_attestation(
                typed_data,
                bytes.fromhex(request.signature[2:]),
                plan=plan,
                executor=str(attestation_message["executor"]),
                trusted_signers=self._settings.trusted_policy_signers,
                now=datetime.now(UTC),
                # The database check below binds this nonce atomically with the step-use row.
                bind_nonce=lambda _nonce, plan_hash_value: plan_hash_value,
            )
        except Exception as error:
            raise SignerFault("ATTESTATION_INVALID") from error
        if reason is not None:
            code = str(reason)
            if code not in {"ATTESTATION_INVALID", "ATTESTATION_EXPIRED", "NONCE_REUSED"}:
                code = "ATTESTATION_INVALID"
            raise SignerFault(code)

        action = _action(step)
        _check_payload(request, step)
        try:
            account = self._resolve_account(treasury_id)
        except Exception as error:
            raise SignerFault("SIGNER_KEY_UNAVAILABLE", 503) from error
        if account.address.lower() != str(attestation_message["executor"]).lower():
            raise SignerFault("ATTESTATION_INVALID")

        try:
            actual_chain_id = int(str(await self._rpc.call("eth_chainId", [])), 16)
            if actual_chain_id != chain_id:
                raise SignerFault("CHAIN_NOT_ALLOWED")
            module_code = await self._rpc.call("eth_getCode", [treasury, "latest"])
            if module_code in (None, "0x", "0x0"):
                raise SignerFault("PAYLOAD_MISMATCH")
            mandate_call = "0x" + keccak(b"mandate()")[:4].hex()
            mandate_data = await self._rpc.call(
                "eth_call", [{"to": treasury, "data": mandate_call}, "latest"]
            )
            mandate = decode(_MANDATE_OUTPUTS, bytes.fromhex(mandate_data[2:]), strict=True)
            expected_target = str(mandate[4]).lower()
            if request.payload.to.lower() != expected_target:
                raise SignerFault("PAYLOAD_MISMATCH")
            if action == REFILL:
                safe_t_selector = "0x" + keccak(b"safeT()")[:4].hex()
                safe_t_data = await self._rpc.call(
                    "eth_call", [{"to": treasury, "data": safe_t_selector}, "latest"]
                )
                safe_t = _address("0x" + str(safe_t_data)[-40:])
                if safe_t != _address(step["from"]):
                    raise SignerFault("PAYLOAD_MISMATCH")

            call = {
                "from": account.address,
                "to": request.payload.to,
                "value": "0x0",
                "data": request.payload.data,
            }
            await self._rpc.call("eth_call", [call, "latest"])
            gas_estimate = int(str(await self._rpc.call("eth_estimateGas", [call])), 16)
            gas_limit = max(gas_estimate, (gas_estimate * 120 + 99) // 100)
            fees = request.fees
            accepted_cap = int(plan.get("feeCapWei", fees.fee_cap_wei))
            fee_cap = min(accepted_cap, fees.fee_cap_wei)
            if (
                fees.max_fee_per_gas < fees.max_priority_fee_per_gas
                or gas_limit * fees.max_fee_per_gas > fee_cap
            ):
                raise SignerFault("FEE_CAP_EXCEEDED")
            pending_nonce = int(
                str(await self._rpc.call("eth_getTransactionCount", [account.address, "pending"])),
                16,
            )
        except SignerFault:
            raise
        except RpcFailure as error:
            if error.reverted:
                raise SignerFault("SIMULATION_REVERTED") from error
            raise SignerFault("CHAIN_RPC_UNAVAILABLE", 503) from error
        except (ValueError, TypeError, DecodingError) as error:
            raise SignerFault("PAYLOAD_MISMATCH") from error

        try:
            plan_hash_bytes = bytes(
                plan_hash(plan["requestId"], plan["treasury"], plan["chainId"], plan["steps"])
            )
            step_id = _bytes32(step["stepId"])
            payload_hash = keccak(
                bytes.fromhex(request.payload.to[2:]) + bytes.fromhex(request.payload.data[2:])
            )
            reserved = await self._store.reserve(
                attestation_nonce=int(attestation_message["nonce"]),
                plan_hash=plan_hash_bytes,
                step_id=step_id,
                payload_hash=payload_hash,
                executor=bytes.fromhex(account.address[2:]),
                pending_nonce=pending_nonce,
            )
        except NonceAlreadyBound as error:
            raise SignerFault("NONCE_REUSED", 409) from error
        except StepAlreadyUsed as error:
            raise SignerFault("PAYLOAD_MISMATCH", 409) from error

        transaction = {
            "chainId": chain_id,
            "nonce": reserved.transaction_nonce,
            "to": request.payload.to,
            "value": 0,
            "data": request.payload.data,
            "gas": gas_limit,
            "maxFeePerGas": fees.max_fee_per_gas,
            "maxPriorityFeePerGas": fees.max_priority_fee_per_gas,
            "type": 2,
        }
        signed = account.sign_transaction(transaction)
        raw_transaction = cast(
            bytes,
            getattr(signed, "raw_transaction", getattr(signed, "rawTransaction", b"")),
        )
        try:
            tx_hash = await self._rpc.call(
                "eth_sendRawTransaction", ["0x" + bytes(raw_transaction).hex()]
            )
        except RpcFailure as error:
            if error.already_known:
                tx_hash = "0x" + keccak(bytes(raw_transaction)).hex()
            else:
                raise SignerFault("BROADCAST_FAILED", 503) from error
        return SignResponse(
            txHash=tx_hash, nonce=reserved.transaction_nonce, **{"from": account.address}
        )
