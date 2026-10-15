"""Publish the EAS payment receipt of a Paid request (REC-005, ADR-018, M11-D8).

A receipt is attested as soon as the request is Paid and its PAY block is finalized; it does not
wait for Finance matching. The receipt carries hashes and addresses only (BR-074). A failure here
only moves the ``chain_attestations`` row to Failed and schedules a retry with backoff: nothing in
this module writes ``payment_requests`` (M11 §11), so the payment stays Paid.

State machine per request: Queued -> Sent (tx broadcast, hash stored) -> Confirmed (UID stored),
with Failed (retried with exponential backoff) reachable from Queued and Sent. Work is claimed with
a short lease (``next_attempt_at`` pushed forward) so overlapping sweeps never double-send and no
database transaction stays open while the chain is called.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

import asyncpg  # type: ignore[import-untyped]
from hexbytes import HexBytes
from web3 import Account, Web3
from web3.exceptions import TransactionNotFound
from web3.types import Nonce

from treasurypilot_core.attestations import (
    ATTESTED_EVENT,
    PAYMENT_RECEIPT_SCHEMA_UID,
    PaymentReceipt,
    verify_payment_finality,
)
from treasurypilot_core.eip712 import digest as eip712_digest
from treasurypilot_worker.audit import append_audit

logger = logging.getLogger(__name__)

BATCH = 25
LEASE = timedelta(minutes=5)  # a crashed run's claim expires after this
NOT_FINAL_RECHECK = timedelta(seconds=30)
SENT_RECHECK = timedelta(seconds=60)
SENT_STALE = timedelta(minutes=15)  # a broadcast never mined by then is retried
BACKOFF_BASE_S = 30
BACKOFF_CAP_S = 3600
_RPC_TIMEOUT = 20.0

EAS_ABI: list[dict[str, Any]] = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "bytes32", "name": "schema", "type": "bytes32"},
                    {
                        "components": [
                            {"internalType": "address", "name": "recipient", "type": "address"},
                            {"internalType": "uint64", "name": "expirationTime", "type": "uint64"},
                            {"internalType": "bool", "name": "revocable", "type": "bool"},
                            {"internalType": "bytes32", "name": "refUID", "type": "bytes32"},
                            {"internalType": "bytes", "name": "data", "type": "bytes"},
                            {"internalType": "uint256", "name": "value", "type": "uint256"},
                        ],
                        "internalType": "struct AttestationRequestData",
                        "name": "data",
                        "type": "tuple",
                    },
                ],
                "internalType": "struct AttestationRequest",
                "name": "request",
                "type": "tuple",
            }
        ],
        "name": "attest",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "payable",
        "type": "function",
    }
]


class ReceiptReverted(RuntimeError):
    """The attest transaction was mined but failed; the next attempt sends a new one."""


class PaymentFinality(Protocol):
    async def is_final(self, chain_id: int, tx_hash: bytes) -> bool:
        """True once the PAY transaction's block is canonical and at or below ``finalized``."""
        ...


@dataclass(frozen=True, slots=True)
class SignedReceipt:
    tx_hash: bytes  # known before broadcast, so it can be stored first
    raw_tx: bytes
    nonce: int


class ReceiptPublisher(Protocol):
    def sign(self, receipt: PaymentReceipt, nonce: int | None) -> SignedReceipt:
        """Sign with the receipt key. ``nonce`` None takes the next one; a resend passes the
        previous nonce so at most one of the two transactions can ever be mined."""
        ...

    def broadcast(self, raw_tx: bytes) -> None:
        """Hand the signed transaction to the node."""
        ...

    def nonce_consumed(self, nonce: int) -> bool:
        """True once the receipt account's mined nonce count has passed ``nonce``."""
        ...

    def pending(self, tx_hash: bytes) -> bool:
        """True while the node still knows the transaction (mempool or mined)."""
        ...

    def result(self, tx_hash: bytes) -> bytes | None:
        """The attestation UID once mined; None while pending; ReceiptReverted if it failed."""
        ...


class RpcPaymentFinality:
    """Finality of the PAY transaction on its own chain, via the worker's RPC clients."""

    def __init__(self, rpc_for_chain: Any) -> None:
        self._rpc_for_chain = rpc_for_chain

    async def is_final(self, chain_id: int, tx_hash: bytes) -> bool:
        rpc = await self._rpc_for_chain(chain_id)
        transaction = await rpc.call("eth_getTransactionReceipt", ["0x" + tx_hash.hex()])
        if not isinstance(transaction, dict) or transaction.get("blockNumber") is None:
            return False
        canonical = await rpc.call("eth_getBlockByNumber", [transaction["blockNumber"], False])
        finalized = await rpc.call("eth_getBlockByNumber", ["finalized", False])
        if not isinstance(canonical, dict) or not isinstance(finalized, dict):
            return False
        try:
            verify_payment_finality(transaction, canonical, finalized)
        except ValueError:
            return False  # not finalized yet, or reorged out: wait; Paid is the tracker's call
        return True


class Web3ReceiptPublisher:
    """Attest on EAS with the dedicated receipt key (the only key this class ever holds)."""

    def __init__(
        self,
        *,
        rpc_url: str,
        expected_chain_id: int,
        eas_address: str,
        schema_uid: str,
        private_key: str,
    ) -> None:
        self.web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))
        actual = self.web3.eth.chain_id
        if actual != expected_chain_id:
            raise RuntimeError(
                f"EAS RPC chain id mismatch: expected {expected_chain_id}, got {actual}"
            )
        if not Web3.is_address(eas_address):
            raise ValueError("invalid EAS contract address")
        self.account = Account.from_key(private_key)
        self.eas = Web3.to_checksum_address(eas_address)
        self.schema_uid = schema_uid.lower()
        self.contract = self.web3.eth.contract(address=self.eas, abi=EAS_ABI)

    def sign(self, receipt: PaymentReceipt, nonce: int | None) -> SignedReceipt:
        # No expiry, non-revocable, no reference, no ETH: the exact tuple of PaymentReceipt.
        request = (
            bytes.fromhex(self.schema_uid[2:]),
            (
                Web3.to_checksum_address(receipt.payee),
                0,
                False,
                bytes(32),
                receipt.encode(),
                0,
            ),
        )
        function = self.contract.functions.attest(request)
        use_nonce = Nonce(
            nonce
            if nonce is not None
            else self.web3.eth.get_transaction_count(self.account.address, "pending")
        )
        transaction = function.build_transaction(
            {
                "from": self.account.address,
                "nonce": use_nonce,
                "chainId": self.web3.eth.chain_id,
                "gas": function.estimate_gas({"from": self.account.address}),
                "gasPrice": self.web3.eth.gas_price,
            }
        )
        signed = self.account.sign_transaction(transaction)
        return SignedReceipt(bytes(signed.hash), bytes(signed.raw_transaction), use_nonce)

    def broadcast(self, raw_tx: bytes) -> None:
        self.web3.eth.send_raw_transaction(raw_tx)

    def nonce_consumed(self, nonce: int) -> bool:
        return int(self.web3.eth.get_transaction_count(self.account.address, "latest")) > nonce

    def pending(self, tx_hash: bytes) -> bool:
        try:
            self.web3.eth.get_transaction(HexBytes(tx_hash))
        except TransactionNotFound:
            return False
        return True

    def result(self, tx_hash: bytes) -> bytes | None:
        try:
            mined = self.web3.eth.get_transaction_receipt(HexBytes(tx_hash))
        except TransactionNotFound:
            return None
        if mined["status"] != 1:
            raise ReceiptReverted("attest transaction reverted")
        topic = Web3.keccak(text=ATTESTED_EVENT)
        schema = bytes.fromhex(self.schema_uid[2:])
        matches = [
            entry
            for entry in mined["logs"]
            if entry["address"].lower() == self.eas.lower()
            and len(entry["topics"]) == 4
            and bytes(entry["topics"][0]) == topic
            and bytes(entry["topics"][3]) == schema
            and bytes(entry["topics"][2])[-20:] == bytes.fromhex(self.account.address[2:])
        ]
        if len(matches) != 1 or len(bytes(matches[0]["data"])) != 32:
            raise ReceiptReverted("attest transaction has no single matching Attested event")
        return bytes(matches[0]["data"])


# Everything the receipt needs, from the request's own rows. The PAY line must be unique and
# equal the invoice amount; the plan and policy version come from the attestation that covered the
# PAY step, the approval hash is the EIP-712 digest of the Valid approval of the current revision.
_FACTS = """
SELECT q.chain_id, q.onchain_request_id, q.invoice_hash, q.amount,
       l.tx_hash, l.to_address, l.amount AS line_amount,
       (SELECT count(*) FROM reconciliation_lines x
          WHERE x.reconciliation_id = r.id AND x.classification = 'EXTERNAL_EXPENSE') AS pay_lines,
       (SELECT at.plan_hash FROM attestations at JOIN operations o ON o.step_id = ANY(at.step_ids)
          WHERE o.id = l.operation_id ORDER BY at.created_at LIMIT 1) AS plan_hash,
       (SELECT at.policy_version FROM attestations at JOIN operations o
          ON o.step_id = ANY(at.step_ids) WHERE o.id = l.operation_id
          ORDER BY at.created_at LIMIT 1) AS policy_version,
       (SELECT a.typed_data FROM approvals a WHERE a.request_id = q.id AND a.status = 'Valid'
          AND a.revision = q.current_revision ORDER BY a.created_at, a.id LIMIT 1)
          AS approval_typed_data
FROM reconciliations r
JOIN payment_requests q ON q.id = r.request_id
JOIN reconciliation_lines l ON l.reconciliation_id = r.id AND l.classification = 'EXTERNAL_EXPENSE'
WHERE r.request_id = $1 AND q.status = 'Paid'
ORDER BY l.block_number DESC NULLS LAST LIMIT 1
"""

# Paid requests whose receipt is missing, or not Confirmed and due. NOT EXISTS keeps a Confirmed
# receipt out; the claim below re-checks the due time atomically.
_DUE = """
SELECT q.id AS request_id, q.org_id FROM payment_requests q
JOIN reconciliations r ON r.request_id = q.id
LEFT JOIN chain_attestations ca ON ca.request_id = q.id
WHERE q.status = 'Paid' AND (ca.id IS NULL OR (ca.status <> 'Confirmed' AND ca.next_attempt_at <= now()))
ORDER BY r.created_at LIMIT $1
"""

_ENSURE = """
INSERT INTO chain_attestations (id, request_id, chain_id, schema_uid)
VALUES (gen_random_uuid(), $1, $2, $3) ON CONFLICT (request_id) DO NOTHING
"""

_CLAIM = """
UPDATE chain_attestations SET next_attempt_at = now() + $2::interval
WHERE request_id = $1 AND status <> 'Confirmed' AND next_attempt_at <= now()
RETURNING id, status, attempts, tx_hash, nonce, updated_at < now() - $3::interval AS stale
"""

_DEFER = """
UPDATE chain_attestations SET next_attempt_at = now() + $2::interval
WHERE id = $1
"""

_SENT = """
UPDATE chain_attestations SET status = 'Sent', tx_hash = $2, nonce = $4, attempts = attempts + 1,
    last_error = NULL, next_attempt_at = now() + $3::interval, updated_at = now()
WHERE id = $1
"""

_FAILED = """
UPDATE chain_attestations SET status = 'Failed', attempts = attempts + $2, last_error = $3,
    next_attempt_at = now() + $4::interval, updated_at = now(),
    nonce = CASE WHEN $5 THEN NULL ELSE nonce END
WHERE id = $1
"""

_CONFIRM = """
UPDATE chain_attestations SET status = 'Confirmed', attestation_uid = $2, last_error = NULL,
    updated_at = now()
WHERE id = $1 AND status <> 'Confirmed'
"""


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(BACKOFF_BASE_S * 2 ** max(attempts, 0), BACKOFF_CAP_S))


def build_receipt(facts: Any) -> PaymentReceipt:
    """Validate the rows and map them to the schema; raises ValueError when they do not fit."""

    if facts["pay_lines"] != 1 or facts["line_amount"] != facts["amount"]:
        raise ValueError("PAY line is not unique or does not equal the invoice amount")
    if facts["approval_typed_data"] is None or facts["plan_hash"] is None:
        raise ValueError("approval or plan attestation evidence is missing")
    typed = facts["approval_typed_data"]
    if isinstance(typed, str):
        typed = json.loads(typed)
    return PaymentReceipt(
        request_id="0x" + bytes(facts["onchain_request_id"]).hex(),
        invoice_hash="0x" + bytes(facts["invoice_hash"]).hex(),
        approval_hash="0x" + eip712_digest(typed).hex(),
        plan_hash="0x" + bytes(facts["plan_hash"]).hex(),
        pay_tx_hash="0x" + bytes(facts["tx_hash"]).hex(),
        payee="0x" + bytes(facts["to_address"]).hex(),
        amount=int(facts["amount"]),
        policy_version="0x" + bytes(facts["policy_version"]).hex(),
    )


async def _fail(
    pool: asyncpg.Pool, row_id: Any, error: BaseException, attempts: int, count: int = 1
) -> None:
    # Type only: RPC errors can echo credentialed URLs. A reverted attest consumed its nonce.
    await pool.execute(
        _FAILED,
        row_id,
        count,
        type(error).__name__,
        backoff(attempts + count - 1),
        isinstance(error, ReceiptReverted),
    )


async def _confirm(
    pool: asyncpg.Pool, org_id: Any, request_id: Any, row_id: Any, uid: bytes
) -> None:
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(_CONFIRM, row_id, uid)
        await connection.execute(
            "UPDATE reconciliations SET eas_uid = $2 WHERE request_id = $1",
            request_id,
            "0x" + uid.hex(),
        )
        await append_audit(
            connection,
            org_id,
            action="reconciliation.receipt_published",
            entity_type="payment_request",
            entity_id=str(request_id),
            data={"easUid": "0x" + uid.hex()},
        )


async def publish_receipts(
    pool: asyncpg.Pool,
    finality: PaymentFinality,
    publisher: ReceiptPublisher,
    *,
    eas_chain_id: int,
    schema_uid: str = PAYMENT_RECEIPT_SCHEMA_UID,
) -> dict[str, int]:
    """One sweep. Per-request failures are recorded and retried; the sweep never raises for them."""

    counts = {"confirmed": 0, "sent": 0, "failed": 0, "waiting": 0}
    schema = bytes.fromhex(schema_uid[2:])
    for due in await pool.fetch(_DUE, BATCH):
        request_id = due["request_id"]
        facts = await pool.fetchrow(_FACTS, request_id)
        if facts is None:
            continue
        await pool.execute(_ENSURE, request_id, eas_chain_id, schema)
        claim = await pool.fetchrow(_CLAIM, request_id, LEASE, SENT_STALE)
        if claim is None:
            continue  # confirmed, leased by another sweep, or not yet due
        row_id, attempts = claim["id"], claim["attempts"]
        persisted = False
        try:
            if claim["status"] == "Sent" and claim["tx_hash"] is not None:
                uid = await asyncio.to_thread(publisher.result, bytes(claim["tx_hash"]))
                if uid is not None:
                    await _confirm(pool, due["org_id"], request_id, row_id, uid)
                    counts["confirmed"] += 1
                elif claim["stale"]:
                    if await asyncio.to_thread(publisher.pending, bytes(claim["tx_hash"])):
                        # Still known to the node: resending could give two receipts.
                        logger.warning("EAS receipt still pending request_id=%s", request_id)
                        await pool.execute(_DEFER, row_id, SENT_RECHECK)
                        counts["waiting"] += 1
                    else:  # dropped; the resend reuses the nonce, so only one can ever mine
                        raise TimeoutError("attest transaction was not mined in time")
                else:
                    await pool.execute(_DEFER, row_id, SENT_RECHECK)
                    counts["waiting"] += 1
                continue
            if claim["tx_hash"] is not None:  # an earlier attempt may have mined after all
                uid = await asyncio.to_thread(publisher.result, bytes(claim["tx_hash"]))
                if uid is not None:
                    await _confirm(pool, due["org_id"], request_id, row_id, uid)
                    counts["confirmed"] += 1
                    continue
            nonce = claim["nonce"]
            if nonce is not None and await asyncio.to_thread(publisher.nonce_consumed, nonce):
                # The shared receipt key moved past our nonce and our tx (checked above) did not
                # mine with it, so it never can: take a fresh nonce instead of failing forever.
                nonce = None
            receipt = build_receipt(facts)
            if not await asyncio.wait_for(
                finality.is_final(facts["chain_id"], bytes(facts["tx_hash"])), _RPC_TIMEOUT
            ):
                await pool.execute(_DEFER, row_id, NOT_FINAL_RECHECK)
                counts["waiting"] += 1
                continue
            signed = await asyncio.to_thread(publisher.sign, receipt, nonce)
            tx_hash = signed.tx_hash
            # Persist the hash before broadcasting: a crash in between leaves a Sent row whose
            # transaction the node never saw, which the stale path resends safely.
            await pool.execute(_SENT, row_id, tx_hash, SENT_RECHECK, signed.nonce)
            persisted = True
            await asyncio.to_thread(publisher.broadcast, signed.raw_tx)
            counts["sent"] += 1
            try:  # instant on fast chains; otherwise the next sweep confirms the stored hash
                uid = await asyncio.to_thread(publisher.result, tx_hash)
            except Exception:
                uid = None
            if uid is not None:
                await _confirm(pool, due["org_id"], request_id, row_id, uid)
                counts["confirmed"] += 1
        except Exception as error:
            counts["failed"] += 1
            logger.warning(
                "EAS receipt failed request_id=%s error=%s", request_id, type(error).__name__
            )
            # A reverted or lost Sent attempt already counted; a failed send did not.
            sent = claim["status"] == "Sent" or persisted
            await _fail(pool, row_id, error, attempts + (1 if persisted else 0), 0 if sent else 1)
    return counts
