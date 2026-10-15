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


@pytest.mark.parametrize("kind", ["PAY"])
def test_sequencer_creates_the_reconciliation_with_the_paid_transition(
    database_url: str, kind: str
) -> None:
    async def scenario() -> tuple[str, int]:
        pool = await create_worker_pool(database_url, min_size=1, max_size=2)
        try:
            request = await _seed_request(pool, [("REFILL", 7), (kind, 6)], "Paying")
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
            result = await _seq.sequence_plan(
                pool, _seq.FakeSigner(), run, _seq.FakeGate(), _seq._Passed()
            )
            lines = await _lines(pool, request)
            return result.status, len(lines)
        finally:
            await pool.close()

    assert asyncio.run(scenario()) == ("Completed", 4)
