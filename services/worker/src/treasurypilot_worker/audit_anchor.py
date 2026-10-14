"""Daily publication of PostgreSQL audit heads to AuditRootAnchor."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

from web3 import Account, Web3

from treasurypilot_worker.locks import create_worker_pool

logger = logging.getLogger(__name__)

ANCHOR_ABI = [
    {
        "inputs": [
            {"internalType": "bytes32", "name": "orgId", "type": "bytes32"},
            {"internalType": "uint64", "name": "utcDay", "type": "uint64"},
        ],
        "name": "isAnchored",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "orgId", "type": "bytes32"},
            {"internalType": "uint64", "name": "utcDay", "type": "uint64"},
        ],
        "name": "rootAt",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "orgId", "type": "bytes32"},
            {"internalType": "uint64", "name": "utcDay", "type": "uint64"},
            {"internalType": "bytes32", "name": "root", "type": "bytes32"},
        ],
        "name": "anchorRoot",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


class AuditRootChain(Protocol):
    def anchor_or_confirm(self, org_id: UUID, utc_day: int, root: bytes) -> bool: ...


async def fetch_audit_heads(database_url: str) -> list[Mapping[str, object]]:
    """Read every organization head from one read-only repeatable-read snapshot."""

    pool = await create_worker_pool(database_url)
    try:
        async with pool.acquire() as connection:
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                return list(
                    await connection.fetch(
                        """
                        SELECT org_id, last_hash, statement_timestamp() AS snapshot_at
                        FROM audit_heads ORDER BY org_id
                        """
                    )
                )
    finally:
        await pool.close()


def publish_snapshot(
    heads: Sequence[Mapping[str, object]], *, utc_day: int, chain: AuditRootChain
) -> int:
    """Publish the exact captured hashes; identical retries are successful no-ops."""

    published = 0
    for head in heads:
        org_id = head["org_id"]
        root = head["last_hash"]
        if not isinstance(org_id, UUID) or not isinstance(root, bytes) or len(root) != 32:
            raise ValueError("invalid audit head snapshot row")
        if chain.anchor_or_confirm(org_id, utc_day, root):
            published += 1
    return published


class Web3AuditRootChain:
    """Submit roots with the dedicated configured publisher account."""

    def __init__(
        self, *, rpc_url: str, expected_chain_id: int, contract_address: str, private_key: str
    ) -> None:
        self.web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))
        actual_chain_id = self.web3.eth.chain_id
        if actual_chain_id != expected_chain_id:
            raise RuntimeError(
                f"audit anchor RPC chain id mismatch: expected {expected_chain_id}, got {actual_chain_id}"
            )
        self.account = Account.from_key(private_key)
        if not Web3.is_address(contract_address):
            raise ValueError("invalid audit anchor contract address")
        self.contract = self.web3.eth.contract(
            address=Web3.to_checksum_address(contract_address), abi=ANCHOR_ABI
        )

    def anchor_or_confirm(self, org_id: UUID, utc_day: int, root: bytes) -> bool:
        # Hash UUID bytes to an opaque, stable, non-PII contract key.
        contract_org_id = Web3.keccak(org_id.bytes)
        already_anchored = self.contract.functions.isAnchored(contract_org_id, utc_day).call()
        if already_anchored:
            # A chain can advance after the first daily publication. Never compare
            # today's head with the immutable root from an earlier attempt.
            return False

        nonce = self.web3.eth.get_transaction_count(self.account.address, "pending")
        function = self.contract.functions.anchorRoot(contract_org_id, utc_day, root)
        transaction = function.build_transaction(
            {
                "from": self.account.address,
                "nonce": nonce,
                "chainId": self.web3.eth.chain_id,
                "gas": function.estimate_gas({"from": self.account.address}),
                "gasPrice": self.web3.eth.gas_price,
            }
        )
        signed = self.account.sign_transaction(transaction)
        tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if cast(Mapping[str, object], receipt).get("status") != 1:
            raise RuntimeError(f"audit anchor transaction reverted: {tx_hash.hex()}")
        confirmed = bytes(self.contract.functions.rootAt(contract_org_id, utc_day).call())
        if confirmed != root:
            raise RuntimeError(
                "confirmed on-chain audit root does not match captured database head"
            )
        return True


async def publish_daily_audit_roots(
    database_url: str,
    chain: AuditRootChain,
    *,
    now: datetime | None = None,
    heads_reader: Callable[[str], Awaitable[list[Mapping[str, object]]]] = fetch_audit_heads,
) -> int:
    """Capture heads once and publish them under the UTC day of that snapshot."""

    heads = await heads_reader(database_url)
    if now is not None:
        captured_at = now
    elif heads:
        raw_timestamps = [head.get("snapshot_at") for head in heads]
        if any(not isinstance(value, datetime) for value in raw_timestamps):
            raise ValueError("database audit snapshot timestamp is invalid")
        timestamps = {value for value in raw_timestamps if isinstance(value, datetime)}
        if len(timestamps) != 1:
            raise ValueError("audit head rows do not share one database snapshot timestamp")
        captured_at = next(iter(timestamps))
    else:
        # An organization is created with its head, so an empty table means there is
        # nothing to publish. Still validate the caller's current timestamp below.
        captured_at = datetime.now(UTC)
    if captured_at.utcoffset() is None:
        raise ValueError("audit anchor timestamp must be timezone-aware")
    utc_day = int(captured_at.astimezone(UTC).timestamp()) // 86_400
    return publish_snapshot(heads, utc_day=utc_day, chain=chain)
