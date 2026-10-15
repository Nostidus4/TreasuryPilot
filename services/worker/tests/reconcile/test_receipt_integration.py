"""EAS payment receipts against PostgreSQL with fake chain clients (REC-005, ADR-018)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from treasurypilot_core.attestations import PaymentReceipt
from treasurypilot_core.eip712 import digest
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.reconcile.build import build_reconciliation
from treasurypilot_worker.reconcile.receipt import (
    ReceiptReverted,
    SignedReceipt,
    backoff,
    publish_receipts,
)

_spec = importlib.util.spec_from_file_location(
    "build_fixtures", Path(__file__).with_name("test_build_integration.py")
)
assert _spec and _spec.loader
_build = importlib.util.module_from_spec(_spec)
sys.modules["build_fixtures"] = _build
_spec.loader.exec_module(_build)
database_url = _build.database_url  # module fixture: migrate, seed, downgrade

_TYPED = {
    "types": {
        "EIP712Domain": [{"name": "name", "type": "string"}],
        "PaymentApproval": [{"name": "amount", "type": "uint256"}],
    },
    "primaryType": "PaymentApproval",
    "domain": {"name": "TreasuryPilot"},
    "message": {"amount": 1000},
}
_UID = bytes.fromhex("ee" * 32)
_SENT_TX = bytes.fromhex("dd" * 32)


class FakeFinality:
    def __init__(self, final: bool = True) -> None:
        self.final = final

    async def is_final(self, chain_id: int, tx_hash: bytes) -> bool:
        return self.final


class FakePublisher:
    """EAS stand-in. ``fail`` raises on broadcast; ``mined`` controls when ``result`` yields a UID;
    ``known`` is whether the node still knows the transaction (mempool)."""

    def __init__(self) -> None:
        self.signed: list[tuple[PaymentReceipt, int | None]] = []
        self.broadcasts = 0
        self.fail: Exception | None = None
        self.crash_before_broadcast = False
        self.mined = True
        self.reverted = False
        self.known = True

    @property
    def sent(self) -> list[PaymentReceipt]:
        return [receipt for receipt, _ in self.signed]

    def sign(self, receipt: PaymentReceipt, nonce: int | None) -> SignedReceipt:
        self.signed.append((receipt, nonce))
        return SignedReceipt(_SENT_TX, b"raw", 7 if nonce is None else nonce)

    def broadcast(self, raw_tx: bytes) -> None:
        if self.crash_before_broadcast:
            raise SystemExit("crash")  # BaseException: skips the sweep's failure handling
        if self.fail is not None:
            raise self.fail
        self.broadcasts += 1

    def pending(self, tx_hash: bytes) -> bool:
        return self.known

    def result(self, tx_hash: bytes) -> bytes | None:
        assert tx_hash == _SENT_TX
        if self.reverted:
            raise ReceiptReverted("reverted")
        return _UID if self.mined and self.broadcasts else None


async def _paid_request(pool: Any) -> Any:
    request = await _build._seed_request(pool, [("PAY", 1000)], "Paid")
    async with pool.acquire() as connection:
        await build_reconciliation(connection, request)
        await connection.execute(  # the covering attestation of the PAY step
            "INSERT INTO attestations (id, plan_id, request_id, plan_hash, step_ids, "
            "policy_version, executor, nonce, valid_until, evidence_digest, typed_data, "
            "signature, policy_signer) SELECT gen_random_uuid(), gen_random_uuid(), "
            "request_id, plan_hash, ARRAY(SELECT step_id FROM operations WHERE "
            "request_id = $1), policy_version, executor, nonce + 1, valid_until, "
            "evidence_digest, typed_data, signature, policy_signer FROM attestations "
            "WHERE request_id = $2",
            request,
            request.bytes * 2,
        )
        async with connection.transaction():
            await connection.execute("SET LOCAL session_replication_role = replica")
            await connection.execute(
                "INSERT INTO approvals (id, request_id, revision, approver_address, "
                "typed_data, signature, expires_at, status) VALUES (gen_random_uuid(), $1, "
                "1, $2, $3::jsonb, $2, now(), 'Valid')",
                request,
                b"\x44" * 20,
                json.dumps(_TYPED),
            )
        await connection.execute(
            "UPDATE payment_requests SET invoice_hash = $2, onchain_request_id = $3 WHERE id = $1",
            request,
            b"\x77" * 32,
            request.bytes * 2,
        )
    return request


async def _row(pool: Any, request: Any) -> Any:
    return await pool.fetchrow(
        "SELECT ca.status, ca.attempts, ca.attestation_uid, ca.tx_hash, ca.last_error, "
        "ca.next_attempt_at > now() AS deferred, q.status AS request_status, r.eas_uid "
        "FROM payment_requests q JOIN reconciliations r ON r.request_id = q.id "
        "LEFT JOIN chain_attestations ca ON ca.request_id = q.id WHERE q.id = $1",
        request,
    )


async def _sweep(pool: Any, finality: FakeFinality, publisher: FakePublisher) -> dict[str, int]:
    return await publish_receipts(pool, finality, publisher, eas_chain_id=11155111)


async def _make_due(pool: Any, request: Any) -> None:
    await pool.execute(
        "UPDATE chain_attestations SET next_attempt_at = now() WHERE request_id = $1", request
    )


def _run(url: str, scenario: Callable[[Any], Awaitable[None]]) -> None:
    async def main() -> None:
        pool = await create_worker_pool(url, min_size=1, max_size=2)
        try:
            await scenario(pool)
        finally:
            await pool.close()

    asyncio.run(main())


def test_finalized_paid_request_is_attested_once_with_only_hashes(database_url: str) -> None:
    async def scenario(pool: Any) -> None:
        request, finality, publisher = await _paid_request(pool), FakeFinality(), FakePublisher()
        await _sweep(pool, finality, publisher)
        row = await _row(pool, request)
        assert (row["status"], row["attempts"], bytes(row["attestation_uid"])) == (
            "Confirmed",
            1,
            _UID,
        )
        assert row["eas_uid"] == "0x" + _UID.hex() and row["request_status"] == "Paid"
        receipt = next(
            r for r in publisher.sent if r.request_id == "0x" + (request.bytes * 2).hex()
        )
        assert receipt.invoice_hash == "0x" + "77" * 32 and receipt.amount == 1000
        assert receipt.payee == "0x" + "0c" * 20  # the PAY step's recipient
        assert receipt.approval_hash == "0x" + digest(_TYPED).hex()
        assert len(receipt.encode()) == 8 * 32  # eight static words: hashes, address, amount
        audit = await pool.fetchval(
            "SELECT count(*) FROM audit_log WHERE action = 'reconciliation.receipt_published' "
            "AND entity_id = $1",
            str(request),
        )
        assert audit == 1
        sent_before = len(publisher.sent)
        await _sweep(pool, finality, publisher)  # a Confirmed receipt is never re-sent
        assert len(publisher.sent) == sent_before

    _run(database_url, scenario)


def test_receipt_waits_for_the_pay_block_to_finalize(database_url: str) -> None:
    async def scenario(pool: Any) -> None:
        request = await _paid_request(pool)
        finality, publisher = FakeFinality(final=False), FakePublisher()
        await _sweep(pool, finality, publisher)
        row = await _row(pool, request)
        assert row["status"] == "Queued" and row["attempts"] == 0 and row["deferred"]
        assert not any(r.request_id == "0x" + (request.bytes * 2).hex() for r in publisher.sent)
        finality.final = True
        await _make_due(pool, request)
        await _sweep(pool, finality, publisher)
        assert (await _row(pool, request))["status"] == "Confirmed"

    _run(database_url, scenario)


def test_eas_failure_leaves_payment_paid_and_is_retried_with_backoff(database_url: str) -> None:
    async def scenario(pool: Any) -> None:
        request, finality, publisher = await _paid_request(pool), FakeFinality(), FakePublisher()
        publisher.fail = ConnectionError("https://user:secret@rpc.example/key")
        await _sweep(pool, finality, publisher)
        row = await _row(pool, request)
        assert (row["status"], row["attempts"], row["request_status"]) == ("Failed", 1, "Paid")
        assert row["deferred"] and row["last_error"] == "ConnectionError"  # no URL or secret
        assert row["eas_uid"] is None
        await _sweep(pool, finality, publisher)  # still backing off: nothing is attempted
        assert (await _row(pool, request))["attempts"] == 1
        publisher.fail = None
        await _make_due(pool, request)
        await _sweep(pool, finality, publisher)
        row = await _row(pool, request)
        assert (row["status"], row["attempts"], row["request_status"]) == ("Confirmed", 2, "Paid")

    _run(database_url, scenario)


def test_a_broadcast_is_confirmed_later_without_a_second_send(database_url: str) -> None:
    async def scenario(pool: Any) -> None:
        request, finality, publisher = await _paid_request(pool), FakeFinality(), FakePublisher()
        publisher.mined = False
        await _sweep(pool, finality, publisher)
        row = await _row(pool, request)
        assert (row["status"], bytes(row["tx_hash"])) == ("Sent", _SENT_TX)
        sent = len(publisher.sent)
        publisher.mined = True
        await _make_due(pool, request)
        await _sweep(pool, finality, publisher)
        row = await _row(pool, request)
        assert row["status"] == "Confirmed" and len(publisher.sent) == sent

    _run(database_url, scenario)


def test_a_reverted_attest_is_failed_and_resent(database_url: str) -> None:
    async def scenario(pool: Any) -> None:
        request, finality, publisher = await _paid_request(pool), FakeFinality(), FakePublisher()
        publisher.mined = False
        await _sweep(pool, finality, publisher)
        publisher.reverted = True
        await _make_due(pool, request)
        await _sweep(pool, finality, publisher)
        row = await _row(pool, request)
        assert (row["status"], row["attempts"], row["request_status"]) == ("Failed", 1, "Paid")
        publisher.reverted, publisher.mined = False, True
        await _make_due(pool, request)
        await _sweep(pool, finality, publisher)
        assert (await _row(pool, request))["status"] == "Confirmed"

    _run(database_url, scenario)


def test_crash_after_persist_before_broadcast_broadcasts_exactly_once(database_url: str) -> None:
    async def scenario(pool: Any) -> None:
        request, finality, publisher = await _paid_request(pool), FakeFinality(), FakePublisher()
        publisher.crash_before_broadcast = True
        with pytest.raises(SystemExit):
            await _sweep(pool, finality, publisher)
        row = await _row(pool, request)
        assert (row["status"], bytes(row["tx_hash"])) == ("Sent", _SENT_TX)
        assert publisher.broadcasts == 0
        publisher.crash_before_broadcast, publisher.known = False, False  # node never saw it
        await pool.execute(  # lease expired and the Sent row went stale
            "UPDATE chain_attestations SET next_attempt_at = now(), "
            "updated_at = now() - interval '1 hour' WHERE request_id = $1",
            request,
        )
        await _sweep(pool, finality, publisher)  # dropped: Failed, backoff
        assert (await _row(pool, request))["status"] == "Failed"
        await _make_due(pool, request)
        await _sweep(pool, finality, publisher)
        assert (await _row(pool, request))["status"] == "Confirmed"
        assert publisher.broadcasts == 1  # exactly one broadcast in total
        assert [nonce for _, nonce in publisher.signed if nonce is not None] == [7]  # same nonce

    _run(database_url, scenario)


def test_a_stale_but_still_pending_transaction_is_deferred_not_resent(database_url: str) -> None:
    async def scenario(pool: Any) -> None:
        request, finality, publisher = await _paid_request(pool), FakeFinality(), FakePublisher()
        publisher.mined = False
        await _sweep(pool, finality, publisher)
        assert publisher.broadcasts == 1
        await pool.execute(
            "UPDATE chain_attestations SET next_attempt_at = now(), "
            "updated_at = now() - interval '1 hour' WHERE request_id = $1",
            request,
        )
        await _sweep(pool, finality, publisher)  # node still knows the tx
        row = await _row(pool, request)
        assert row["status"] == "Sent" and row["deferred"]
        assert publisher.broadcasts == 1 and len(publisher.signed) == 1

    _run(database_url, scenario)


def test_unpaid_requests_get_no_receipt(database_url: str) -> None:
    async def scenario(pool: Any) -> None:
        request = await _build._seed_request(pool, [("REFILL", 700)], "Paying")
        await _sweep(pool, FakeFinality(), FakePublisher())
        count = await pool.fetchval(
            "SELECT count(*) FROM chain_attestations WHERE request_id = $1", request
        )
        assert count == 0

    _run(database_url, scenario)


def test_backoff_doubles_up_to_an_hour() -> None:
    assert [backoff(n).total_seconds() for n in (0, 1, 2, 3)] == [30, 60, 120, 240]
    assert backoff(50).total_seconds() == 3600
