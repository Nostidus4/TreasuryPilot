"""Reconciliation records against PostgreSQL (REC-002)."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.reconcile.build import build_reconciliation

_spec = importlib.util.spec_from_file_location(
    "sequencer_fixtures",
    Path(__file__).parents[1] / "executor" / "test_sequencer_integration.py",
)
assert _spec and _spec.loader
_seq = importlib.util.module_from_spec(_spec)
sys.modules["sequencer_fixtures"] = _seq
_spec.loader.exec_module(_seq)
database_url = _seq.database_url  # module fixture: migrate, seed, downgrade

_ASSET = uuid.UUID(_seq._ASSET)
_ETH_FEE = 21_000 * 10**9


async def _seed_request(pool: Any, ops: list[tuple[str, int]], status: str) -> uuid.UUID:
    """Requests with Confirmed operations of the given (kind, amount); each costs _ETH_FEE."""

    request, attestation = uuid.uuid4(), uuid.uuid4()
    await pool.execute(
        "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id, "
        "invoice_no, issue_date, due_at, amount, asset_id, status, fingerprint) VALUES "
        "($1, $2, $3, $4, $5, $6, $7, '2026-10-01', '2026-10-31', 1000, $8, $9, $10)",
        request,
        uuid.UUID(_seq._ORG),
        _seq._TREASURY,
        _seq.CHAIN_ID,
        uuid.UUID(_seq._VENDOR),
        uuid.UUID(_seq._PAYEE),
        "REC-" + request.hex,
        _ASSET,
        status,
        request.bytes * 2,
    )
    await pool.execute(
        "INSERT INTO attestations (id, plan_id, request_id, plan_hash, step_ids, policy_version, "
        "executor, nonce, valid_until, evidence_digest, typed_data, signature, policy_signer) "
        "VALUES ($1, $2, $3, $4, $5, $4, '0x', $6, now(), $4, '{}', $4, '0x')",
        attestation,
        uuid.uuid4(),
        request.bytes * 2,
        attestation.bytes * 2,
        [],
        attestation.int,
    )
    for seq, (kind, amount) in enumerate(ops):
        step_id, step_row, op, tx = (uuid.uuid4() for _ in range(4))
        await pool.execute(
            "INSERT INTO plan_steps (id, attestation_id, plan_id, seq, step_id, action, "
            "request_id, treasury_address, chain_id, from_address, to_address, asset_address, "
            "amount) VALUES ($1, $2, $3, $4, $5, 1, $6, $7, $8, $9, $10, $11, $12)",
            step_row,
            attestation,
            uuid.uuid4(),
            seq,
            step_id.bytes * 2,
            request.bytes * 2,
            b"\x0a" * 20,
            _seq.CHAIN_ID,
            b"\x0b" * 20,
            b"\x0c" * 20,
            b"\x0d" * 20,
            amount,
        )
        await pool.execute(
            "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, kind, "
            "payload, idempotency_key, status) VALUES ($1, $2, $3, $4, $5, $6::operation_kind, "
            "'{}', $7, 'Confirmed')",
            op,
            _seq._TREASURY,
            step_row,
            request,
            step_id.bytes * 2,
            kind,
            "rec:" + op.hex,
        )
        await pool.execute(
            "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, from_address, "
            "status, block_number, fee_wei, confirmed_at) VALUES ($1, $2, $3, $4, $5, $6, "
            "'Confirmed', 100, $7, '2026-10-02 23:59:00+00')",
            tx,
            op,
            _seq.CHAIN_ID,
            tx.bytes * 2,
            seq,
            b"\xee" * 20,
            _ETH_FEE,
        )
        await pool.execute(
            "INSERT INTO gas_ledger (id, treasury_id, transaction_id, payer, payer_address, "
            "fee_wei, reverted, day) VALUES (gen_random_uuid(), $1, $2, 'EXECUTOR', $3, $4, "
            "false, '2026-10-02')",
            _seq._TREASURY,
            tx,
            b"\xee" * 20,
            _ETH_FEE,
        )
    return request


async def _lines(pool: Any, request: uuid.UUID) -> list[tuple[str, int, bool]]:
    rows = await pool.fetch(
        "SELECT l.classification, l.amount, l.asset_address IS NULL AS native FROM "
        "reconciliation_lines l JOIN reconciliations r ON r.id = l.reconciliation_id "
        "WHERE r.request_id = $1 ORDER BY l.classification, l.amount",
        request,
    )
    return [(r["classification"], int(r["amount"]), r["native"]) for r in rows]


async def _build(url: str, ops: list[tuple[str, int]], status: str) -> Any:
    pool = await create_worker_pool(url, min_size=1, max_size=1)
    try:
        request = await _seed_request(pool, ops, status)
        async with pool.acquire() as connection:
            first = await build_reconciliation(connection, request)
            again = await build_reconciliation(connection, request)  # idempotent
        assert first == again
        return first, await _lines(pool, request)
    finally:
        await pool.close()


def test_refill_and_pay_have_two_classified_lines_and_two_fees(database_url: str) -> None:
    rid, lines = asyncio.run(_build(database_url, [("REFILL", 700), ("PAY", 600)], "Paid"))
    assert rid is not None
    assert lines == [
        ("EXTERNAL_EXPENSE", 600, False),
        ("FEE", _ETH_FEE, True),
        ("FEE", _ETH_FEE, True),
        ("INTERNAL_TRANSFER", 700, False),
    ]


def test_swap_and_lending_steps_are_classified(database_url: str) -> None:
    _, lines = asyncio.run(
        _build(
            database_url,
            [("SUPPLY", 1), ("WITHDRAW", 2), ("SWAP", 3), ("REFILL", 4), ("PAY", 5)],
            "Paid",
        )
    )
    assert [(c, a) for c, a, _ in lines if c != "FEE"] == [
        ("CONVERSION", 3),
        ("EXTERNAL_EXPENSE", 5),
        ("INTERNAL_TRANSFER", 4),
        ("LENDING_TRANSFER", 1),
        ("LENDING_TRANSFER", 2),
    ]
    assert sum(c == "FEE" for c, _, _ in lines) == 5


def test_refill_without_a_paid_request_has_no_reconciliation_or_expense(
    database_url: str,
) -> None:
    rid, lines = asyncio.run(_build(database_url, [("REFILL", 700)], "Paying"))
    assert rid is None and lines == []


async def _sequence(database_url: str, ops: list[tuple[str, int]]) -> tuple[str | None, int, str]:
    """Run the sequencer over Confirmed-seeded ops; (result status or None if it raised, lines, request status)."""

    pool = await create_worker_pool(database_url, min_size=1, max_size=2)
    try:
        request = await _seed_request(pool, ops, "Paying")
        steps = await pool.fetch(
            "SELECT step_id, kind::text AS kind, plan_step_id FROM operations "
            "WHERE request_id = $1 ORDER BY created_at, id",
            request,
        )
        run = _seq.PlanRun(
            uuid.uuid4(),
            request,
            tuple(
                _seq.StepExecution(
                    treasury_id=_seq._TREASURY,
                    request_id=request,
                    plan_step_id=s["plan_step_id"],
                    step_id=s["step_id"],
                    kind=s["kind"],
                    chain_id=_seq.CHAIN_ID,
                    sign_request={},
                )
                for s in steps
            ),
            _seq.datetime.now(_seq.UTC) + _seq.timedelta(minutes=5),
        )
        try:
            result = (
                await _seq.sequence_plan(
                    pool, _seq.FakeSigner(), run, _seq.FakeGate(), _seq._Passed()
                )
            ).status
        except RuntimeError:
            result = None
        lines = await _lines(pool, request)
        status = await pool.fetchval("SELECT status FROM payment_requests WHERE id=$1", request)
        return result, len(lines), status
    finally:
        await pool.close()


def test_sequencer_creates_the_reconciliation_with_the_paid_transition(
    database_url: str,
) -> None:
    ops = [("REFILL", 7), ("PAY", 6)]
    assert asyncio.run(_sequence(database_url, ops)) == ("Completed", 4, "Paid")


def test_builder_failure_rolls_back_the_paid_transition(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_: Any) -> None:
        raise RuntimeError("build failed")

    monkeypatch.setattr("treasurypilot_worker.executor.sequencer.build_reconciliation", boom)
    ops = [("REFILL", 7), ("PAY", 6)]
    assert asyncio.run(_sequence(database_url, ops)) == (None, 0, "Paying")


async def _reverted_then_confirmed(
    url: str, *, replacement_status: str, with_ledger: bool
) -> list[tuple[str, int, bool]]:
    """A PAY op whose first tx Reverted and whose replacement has `replacement_status`."""

    pool = await create_worker_pool(url, min_size=1, max_size=1)
    try:
        request = await _seed_request(pool, [("PAY", 600)], "Paid")
        op = await pool.fetchval("SELECT id FROM operations WHERE request_id = $1", request)
        first = await pool.fetchrow("SELECT * FROM transactions WHERE operation_id = $1", op)
        await pool.execute("UPDATE transactions SET status = 'Reverted' WHERE id = $1", first["id"])
        await pool.execute(
            "UPDATE gas_ledger SET reverted = true WHERE transaction_id = $1", first["id"]
        )
        second = uuid.uuid4()
        await pool.execute(
            "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, from_address, "
            "status, block_number, fee_wei, confirmed_at) VALUES ($1, $2, $3, $4, 9, $5, $6, 101, "
            "$7, '2026-10-03 01:00:00+00')",
            second,
            op,
            _seq.CHAIN_ID,
            second.bytes * 2,
            b"\xee" * 20,
            replacement_status,
            _ETH_FEE,
        )
        if with_ledger:
            await pool.execute(
                "INSERT INTO gas_ledger (id, treasury_id, transaction_id, payer, payer_address, "
                "fee_wei, reverted, day) VALUES (gen_random_uuid(), $1, $2, 'EXECUTOR', $3, $4, "
                "false, '2026-10-03')",
                _seq._TREASURY,
                second,
                b"\xee" * 20,
                _ETH_FEE,
            )
        async with pool.acquire() as connection:
            await build_reconciliation(connection, request)
        return await _lines(pool, request)
    finally:
        await pool.close()


def test_reverted_attempt_pays_a_fee_but_only_the_confirmed_one_is_an_expense(
    database_url: str,
) -> None:
    lines = asyncio.run(
        _reverted_then_confirmed(database_url, replacement_status="Confirmed", with_ledger=True)
    )
    assert lines == [
        ("EXTERNAL_EXPENSE", 600, False),
        ("FEE", _ETH_FEE, True),
        ("FEE", _ETH_FEE, True),
    ]


def test_dropped_tx_or_missing_gas_ledger_row_gives_no_fee_line(database_url: str) -> None:
    dropped = asyncio.run(
        _reverted_then_confirmed(database_url, replacement_status="Dropped", with_ledger=False)
    )
    # The Reverted first attempt keeps its FEE; the Dropped one has no gas_ledger row.
    assert [c for c, _, _ in dropped].count("FEE") == 1
    missing = asyncio.run(
        _reverted_then_confirmed(database_url, replacement_status="Confirmed", with_ledger=False)
    )
    assert [c for c, _, _ in missing].count("FEE") == 1


async def _auto_match(
    url: str, *, auto_match: bool, finalized: int = 100, verified: bool = True, doc: bytes = b""
) -> tuple[str, str | None]:
    """Build a one-PAY reconciliation with full evidence, run the sweep; (status, matched_by)."""

    from treasurypilot_worker.reconcile.auto_match import auto_match_reconciliations

    pool = await create_worker_pool(url, min_size=1, max_size=2)
    try:
        request = await _seed_request(pool, [("PAY", 1000)], "Paid")
        async with pool.acquire() as connection:
            await build_reconciliation(connection, request)
            await connection.execute(
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
                    '{"message": {"invoiceHash": "0x' + ("77" * 32) + '"}}',
                )
            if verified:
                await connection.execute(
                    "INSERT INTO verifications (id, operation_id, block_number, expected, "
                    "observed, diffs, result) SELECT gen_random_uuid(), id, 100, '{}', '{}', "
                    "'{}', 'PASSED' FROM operations WHERE request_id = $1",
                    request,
                )
            if doc:
                await connection.execute(
                    "INSERT INTO documents (id, request_id, storage_key, sha256, mime, size) "
                    "VALUES (gen_random_uuid(), $1, $2, $3, 'application/pdf', 1)",
                    request,
                    "k" + request.hex,
                    doc,
                )
            await connection.execute(
                "UPDATE organizations SET auto_match = $1 WHERE id = $2",
                auto_match,
                uuid.UUID(_seq._ORG),
            )

        async def head(_: int) -> int:
            return finalized

        await auto_match_reconciliations(pool, head)
        row = await pool.fetchrow(
            "SELECT status, matched_by FROM reconciliations WHERE request_id = $1", request
        )
        return row["status"], row["matched_by"]
    finally:
        await pool.close()


def test_auto_match_is_off_by_default_and_needs_the_org_setting(database_url: str) -> None:
    assert asyncio.run(_auto_match(database_url, auto_match=False)) == ("Pending", None)
    assert asyncio.run(_auto_match(database_url, auto_match=True)) == ("Matched", "AUTO")


def test_auto_match_waits_for_finality_and_every_check(database_url: str) -> None:
    assert asyncio.run(_auto_match(database_url, auto_match=True, finalized=99))[0] == "Pending"
    assert asyncio.run(_auto_match(database_url, auto_match=True, verified=False))[0] == "Pending"
    # The invoice document must hash to the approval's invoiceHash.
    assert asyncio.run(_auto_match(database_url, auto_match=True, doc=b"\x01" * 32))[0] == "Pending"
    assert asyncio.run(_auto_match(database_url, auto_match=True, doc=b"\x77" * 32))[0] == "Matched"
