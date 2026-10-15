from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import jsonschema
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from treasurypilot_api.audit.evidence import EvidenceBundleInvalid, EvidenceNotFound
from treasurypilot_api.audit.evidence_repository import (
    ReceiptResult,
    SqlAlchemyEvidenceRepository,
)

pytestmark = pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

API_ROOT = Path(__file__).parents[1]
CHAIN_ID = 11155111
SCHEMA_PATH = API_ROOT / "src/treasurypilot_api/audit/evidence-bundle.v1.schema.json"


class _FixtureReceiptVerifier:
    """Test-only stand-in at the RPC boundary for hashes inserted by this test."""

    async def verify(
        self,
        *,
        tx_hash: str,
        chain_id: int,
        rpc_urls: Sequence[str],
        expected_block_number: int | None,
        expected_block_hash: str | None,
    ) -> ReceiptResult:
        assert rpc_urls == ["https://rpc.test.invalid"]
        return ReceiptResult(
            resolved=True,
            chain_id=chain_id,
            transaction_hash=tx_hash,
            block_number=expected_block_number,
            block_hash=expected_block_hash,
            status="0x1",
        )


class _UnresolvedReceiptVerifier:
    async def verify(self, **_kwargs: object) -> ReceiptResult:
        return ReceiptResult(resolved=False)


async def _seed_and_export(database_url: str) -> dict[str, object]:
    engine = create_async_engine(database_url)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        organization_id, user_id = uuid.uuid4(), uuid.uuid4()
        treasury_id, asset_id = uuid.uuid4(), uuid.uuid4()
        vendor_id, payee_id = uuid.uuid4(), uuid.uuid4()
        paid_request_id, blocked_request_id = uuid.uuid4(), uuid.uuid4()
        operation_id, plan_id = uuid.uuid4(), uuid.uuid4()
        blocked_plan_id, attestation_id = uuid.uuid4(), uuid.uuid4()
        multi_request_id = uuid.uuid4()
        plan_step_id, reconciliation_id = uuid.uuid4(), uuid.uuid4()
        now = datetime.now(UTC)
        issue_date = date.today()
        tx_hash = bytes.fromhex("a1" * 32)  # Test database fixture only; never production evidence.
        block_hash = bytes.fromhex("b2" * 32)
        onchain_request_id = bytes.fromhex("c3" * 32)
        plan_hash = bytes.fromhex("d4" * 32)
        step_id = bytes.fromhex("e5" * 32)
        typed_data = {
            "domain": {"name": "TreasuryPilot Policy"},
            "message": {
                "requestId": "0x" + onchain_request_id.hex(),
                "planHash": "0x" + plan_hash.hex(),
                "stepIds": ["0x" + step_id.hex()],
            },
        }

        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO users (id, email) VALUES (:id, :email)"),
                {"id": user_id, "email": f"evidence-{uuid.uuid4()}@example.test"},
            )
            await connection.execute(
                text("INSERT INTO organizations (id, name) VALUES (:id, 'Evidence test')"),
                {"id": organization_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO chains (chain_id, name, is_testnet, confirmations, "
                    "explorer_url, rpc_urls) VALUES (:chain, 'Sepolia', true, 3, "
                    "'https://explorer.test', '[\"https://rpc.test.invalid\"]'::jsonb)"
                ),
                {"chain": CHAIN_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label, "
                    "is_test) VALUES (:id, :chain, decode(repeat('11', 20), 'hex'), 'USDC', 6, "
                    "'test issuer', true)"
                ),
                {"id": asset_id, "chain": CHAIN_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id) "
                    "VALUES (:id, :org, :chain, :asset)"
                ),
                {
                    "id": treasury_id,
                    "org": organization_id,
                    "chain": CHAIN_ID,
                    "asset": asset_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO vendors (id, org_id, name, normalized_ref) "
                    "VALUES (:id, :org, 'Example vendor', 'example-vendor')"
                ),
                {"id": vendor_id, "org": organization_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, "
                    "status, oob_verified_by, oob_verified_at, oob_method, oob_note, active_from) "
                    "VALUES (:id, :treasury, :org, :vendor, 'Primary', decode(repeat('22', 20), 'hex'), "
                    "'Active', :user_id, :at, 'PHONE', 'test verification', :at)"
                ),
                {
                    "id": payee_id,
                    "treasury": treasury_id,
                    "org": organization_id,
                    "vendor": vendor_id,
                    "user_id": user_id,
                    "at": now,
                },
            )
            for request_id, invoice_no, status, onchain_id in (
                (paid_request_id, "INV-PAID", "Paid", onchain_request_id),
                (blocked_request_id, "INV-BLOCKED", "NeedsReview", None),
                (multi_request_id, "INV-MULTI", "NeedsReview", None),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, "
                        "vendor_id, payee_id, asset_id, invoice_no, issue_date, due_at, amount, "
                        "status, fingerprint, invoice_hash, onchain_request_id) VALUES "
                        "(:id, :org, :treasury, :chain, :vendor, :payee, :asset, :invoice, "
                        ":issue_date, :due_at, 250000, :status, :fingerprint, :invoice_hash, :onchain_id)"
                    ),
                    {
                        "id": request_id,
                        "org": organization_id,
                        "treasury": treasury_id,
                        "chain": CHAIN_ID,
                        "vendor": vendor_id,
                        "payee": payee_id,
                        "asset": asset_id,
                        "invoice": invoice_no,
                        "issue_date": issue_date,
                        "due_at": issue_date + timedelta(days=10),
                        "status": status,
                        "fingerprint": hashlib.sha256(invoice_no.encode()).digest(),
                        "invoice_hash": hashlib.sha256((invoice_no + "-hash").encode()).digest(),
                        "onchain_id": onchain_id,
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO request_revisions (id, request_id, revision, snapshot) "
                        "VALUES (:revision_id, :request_id, 1, '{}'::jsonb)"
                    ),
                    {"revision_id": uuid.uuid4(), "request_id": request_id},
                )

            await connection.execute(
                text(
                    "INSERT INTO approvals (id, request_id, revision, approver_address, "
                    "typed_data, signature, expires_at, status) VALUES (:id, :request_id, 1, "
                    "decode(repeat('33', 20), 'hex'), '{\"message\": {\"amount\": \"250000\"}}'::jsonb, "
                    "decode('deadbeef', 'hex'), :expiry, 'Valid')"
                ),
                {
                    "id": uuid.uuid4(),
                    "request_id": paid_request_id,
                    "expiry": now + timedelta(days=1),
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO flags (id, request_id, revision, code, severity, evidence, source) "
                    "VALUES (:id, :request_id, 1, 'POLICY_BLOCK', 'HIGH', "
                    "'{\"privateEmail\": \"private@example.test\"}'::jsonb, 'DETERMINISTIC')"
                ),
                {"id": uuid.uuid4(), "request_id": blocked_request_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, "
                    "kind, payload, idempotency_key, status, attempts) VALUES (:id, :treasury, "
                    ":plan_step, :request_id, :step_id, 'PAY', '{}'::jsonb, :key, 'Confirmed', 1)"
                ),
                {
                    "id": operation_id,
                    "treasury": treasury_id,
                    "plan_step": plan_step_id,
                    "request_id": paid_request_id,
                    "step_id": step_id,
                    "key": f"test-{uuid.uuid4()}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, "
                    "from_address, status, block_number, block_hash, confirmations, fee_wei, "
                    "submitted_at, last_seen_pending_at, confirmed_at, crosscheck) VALUES "
                    "(:id, :operation, :chain, :tx_hash, 1, decode(repeat('44', 20), 'hex'), "
                    "'Confirmed', 123, :block_hash, 8, 19, :at, :at, :at, 'Match')"
                ),
                {
                    "id": uuid.uuid4(),
                    "operation": operation_id,
                    "chain": CHAIN_ID,
                    "tx_hash": tx_hash,
                    "block_hash": block_hash,
                    "at": now,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO attestations (id, plan_id, request_id, plan_hash, step_ids, "
                    "policy_version, executor, nonce, valid_until, evidence_digest, typed_data, "
                    "signature, policy_signer) VALUES (:id, :plan_id, :request_id, :plan_hash, "
                    ":step_ids, :policy_version, :executor, 1, :valid_until, :evidence_digest, "
                    "CAST(:typed_data AS jsonb), decode('cafe', 'hex'), :signer)"
                ),
                {
                    "id": attestation_id,
                    "plan_id": plan_id,
                    "request_id": onchain_request_id,
                    "plan_hash": plan_hash,
                    "step_ids": [step_id],
                    "policy_version": bytes.fromhex("01" * 32),
                    "executor": "0x" + "44" * 20,
                    "valid_until": now + timedelta(minutes=10),
                    "evidence_digest": bytes.fromhex("02" * 32),
                    "typed_data": json.dumps(typed_data),
                    "signer": "0x" + "55" * 20,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO validations (id, plan_id, stage, decision, reason_codes, "
                    "warnings, checks, policy_version, snapshot_block) VALUES (:id, :plan_id, "
                    "'PLAN', 'ALLOW', ARRAY[]::text[], ARRAY[]::text[], "
                    '\'[ {"name": "within_limit", "passed": true} ]\'::jsonb, :version, 123)'
                ),
                {
                    "id": uuid.uuid4(),
                    "plan_id": plan_id,
                    "version": bytes.fromhex("01" * 32),
                },
            )
            multi_plan_ids = [uuid.uuid4() for _ in range(3)]
            for pid, req, source, plan_status, att, age in (
                (plan_id, paid_request_id, "DETERMINISTIC", "Completed", attestation_id, 0),
                # A later empty Draft must not hide the attested plan.
                (uuid.uuid4(), paid_request_id, None, "Draft", None, 5),
                (blocked_plan_id, blocked_request_id, None, "Blocked", None, 0),
                # Expired -> Superseded (decided, has validations) -> empty Draft: only one
                # plan per request may be open, so the decided one is Superseded.
                (multi_plan_ids[0], multi_request_id, None, "Expired", None, 0),
                (multi_plan_ids[1], multi_request_id, None, "Superseded", None, 1),
                (multi_plan_ids[2], multi_request_id, None, "Draft", None, 2),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO plans (id, org_id, treasury_id, request_id, planner_source, "
                        "plan_hash, status, attestation_id, created_at) VALUES (:id, :org, "
                        ":treasury, :req, :source, :hash, :status, :att, :created)"
                    ),
                    {
                        "id": pid,
                        "org": organization_id,
                        "treasury": treasury_id,
                        "req": req,
                        "source": source,
                        "hash": plan_hash if att else None,
                        "status": plan_status,
                        "att": att,
                        "created": now + timedelta(hours=age),
                    },
                )
            await connection.execute(
                text(
                    "INSERT INTO validations (id, plan_id, stage, decision, reason_codes, "
                    "warnings, checks, policy_version, snapshot_block) VALUES (:id, :plan_id, "
                    "'PLAN', 'BLOCK', ARRAY['POLICY_BLOCK']::text[], ARRAY[]::text[], "
                    '\'[ {"name": "vendor_allowed", "passed": false} ]\'::jsonb, :version, 122)'
                ),
                {
                    "id": uuid.uuid4(),
                    "plan_id": blocked_plan_id,
                    "version": bytes.fromhex("01" * 32),
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO validations (id, plan_id, stage, decision, reason_codes, "
                    "warnings, checks, policy_version, snapshot_block) VALUES (:id, :plan_id, "
                    "'PLAN', 'BLOCK', ARRAY['POLICY_BLOCK']::text[], ARRAY[]::text[], "
                    "'[]'::jsonb, :version, 122)"
                ),
                {
                    "id": uuid.uuid4(),
                    "plan_id": multi_plan_ids[1],
                    "version": bytes.fromhex("01" * 32),
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO plan_steps (id, attestation_id, plan_id, seq, step_id, action, "
                    "request_id, treasury_address, chain_id, from_address, to_address, "
                    "asset_address, amount) VALUES (:id, :att, :plan, 0, :step_id, 1, :req, "
                    "decode(repeat('66', 20), 'hex'), :chain, decode(repeat('66', 20), 'hex'), "
                    "decode(repeat('22', 20), 'hex'), decode(repeat('11', 20), 'hex'), 250000)"
                ),
                {
                    "id": plan_step_id,
                    "att": attestation_id,
                    "plan": plan_id,
                    "step_id": step_id,
                    "req": onchain_request_id,
                    "chain": CHAIN_ID,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO verifications (id, operation_id, block_number, expected, "
                    "observed, diffs, result) VALUES (:id, :op, 123, '{}'::jsonb, '{}'::jsonb, "
                    "'[]'::jsonb, 'PASSED')"
                ),
                {"id": uuid.uuid4(), "op": operation_id},
            )
            # A later UNKNOWN must not displace the definitive PASSED verdict.
            await connection.execute(
                text(
                    "INSERT INTO verifications (id, operation_id, block_number, expected, "
                    "observed, diffs, result, at) VALUES (:id, :op, 124, '{}'::jsonb, "
                    "'{}'::jsonb, '[]'::jsonb, 'UNKNOWN', :at)"
                ),
                {"id": uuid.uuid4(), "op": operation_id, "at": now + timedelta(hours=1)},
            )
            await connection.execute(
                text(
                    "INSERT INTO reconciliations (id, org_id, treasury_id, request_id, status) "
                    "VALUES (:id, :org, :treasury, :req, 'Matched')"
                ),
                {
                    "id": reconciliation_id,
                    "org": organization_id,
                    "treasury": treasury_id,
                    "req": paid_request_id,
                },
            )
            for classification, to_address, asset, amount in (
                (
                    "EXTERNAL_EXPENSE",
                    "decode(repeat('22', 20), 'hex')",
                    "decode(repeat('11', 20), 'hex')",
                    250000,
                ),
                ("FEE", "NULL", "NULL", 10),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO reconciliation_lines (id, reconciliation_id, classification, "
                        "operation_id, transaction_id, tx_hash, from_address, to_address, "
                        f"asset_address, amount, block_number) SELECT :id, :rec, :class, "
                        f"operation_id, id, tx_hash, from_address, {to_address}, {asset}, "
                        f":amount, block_number FROM transactions"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "rec": reconciliation_id,
                        "class": classification,
                        "amount": amount,
                    },
                )
            await connection.execute(
                text(
                    "UPDATE reconciliations SET eas_uid = '0x' || repeat('ab', 32) WHERE id = :id"
                ),
                {"id": reconciliation_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO chain_attestations (id, request_id, chain_id, schema_uid, "
                    "attestation_uid, status) VALUES (:id, :req, 11155111, "
                    "decode(repeat('51', 32), 'hex'), decode(repeat('ab', 32), 'hex'), "
                    "'Confirmed')"
                ),
                {"id": uuid.uuid4(), "req": paid_request_id},
            )
            # Zero-line reconciliation whose free-text note carries PII.
            await connection.execute(
                text(
                    "INSERT INTO reconciliations (id, org_id, treasury_id, request_id, status, "
                    "note) VALUES (:id, :org, :treasury, :req, 'Pending', "
                    "'call note-private@example.test')"
                ),
                {
                    "id": uuid.uuid4(),
                    "org": organization_id,
                    "treasury": treasury_id,
                    "req": multi_request_id,
                },
            )

        repository = SqlAlchemyEvidenceRepository(
            sessions, receipt_verifier=_FixtureReceiptVerifier(), app_version="integration-test"
        )
        paid = await repository.export_request(
            organization_id=organization_id, request_id=paid_request_id
        )
        blocked = await repository.export_request(
            organization_id=organization_id, request_id=blocked_request_id
        )
        assert (
            paid.transactions is not None and paid.transactions[0].tx_hash == "0x" + tx_hash.hex()
        )
        assert paid.validations[0].decision == "ALLOW"
        assert paid.approval is not None
        assert paid.attestation is not None
        assert paid.approval.signature_hash == hashlib.sha256(bytes.fromhex("deadbeef")).hexdigest()
        assert paid.attestation.signature_hash == hashlib.sha256(bytes.fromhex("cafe")).hexdigest()
        assert "TESTNET" in paid.fixture_labels
        assert "TEST_ASSET" in paid.fixture_labels
        assert paid.plan is not None
        assert paid.plan.planner_source == "DETERMINISTIC"
        assert [step.seq for step in paid.plan.steps] == [0]
        assert paid.reconciliation is not None
        assert paid.reconciliation.status == "Matched"
        assert [line.classification for line in paid.reconciliation.lines] == [
            "EXTERNAL_EXPENSE",
            "FEE",
        ]
        assert paid.plan.status == "Completed" and paid.plan.plan_id == plan_id
        assert paid.eas_uid == "0x" + "ab" * 32
        assert paid.eas_url == "https://sepolia.easscan.org/attestation/view/0x" + "ab" * 32
        assert paid.verifications[0].details["independentVerifier"] == "PASSED"
        again = await repository.export_request(
            organization_id=organization_id, request_id=paid_request_id
        )
        # generated_at is part of the seal, so compare the content that must be stable.
        assert again.reconciliation == paid.reconciliation
        multi = await repository.export_request(
            organization_id=organization_id, request_id=multi_request_id
        )
        assert multi.plan is not None and multi.plan.status == "Superseded"
        assert multi.plan.plan_id == multi_plan_ids[1]
        assert multi.reconciliation is not None and multi.reconciliation.lines == []
        assert "note-private@example.test" not in json.dumps(
            multi.model_dump(mode="json", by_alias=True)
        )
        assert blocked.transactions is None
        assert blocked.plan is not None and blocked.plan.steps == []
        assert [v.decision for v in blocked.validations] == ["BLOCK"]
        assert blocked.validations[0].checks == [{"name": "vendor_allowed", "passed": False}]
        assert blocked.coverage["validations"] == "linked_by_plans_request_id_and_attested_plan_id"
        # Acceptance: every tx hash in the bundle (and in reconciliation) is a real
        # confirmed `transactions` row with a block.
        bundle_hashes = {tx.tx_hash for tx in paid.transactions}
        bundle_hashes |= {line.tx_hash for line in paid.reconciliation.lines}
        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text(
                            "SELECT '0x' || encode(tx_hash, 'hex') FROM transactions "
                            "WHERE status = 'Confirmed' AND block_number IS NOT NULL "
                            "AND block_hash IS NOT NULL AND confirmed_at IS NOT NULL"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert bundle_hashes == set(rows)
        assert "private@example.test" not in json.dumps(
            blocked.model_dump(mode="json", by_alias=True)
        )
        with pytest.raises(EvidenceNotFound):
            await repository.export_request(
                organization_id=uuid.uuid4(), request_id=paid_request_id
            )

        unresolved = SqlAlchemyEvidenceRepository(
            sessions,
            receipt_verifier=_UnresolvedReceiptVerifier(),
            app_version="integration-test",
        )
        with pytest.raises(EvidenceBundleInvalid):
            await unresolved.export_request(
                organization_id=organization_id, request_id=paid_request_id
            )
        schema = json.loads((SCHEMA_PATH).read_text())
        for bundle in (paid, blocked, multi):
            jsonschema.validate(
                bundle.model_dump(mode="json", by_alias=True, exclude_none=True), schema
            )
        return paid.model_dump(mode="json", by_alias=True, exclude_none=True)
    finally:
        await engine.dispose()


def test_sql_exporter_reads_postgres_rows_and_fails_closed() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        result = asyncio.run(_seed_and_export(database_url))
        assert result["status"] == "VALID"
    finally:
        command.downgrade(config, "base")
