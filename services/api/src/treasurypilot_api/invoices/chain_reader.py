"""JSON-RPC implementation of ``ApprovalChainReader`` over the configured chain RPC URLs."""

from __future__ import annotations

from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import keccak

from treasurypilot_api.treasury.safe import RpcSafeVerifier

_IS_APPROVER = keccak(text="isApprover(address)")[:4]
_IS_VALID_SIGNATURE = keccak(text="isValidSignature(bytes32,bytes)")[:4]
ERC1271_MAGIC = bytes.fromhex("1626ba7e")


class RpcApprovalChainReader:
    """Failover and revert handling come from ``RpcSafeVerifier.call``; ``RpcUnavailable`` means 503."""

    def __init__(self, rpc: RpcSafeVerifier) -> None:
        self._rpc = rpc

    async def _eth_call(self, chain_id: int, to: str, data: bytes) -> bytes:
        result = await self._rpc.call(
            chain_id,
            "eth_call",
            [{"to": to, "data": "0x" + data.hex()}, "latest"],
            on_revert="0x",
        )
        return bytes.fromhex(str(result).removeprefix("0x"))

    async def is_approver(self, *, chain_id: int, module: str, signer: str) -> bool:
        data = _IS_APPROVER + abi_encode(["address"], [signer])
        raw = await self._eth_call(chain_id, module, data)
        return len(raw) == 32 and bool(abi_decode(["bool"], raw)[0])

    async def is_valid_erc1271_signature(
        self, *, chain_id: int, wallet: str, digest: bytes, signature: bytes
    ) -> bool:
        data = _IS_VALID_SIGNATURE + abi_encode(["bytes32", "bytes"], [digest, signature])
        # Safe reverts on a signature it rejects; that is "invalid", not an outage.
        raw = await self._eth_call(chain_id, wallet, data)
        return raw[:4] == ERC1271_MAGIC
