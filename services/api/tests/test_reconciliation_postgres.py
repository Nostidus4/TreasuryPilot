"""Reconciliation match, discrepancy and resolve routes against PostgreSQL (REC-003)."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import SessionAccess, UserRecord
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.main import create_app

API_ROOT = Path(__file__).parents[1]
ORG, ASSET, VENDOR, PAYEE, TREASURY = (
    uuid.UUID(f"00000000-0000-7000-8000-000000000c{i:02d}") for i in range(1, 6)
)
FINANCE, OWNER = (uuid.UUID(f"00000000-0000-7000-8000-000000000d{i:02d}") for i in (1, 2))
PAY_BLOCK, FEE = 100, 21_000
INVOICE_HASH = "0x" + "77" * 32


class _Chain:
    finalized = PAY_BLOCK

    async def call(self, chain_id: int, method: str, params: list[object]) -> Any:
        assert method == "eth_getBlockByNumber" and params[0] == "finalized"
        return {"number": hex(self.finalized)}


@pytest.fixture(scope="module")
def url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for the reconciliation integration tests")
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed(database_url))
        yield database_url
    finally:
        command.downgrade(config, "base")


async def _sql(url: str, *queries: tuple[str, dict[str, Any]]) -> list[Any]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            rows: list[Any] = []
            for query, params in queries:
                result = await connection.execute(text(query), params)
                rows = list(result.all()) if result.returns_rows else []
            return rows
    finally:
        await engine.dispose()


async def _seed(url: str) -> None:
    for user in (FINANCE, OWNER):
        await _sql(
            url,
            ("INSERT INTO users (id, email) VALUES (:id, :e)", {"id": user, "e": f"{user}@x.test"}),
        )
    await _sql(
        url,
        ("INSERT INTO organizations (id, name) VALUES (:id, 'Acme')", {"id": ORG}),
        (
            "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
            "VALUES (31337, 'Anvil', true, 3, 'https://explorer.invalid', '[\"http://rpc\"]')",
            {},
        ),
        (
            "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
            "VALUES (:id, 31337, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
            {"id": ASSET},
        ),
        (
            "INSERT INTO treasuries (id, org_id, chain_id, asset_id, module_address) "
            "VALUES (:id, :org, 31337, :asset, decode(repeat('aa', 20), 'hex'))",
            {"id": TREASURY, "org": ORG, "asset": ASSET},
        ),
        (
            "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES (:id, :org, 'V', 'v')",
            {"id": VENDOR, "org": ORG},
        ),
        (
            "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) "
            "VALUES (:id, :t, :org, :vendor, 'Main', decode(repeat('22', 20), 'hex'), 'Proposed')",
            {"id": PAYEE, "t": TREASURY, "org": ORG, "vendor": VENDOR},
        ),
    )


async def _scenario(url: str, *, verified: bool = True, fee: int = FEE) -> uuid.UUID:
    """A Paid request with complete evidence; the knobs break one piece."""

    ids = {name: uuid.uuid4() for name in ("req", "op", "tx", "recon", "att")}
    step = ids["op"].bytes * 2
    await _sql(
        url,
        (
            "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id, "
            "invoice_no, issue_date, due_at, amount, asset_id, status, fingerprint) VALUES (:req, :org, "
            ":t, 31337, :vendor, :payee, :no, '2026-10-01', '2026-10-31', 1000, :asset, 'Paid', "
            ":fp)",
            {
                **ids,
                "org": ORG,
                "t": TREASURY,
                "vendor": VENDOR,
                "payee": PAYEE,
                "asset": ASSET,
                "no": "R-" + ids["req"].hex,
                "fp": ids["req"].bytes * 2,
            },
        ),
        (
            "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, kind, "
            "payload, idempotency_key, status) VALUES (:op, :t, gen_random_uuid(), :req, :step, "
            "'PAY', '{}'::jsonb, :key, 'Confirmed')",
            {**ids, "t": TREASURY, "step": step, "key": "k" + ids["op"].hex},
        ),
        (
            "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, from_address, "
            "status, block_number, fee_wei, confirmed_at) VALUES (:tx, :op, 31337, :hash, 1, "
            "decode(repeat('ee', 20), 'hex'), 'Confirmed', :block, :fee, now())",
            {**ids, "hash": ids["tx"].bytes * 2, "block": PAY_BLOCK, "fee": FEE},
        ),
        (
            "INSERT INTO gas_ledger (id, treasury_id, transaction_id, payer, payer_address, "
            "fee_wei, reverted, day) VALUES (gen_random_uuid(), :t, :tx, 'EXECUTOR', "
            "decode(repeat('ee', 20), 'hex'), :fee, false, '2026-10-02')",
            {**ids, "t": TREASURY, "fee": fee},
        ),
        (
            "INSERT INTO reconciliations (id, org_id, treasury_id, request_id, status) "
            "VALUES (:recon, :org, :t, :req, 'Pending')",
            {**ids, "org": ORG, "t": TREASURY},
        ),
        (
            "INSERT INTO reconciliation_lines (id, reconciliation_id, classification, "
            "operation_id, transaction_id, tx_hash, from_address, amount, block_number, day) "
            "SELECT gen_random_uuid(), :recon, c, :op, :tx, :hash, decode(repeat('ee', 20), "
            "'hex'), a, :block, '2026-10-02' FROM (VALUES ('EXTERNAL_EXPENSE', 1000), "
            "('FEE', :feeline)) AS v(c, a)",
            {**ids, "hash": ids["tx"].bytes * 2, "block": PAY_BLOCK, "feeline": FEE},
        ),
        (
            "INSERT INTO attestations (id, plan_id, request_id, plan_hash, step_ids, "
            "policy_version, executor, nonce, valid_until, evidence_digest, typed_data, "
            "signature, policy_signer) VALUES (:att, gen_random_uuid(), CAST(:step AS bytea), CAST(:step AS bytea), "
            "ARRAY[CAST(:step AS bytea)], CAST(:step AS bytea), '0x', :n, now(), CAST(:step AS bytea), '{}', CAST(:step AS bytea), '0x')",
            {**ids, "step": step, "n": ids["att"].int},
        ),
        (  # the revision FK is irrelevant to this feature
            "SET LOCAL session_replication_role = replica",
            {},
        ),
        (
            "INSERT INTO approvals (id, request_id, revision, approver_address, typed_data, "
            "signature, expires_at, status) VALUES (gen_random_uuid(), :req, 1, "
            "decode(repeat('44', 20), 'hex'), CAST(:typed AS jsonb), :step, now(), 'Valid')",
            {**ids, "step": step, "typed": f'{{"message": {{"invoiceHash": "{INVOICE_HASH}"}}}}'},
        ),
    )
    if verified:
        await _sql(
            url,
            (
                "INSERT INTO verifications (id, operation_id, block_number, expected, observed, "
                "diffs, result) VALUES (gen_random_uuid(), :op, :block, '{}', '{}', '{}', 'PASSED')",
                {**ids, "block": PAY_BLOCK},
            ),
        )
    return ids["recon"]


def _client(
    url: str, role: str = "Finance", user: uuid.UUID = FINANCE
) -> tuple[TestClient, _Chain]:
    app = create_app(settings=Settings(environment="local"))
    engine = create_async_engine(url, poolclass=NullPool)  # one loop per request
    app.state.request_sessions = async_sessionmaker(engine, expire_on_commit=False)
    chain = _Chain()
    app.state.fee_history_provider = chain

    async def member(organization_id: uuid.UUID) -> MemberAccess:
        access = SessionAccess(
            user=UserRecord(user, "u@example.test", None, "active"),
            session_id=uuid.uuid4(),
            step_up_at=datetime.now(UTC),
        )
        return MemberAccess(access=access, organization_id=organization_id, roles=frozenset({role}))

    app.dependency_overrides[require_member] = member
    return TestClient(app), chain


def _path(recon: uuid.UUID, action: str = "") -> str:
    return f"/v1/orgs/{ORG}/reconciliations/{recon}{action}"


def _state(url: str, recon: uuid.UUID) -> Any:
    return asyncio.run(
        _sql(
            url,
            ("SELECT status, matched_by, version FROM reconciliations WHERE id = :r", {"r": recon}),
        )
    )[0]


def test_auto_match_is_off_by_default(url: str) -> None:
    assert (
        asyncio.run(_sql(url, ("SELECT auto_match FROM organizations WHERE id = :o", {"o": ORG})))[
            0
        ][0]
        is False
    )


def test_match_closes_a_finalized_payment_with_complete_evidence(url: str) -> None:
    recon = asyncio.run(_scenario(url))
    client, _ = _client(url)
    detail = client.get(_path(recon)).json()
    assert detail["evidence"]["missing"] == [] and len(detail["lines"]) == 2
    response = client.post(_path(recon, "/match"), json={"note": "ok"})
    assert response.status_code == 200 and response.json()["status"] == "Matched"
    assert _state(url, recon) == ("Matched", "USER", 2)
    assert client.post(_path(recon, "/match"), json={}).status_code == 409  # no longer Pending


def test_match_is_refused_when_evidence_is_incomplete(url: str) -> None:
    recon = asyncio.run(_scenario(url, verified=False))
    client, _ = _client(url)
    response = client.post(_path(recon, "/match"), json={})
    assert response.status_code == 409
    assert response.json()["code"] == "EVIDENCE_INCOMPLETE"
    assert response.json()["missing"] == ["verifications"]
    assert _state(url, recon)[0] == "Pending"


def test_a_stale_fee_line_blocks_the_match(url: str) -> None:
    recon = asyncio.run(_scenario(url, fee=FEE + 1))  # gas_ledger changed after Paid
    response = _client(url)[0].post(_path(recon, "/match"), json={})
    assert response.json()["code"] == "EVIDENCE_INCOMPLETE"
    assert response.json()["missing"] == ["transactions"]


def test_match_waits_for_the_pay_block_to_be_finalized(url: str) -> None:
    recon = asyncio.run(_scenario(url))
    client, chain = _client(url)
    chain.finalized = PAY_BLOCK - 1
    response = client.post(_path(recon, "/match"), json={})
    assert response.status_code == 409 and response.json()["code"] == "NOT_FINALIZED"


def test_roles_and_optimistic_version(url: str) -> None:
    recon = asyncio.run(_scenario(url))
    operator, _ = _client(url, "Operator")
    assert operator.get(_path(recon)).status_code == 200
    assert operator.get(f"/v1/orgs/{ORG}/reconciliations").status_code == 403
    assert operator.post(_path(recon, "/match"), json={}).status_code == 403
    finance, _ = _client(url)
    assert finance.get(f"/v1/orgs/{ORG}/reconciliations?status=Pending").json()["items"]
    stale = finance.post(_path(recon, "/match"), json={}, headers={"If-Match": '"9"'})
    assert stale.status_code == 412 and _state(url, recon)[0] == "Pending"


def test_discrepancy_needs_a_finance_note_and_a_separate_owner_acknowledgment(url: str) -> None:
    recon = asyncio.run(_scenario(url))
    finance, _ = _client(url)
    assert finance.post(_path(recon, "/discrepancy"), json={}).status_code == 422
    assert finance.post(_path(recon, "/discrepancy"), json={"note": "off by 1"}).status_code == 200
    assert finance.post(_path(recon, "/match"), json={}).status_code == 409  # Discrepancy
    noted = finance.post(_path(recon, "/resolve"), json={"note": "fixed upstream"})
    assert noted.json()["status"] == "Discrepancy"  # still waiting for the Owner
    owner_same_user, _ = _client(url, "Owner", FINANCE)
    assert (
        owner_same_user.post(_path(recon, "/resolve"), json={"acknowledge": True}).status_code
        == 409
    )
    assert finance.post(_path(recon, "/resolve"), json={"acknowledge": True}).status_code == 403
    owner, _ = _client(url, "Owner", OWNER)
    assert owner.post(_path(recon, "/resolve"), json={"note": "x"}).status_code == 403
    resolved = owner.post(_path(recon, "/resolve"), json={"acknowledge": True})
    assert resolved.status_code == 200 and resolved.json()["status"] == "Matched"
    assert _state(url, recon)[:2] == ("Matched", "USER")


def _flag(client: TestClient, recon: uuid.UUID) -> None:
    assert client.post(_path(recon, "/discrepancy"), json={"note": "off"}).status_code == 200


def test_owner_may_acknowledge_first_and_resolve_waits_for_finality(url: str) -> None:
    recon = asyncio.run(_scenario(url))
    finance, chain = _client(url)
    _flag(finance, recon)
    owner, _ = _client(url, "Owner", OWNER)
    first = owner.post(_path(recon, "/resolve"), json={"acknowledge": True})
    assert first.json()["status"] == "Discrepancy" and first.json()["version"] == 3
    chain.finalized = PAY_BLOCK - 1
    blocked = finance.post(_path(recon, "/resolve"), json={"note": "fixed"})
    assert blocked.status_code == 409 and blocked.json()["code"] == "NOT_FINALIZED"
    assert _state(url, recon)[0] == "Discrepancy"
    chain.finalized = PAY_BLOCK
    done = finance.post(_path(recon, "/resolve"), json={"note": "fixed"})
    assert done.json()["status"] == "Matched" and done.json()["finalizedAt"]


def test_manual_match_is_a_human_call_on_document_and_amount(url: str) -> None:
    recon = asyncio.run(_scenario(url))
    asyncio.run(
        _sql(
            url,
            (
                "INSERT INTO documents (id, request_id, storage_key, sha256, mime, size) "
                "SELECT gen_random_uuid(), request_id, 'k' || :r, decode(repeat('01', 32), 'hex'), "
                "'application/pdf', 1 FROM reconciliations WHERE id = :rid",
                {"r": recon.hex, "rid": recon},
            ),
            (
                "UPDATE payment_requests SET amount = 999 WHERE id IN (SELECT request_id FROM reconciliations WHERE id = :rid)",
                {"rid": recon},
            ),
        )
    )
    client, _ = _client(url)
    assert (
        client.get(_path(recon)).json()["evidence"]["missing"] == []
    )  # strict checks are auto-only
    assert client.post(_path(recon, "/match"), json={}).json()["status"] == "Matched"


def test_if_match_accepts_weak_and_unquoted_forms(url: str) -> None:
    recon = asyncio.run(_scenario(url))
    client, _ = _client(url)
    assert (
        client.post(_path(recon, "/match"), json={}, headers={"If-Match": 'W/"9"'}).status_code
        == 412
    )
    assert (
        client.post(_path(recon, "/match"), json={}, headers={"If-Match": "1"}).status_code == 200
    )


def _missing(url: str, recon: uuid.UUID) -> list[str]:
    return _client(url)[0].get(_path(recon)).json()["evidence"]["missing"]


def test_stale_lines_cover_tx_hash_status_and_orphan_ledger_rows(url: str) -> None:
    changed = asyncio.run(_scenario(url))
    asyncio.run(
        _sql(
            url,
            (
                "UPDATE transactions SET tx_hash = decode(repeat('99', 32), 'hex') WHERE id IN "
                "(SELECT transaction_id FROM reconciliation_lines WHERE reconciliation_id = :r)",
                {"r": changed},
            ),
        )
    )
    assert _missing(url, changed) == ["transactions"]

    dropped = asyncio.run(_scenario(url))
    asyncio.run(
        _sql(
            url,
            (
                "UPDATE transactions SET status = 'Dropped' WHERE id IN "
                "(SELECT transaction_id FROM reconciliation_lines WHERE reconciliation_id = :r)",
                {"r": dropped},
            ),
        )
    )
    assert _missing(url, dropped) == ["transactions"]

    orphan = asyncio.run(_scenario(url))
    asyncio.run(
        _sql(
            url,
            (
                "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, "
                "from_address, status, block_number, fee_wei) SELECT gen_random_uuid(), "
                "operation_id, 31337, decode(repeat('98', 32), 'hex'), 2, from_address, "
                "'Reverted', 99, 5 FROM reconciliation_lines WHERE reconciliation_id = :r LIMIT 1",
                {"r": orphan},
            ),
            (
                "INSERT INTO gas_ledger (id, treasury_id, transaction_id, payer, payer_address, "
                "fee_wei, reverted, day) SELECT gen_random_uuid(), :t, id, 'EXECUTOR', "
                "from_address, 5, true, '2026-10-02' FROM transactions "
                "WHERE tx_hash = decode(repeat('98', 32), 'hex')",
                {"t": TREASURY},
            ),
        )
    )
    assert _missing(url, orphan) == ["transactions"]
