from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from eth_abi import decode
from eth_abi.exceptions import DecodingError
from eth_hash.auto import keccak
from eth_utils import to_checksum_address

from treasurypilot_core.eip712 import (
    PAY,
    REFILL,
    SUPPLY,
    SWAP_IN,
    WITHDRAW,
    plan_hash,
)
from treasurypilot_core.policy.attestation import (
    verify_attestation,
)
from treasurypilot_signer.config import Settings
from treasurypilot_signer.keys import ExecutorKeyNotConfigured
from treasurypilot_signer.kms import ExecutorSigner
from treasurypilot_signer.models import SignRequest, SignResponse
from treasurypilot_signer.rpc import RpcFailure
from treasurypilot_signer.store import NonceAlreadyBound, StepAlreadyUsed

logger = logging.getLogger(__name__)

_APPROVAL = "(bytes32,bytes32,bytes32,address,address,address,address,uint256,uint256,uint64,uint64,bytes32,uint64,bool)"
_ATTESTATION = "(bytes32,bytes32,bytes32[],uint256[],bytes32,address,uint64,uint256,bytes32)"
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
    PAY: ("pay", (_APPROVAL, "bytes", "bytes32", "uint256", _ATTESTATION, "bytes")),
    REFILL: (
        "refill",
        (_APPROVAL, "bytes", "bytes32", "address", "address", "uint256", _ATTESTATION, "bytes"),
    ),
    SUPPLY: ("supply", ("bytes32", "bytes32", "uint256", _ATTESTATION, "bytes")),
    WITHDRAW: ("withdraw", ("bytes32", "bytes32", "uint256", _ATTESTATION, "bytes")),
    # The executor's swapForGas carries no attestation: the signer checks it against the plan.
    SWAP_IN: ("swapForGas", ("bytes32", "uint256", "uint256")),
}
_ACTION_NAMES = {
    "PAY": PAY,
    "REFILL": REFILL,
    "SUPPLY": SUPPLY,
    "WITHDRAW": WITHDRAW,
    "SWAP": SWAP_IN,
}


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

    async def record_signed(
        self, *, attestation_nonce: int, step_id: bytes, tx_hash: str, raw_transaction: bytes
    ) -> None: ...

    async def release(
        self, *, attestation_nonce: int, step_id: bytes, executor: bytes, transaction_nonce: int
    ) -> None: ...


class Rpc(Protocol):
    async def call(self, method: str, params: Sequence[Any]) -> Any: ...


def _rpc_hex(value: Any, *, min_bytes: int = 0, quantity: bool = False) -> str:
    """Validate an RPC result as 0x-prefixed hex; a malformed node reply is an RPC fault."""
    if (
        not isinstance(value, str)
        or not value.startswith("0x")
        or len(value) < 3
        or (not quantity and len(value) % 2)
        or len(value) - 2 < 2 * min_bytes
    ):
        raise SignerFault("CHAIN_RPC_UNAVAILABLE", 503)
    try:
        int(value[2:], 16)
    except ValueError as error:
        raise SignerFault("CHAIN_RPC_UNAVAILABLE", 503) from error
    return value


def _rpc_quantity(value: Any) -> int:
    return int(_rpc_hex(value, quantity=True), 16)


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
        [int(item) for item in message["stepAmounts"]],
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
        [int(item) for item in encoded[3]],
        bytes(encoded[4]),
        str(encoded[5]).lower(),
        int(encoded[6]),
        int(encoded[7]),
        bytes(encoded[8]),
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
    if action == SWAP_IN:
        # shortcut: minOut/venue come from the unattested plan.swaps (outside plan_hash); fine for
        # the test router only, production needs minOut in the attestation or an on-chain floor.
        swap = request.plan.get("swaps", {}).get(step["stepId"])
        if swap is None or swap.get("venue") != "TEST_ROUTER" or int(swap["minOut"]) <= 0:
            raise SignerFault("PAYLOAD_MISMATCH")
        if not (
            bytes(args[0]) == step_id
            and int(args[1]) == step_amount
            and int(args[2]) == int(swap["minOut"])
        ):
            raise SignerFault("PAYLOAD_MISMATCH")
        return
    if action in (PAY, REFILL):
        approval = args[0]
        # PaymentApproval: requestId, invoiceHash, fingerprint, treasury, payingWallet,
        # asset, payee, amount, earlyAmount, earlyPayBy, deadline, termsHash, expiry, isFiat.
        if action == PAY:
            checks = (
                bytes(approval[0]) == request_id,
                _address(approval[3]) == module,
                _address(approval[4]) == step_from,
                _address(approval[5]) == step_asset,
                bytes(args[2]) == step_id,
                _address(approval[6]) == step_to,
                int(args[3]) == step_amount,
                # Fiat-quoted approvals cap the payment; otherwise it must be exact.
                step_amount <= int(approval[7])
                if approval[13]
                else step_amount == int(approval[7]),
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
                _address(args[3]) == step_from,
                _address(args[4]) == step_to,
                int(args[5]) == step_amount,
            )
        attestation_position = 4 if action == PAY else 6
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
        resolve_account: Callable[[str], ExecutorSigner],
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
        except (ValueError, KeyError, TypeError) as error:  # binascii.Error is a ValueError
            raise SignerFault("ATTESTATION_INVALID") from error
        except Exception as error:
            logger.exception("attestation verification failed unexpectedly")
            raise SignerFault("SIGNER_INTERNAL_ERROR", 500) from error
        if reason is not None:
            code = str(reason)
            if code not in {"ATTESTATION_INVALID", "ATTESTATION_EXPIRED", "NONCE_REUSED"}:
                code = "ATTESTATION_INVALID"
            raise SignerFault(code)

        action = _action(step)
        _check_payload(request, step)
        try:
            account = self._resolve_account(treasury_id)
        except ExecutorKeyNotConfigured as error:
            raise SignerFault("NOT_CONFIGURED", 503) from error
        except Exception as error:
            raise SignerFault("SIGNER_KEY_UNAVAILABLE", 503) from error
        if account.address.lower() != str(attestation_message["executor"]).lower():
            raise SignerFault("ATTESTATION_INVALID")

        try:
            actual_chain_id = _rpc_quantity(await self._rpc.call("eth_chainId", []))
            if actual_chain_id != chain_id:
                raise SignerFault("CHAIN_NOT_ALLOWED")
            module_code = _rpc_hex(
                await self._rpc.call("eth_getCode", [treasury, "latest"]), quantity=True
            )
            if module_code in ("0x", "0x0"):
                raise SignerFault("PAYLOAD_MISMATCH")
            mandate_call = "0x" + keccak(b"mandate()")[:4].hex()
            mandate_data = await self._rpc.call(
                "eth_call", [{"to": treasury, "data": mandate_call}, "latest"]
            )
            mandate = decode(
                _MANDATE_OUTPUTS, bytes.fromhex(_rpc_hex(mandate_data)[2:]), strict=True
            )
            expected_target = str(mandate[4]).lower()
            if request.payload.to.lower() != expected_target:
                raise SignerFault("PAYLOAD_MISMATCH")
            if action == REFILL:
                # Operational-source refills (contract-allowed via a refill path) are planned by the
                # engine (ENG-L01) but the worker validator and RefillPathSet indexing are not wired,
                # so only Safe T sources are signed.
                safe_t_selector = "0x" + keccak(b"safeT()")[:4].hex()
                safe_t_data = await self._rpc.call(
                    "eth_call", [{"to": treasury, "data": safe_t_selector}, "latest"]
                )
                safe_t = _address("0x" + _rpc_hex(safe_t_data, min_bytes=20)[-40:])
                if safe_t != _address(step["from"]):
                    raise SignerFault("PAYLOAD_MISMATCH")

            call = {
                "from": account.address,
                "to": request.payload.to,
                "value": "0x0",
                "data": request.payload.data,
            }
            await self._rpc.call("eth_call", [call, "latest"])
            gas_estimate = _rpc_quantity(await self._rpc.call("eth_estimateGas", [call]))
            gas_limit = max(gas_estimate, (gas_estimate * 120 + 99) // 100)
            fees = request.fees
            # plan.feeCapWei is outside the attested plan hash and the request's own cap is
            # caller-controlled, so neither may raise the signer's configured ceiling.
            fee_cap = min(
                int(plan.get("feeCapWei", self._settings.max_fee_cap_wei)),
                fees.fee_cap_wei,
                self._settings.max_fee_cap_wei,
            )
            if (
                fees.max_fee_per_gas < fees.max_priority_fee_per_gas
                or gas_limit * fees.max_fee_per_gas > fee_cap
            ):
                raise SignerFault("FEE_CAP_EXCEEDED")
            # Nothing is reserved or signed when the executor cannot pay the worst-case fee.
            # Advisory only: a concurrent send can still drain the balance before broadcast.
            balance = _rpc_quantity(
                await self._rpc.call("eth_getBalance", [account.address, "latest"])
            )
            if balance < gas_limit * fees.max_fee_per_gas:
                raise SignerFault("INSUFFICIENT_GAS")
            pending_nonce = _rpc_quantity(
                await self._rpc.call("eth_getTransactionCount", [account.address, "pending"])
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

        if reserved.raw_transaction is not None:
            # Replay: rebroadcast the original signed bytes and never sign again with new fees.
            raw_transaction = bytes(reserved.raw_transaction)
            tx_hash = str(reserved.tx_hash)
        else:
            transaction = {
                "chainId": chain_id,
                "nonce": reserved.transaction_nonce,
                # eth-account rejects a non-checksummed `to`; the worker sends lowercase hex.
                "to": to_checksum_address(request.payload.to),
                "value": 0,
                "data": request.payload.data,
                "gas": gas_limit,
                "maxFeePerGas": fees.max_fee_per_gas,
                "maxPriorityFeePerGas": fees.max_priority_fee_per_gas,
                "type": 2,
            }
            signed = account.sign_transaction(transaction)
            raw_transaction = bytes(
                cast(
                    bytes,
                    getattr(signed, "raw_transaction", getattr(signed, "rawTransaction", b"")),
                )
            )
            tx_hash = "0x" + keccak(raw_transaction).hex()
            await self._store.record_signed(
                attestation_nonce=int(attestation_message["nonce"]),
                step_id=step_id,
                tx_hash=tx_hash,
                raw_transaction=raw_transaction,
            )
        try:
            await self._rpc.call("eth_sendRawTransaction", ["0x" + raw_transaction.hex()])
        except RpcFailure as error:
            # The hash is deterministic, so "already known" (or, on replay, a mined nonce)
            # means this exact transaction is already with the node.
            if error.already_known or (reserved.replacement and error.nonce_too_low):
                pass
            elif error.rejected and not reserved.replacement:
                # Definitive rejection: free the nonce so later transactions are not stalled.
                await self._store.release(
                    attestation_nonce=int(attestation_message["nonce"]),
                    step_id=step_id,
                    executor=bytes.fromhex(account.address[2:]),
                    transaction_nonce=reserved.transaction_nonce,
                )
                raise SignerFault("BROADCAST_FAILED", 503) from error
            else:
                # Ambiguous (timeout/transport) or replay: keep the reservation; a retry
                # rebroadcasts the stored raw transaction.
                raise SignerFault("BROADCAST_FAILED", 503) from error
        return SignResponse(
            txHash=tx_hash, nonce=reserved.transaction_nonce, **{"from": account.address}
        )
