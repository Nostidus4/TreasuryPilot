from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, Protocol

from eth_abi import encode
from eth_account.signers.local import LocalAccount
from eth_hash.auto import keccak

from treasurypilot_signer.config import Settings
from treasurypilot_signer.keys import ExecutorKeyNotConfigured, SentinelKey
from treasurypilot_signer.rpc import RpcFailure
from treasurypilot_signer.service import SignerFault, _rpc_hex, _rpc_quantity

_PAUSE = keccak(b"pause()")[:4]
_STATUS = "0x" + keccak(b"status()")[:4].hex()
_PAUSED = 1
_EXEC = keccak(
    b"execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)"
)[:4]
_ZERO = "0x" + "00" * 20


class Rpc(Protocol):
    async def call(self, method: str, params: Sequence[Any]) -> Any: ...


def build_pause_transaction(sentinel: str, module: str) -> bytes:
    """GuardianSafe.execTransaction(module, 0, pause(), CALL, 0, 0, 0, 0, 0, sig).

    The only calldata this service can produce. The signature is the Safe's "approved by
    msg.sender" form (v=1), valid because the sentinel is an owner of the 1-of-N guardian Safe.
    """
    approval = bytes(12) + bytes.fromhex(sentinel[2:]) + bytes(32) + b"\x01"
    return _EXEC + encode(
        [
            "address",
            "uint256",
            "bytes",
            "uint8",
            "uint256",
            "uint256",
            "uint256",
            "address",
            "address",
            "bytes",
        ],
        [module, 0, _PAUSE, 0, 0, 0, 0, _ZERO, _ZERO, approval],
    )


class SentinelService:
    def __init__(self, settings: Settings, rpc: Rpc, key: SentinelKey) -> None:
        self._settings = settings
        self._rpc = rpc
        self._key = key
        self._lock = asyncio.Lock()  # one pending nonce at a time

    def _account(self) -> LocalAccount:
        try:
            return self._key.load()
        except ExecutorKeyNotConfigured as error:
            raise SignerFault("NOT_CONFIGURED", 503) from error
        except Exception as error:
            raise SignerFault("SIGNER_KEY_UNAVAILABLE", 503) from error

    def address(self) -> str:
        return self._account().address

    async def pause(self, treasury_id: str) -> dict[str, Any]:
        target = self._settings.sentinel_targets.get(treasury_id.lower())
        if target is None:
            raise SignerFault("NOT_CONFIGURED", 503)
        account = self._account()
        safe, module = target["guardianSafe"], target["module"]
        data = build_pause_transaction(account.address, module)
        call = {"from": account.address, "to": safe, "value": "0x0", "data": "0x" + data.hex()}
        async with self._lock:
            try:
                status = _rpc_quantity(
                    await self._rpc.call("eth_call", [{"to": module, "data": _STATUS}, "pending"])
                )
                if status == _PAUSED:
                    return {"txHash": None, "alreadyPaused": True}
                chain_id = _rpc_quantity(await self._rpc.call("eth_chainId", []))
                if chain_id not in self._settings.allowed_chain_ids:
                    raise SignerFault("CHAIN_NOT_ALLOWED")
                await self._rpc.call("eth_call", [call, "latest"])
                gas = _rpc_quantity(await self._rpc.call("eth_estimateGas", [call]))
                max_fee = 2 * _rpc_quantity(await self._rpc.call("eth_gasPrice", []))
                tip = min(
                    max_fee, _rpc_quantity(await self._rpc.call("eth_maxPriorityFeePerGas", []))
                )
                nonce = _rpc_quantity(
                    await self._rpc.call("eth_getTransactionCount", [account.address, "pending"])
                )
                transaction: dict[str, Any] = {
                    "chainId": chain_id,
                    "nonce": nonce,
                    "to": safe,
                    "value": 0,
                    "data": data,
                    "gas": gas * 12 // 10,
                    "maxFeePerGas": max_fee,
                    "maxPriorityFeePerGas": tip,
                    "type": 2,
                }
                signed = account.sign_transaction(transaction)
                raw = bytes(signed.raw_transaction)
                tx_hash = _rpc_hex(
                    await self._rpc.call("eth_sendRawTransaction", ["0x" + raw.hex()]), min_bytes=32
                )
            except SignerFault:
                raise
            except RpcFailure as error:
                if error.reverted:
                    raise SignerFault("SIMULATION_REVERTED") from error
                raise SignerFault("CHAIN_RPC_UNAVAILABLE", 503) from error
        return {"txHash": tx_hash, "alreadyPaused": False}
