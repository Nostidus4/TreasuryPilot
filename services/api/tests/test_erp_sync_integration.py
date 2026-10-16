"""ERP framework against PostgreSQL with a fake provider (REC-L01).

Covers encrypted token storage and rotation, idempotent export, bill-as-draft, the payment
waiting for human approval, retries with backoff, re-authorisation and audit.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import SessionAccess, UserRecord
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.integrations.erp.provider import (
    BillState,
    BillStatus,
    ErpAuthError,
    ErpBill,
    ErpContext,
    ErpObject,
    ErpPayment,
    ErpTenant,
    ErpTransientError,
    TokenSet,
)
from treasurypilot_api.integrations.erp.service import Actor, ErpService, ErpServiceError
from treasurypilot_api.main import create_app
from treasurypilot_core.privacy import FieldCipher, FieldEncryptionKey
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.reconcile.build import build_reconciliation

pytestmark = pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

API_ROOT = Path(__file__).parents[1]
CHAIN = 31337
USDC = bytes.fromhex("11" * 20)
ORG, OTHER_ORG = uuid.uuid4(), uuid.uuid4()
USER = uuid.uuid4()
ASSET = uuid.uuid4()
START = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


@dataclass
class FakeErp:
    """In-memory ERP: creates are idempotent by reference; nothing here can approve a bill."""

    key: str = "xero"
    display_name: str = "Fake ERP"
    bills: dict[str, dict[str, Any]] = field(default_factory=dict)
    payments: dict[str, dict[str, Any]] = field(default_factory=dict)
    failures: list[Exception] = field(default_factory=list)
    refreshes: int = 0
    refresh_error: Exception | None = None
    create_calls: int = 0
    clock: Clock = field(default_factory=Clock)

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        return f"https://erp.invalid/auth?state={state}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenSet:
        assert code == "good-code"
        return TokenSet("access-0", "refresh-0", self.clock.now + timedelta(minutes=30), "s")

    async def refresh(self, refresh_token: str) -> TokenSet:
        if self.refresh_error:
            raise self.refresh_error
        self.refreshes += 1
        return TokenSet(
            f"access-{self.refreshes}",
            f"refresh-{self.refreshes}",
            self.clock.now + timedelta(minutes=30),
        )

    async def resolve_tenant(self, access_token: str) -> ErpTenant:
        return ErpTenant("tenant-1", "Demo Co")

    def _maybe_fail(self) -> None:
        if self.failures:
            raise self.failures.pop(0)

    async def create_draft_bill(self, ctx: ErpContext, bill: ErpBill) -> ErpObject:
        self._maybe_fail()
        self.create_calls += 1
        existing = self.bills.get(bill.reference)
        if existing:
            return ErpObject(existing["id"], existing["state"].value, created=False)
        record = {"id": f"bill-{len(self.bills) + 1}", "state": BillState.DRAFT, "bill": bill}
        self.bills[bill.reference] = record
        return ErpObject(record["id"], "DRAFT")

    def _by_id(self, external_id: str) -> dict[str, Any]:
        return next(b for b in self.bills.values() if b["id"] == external_id)

    async def bill_status(self, ctx: ErpContext, external_id: str) -> BillStatus:
        self._maybe_fail()
        state = self._by_id(external_id)["state"]
        return BillStatus(state, state.value)

    async def create_payment(
        self, ctx: ErpContext, payment: ErpPayment, bill_external_id: str
    ) -> ErpObject:
        assert self._by_id(bill_external_id)["state"] is BillState.APPROVED
        existing = self.payments.get(payment.tx_hash)
        if existing:
            return ErpObject(existing["id"], created=False)
        self.payments[payment.tx_hash] = {"id": f"pay-{len(self.payments) + 1}", "p": payment}
        return ErpObject(self.payments[payment.tx_hash]["id"])

    def human_approves(self, reference: str) -> None:
        self.bills[reference]["state"] = BillState.APPROVED


async def _seed_request(pool: Any, org: uuid.UUID, invoice: str, amount: int) -> uuid.UUID:
    treasury, vendor, payee = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await pool.execute(
        "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES ($1, $2, $3, $4)",
        treasury, org, CHAIN, ASSET,
    )  # fmt: skip
    await pool.execute(
        "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES ($1, $2, 'Acme Supplies', $3)",
        vendor, org, invoice.lower(),
    )  # fmt: skip
    await pool.execute(
        "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) "
        "VALUES ($1, $2, $3, $4, 'Main', $5, 'Proposed')",
        payee, treasury, org, vendor, b"\x22" * 20,
    )  # fmt: skip
    request, attestation = uuid.uuid4(), uuid.uuid4()
    await pool.execute(
        "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id, "
        "invoice_no, issue_date, due_at, amount, asset_id, status, fingerprint) VALUES "
        "($1, $2, $3, $4, $5, $6, $7, '2026-10-01', '2026-10-31', $8, $9, 'Paid', $10)",
        request, org, treasury, CHAIN, vendor, payee, invoice, amount, ASSET, request.bytes * 2,
    )  # fmt: skip
    await pool.execute(
        "INSERT INTO attestations (id, plan_id, request_id, plan_hash, step_ids, policy_version, "
        "executor, nonce, valid_until, evidence_digest, typed_data, signature, policy_signer) "
        "VALUES ($1, $2, $3, $4, $5, $4, '0x', $6, now(), $4, '{}', $4, '0x')",
        attestation, uuid.uuid4(), request.bytes * 2, attestation.bytes * 2, [], attestation.int,
    )  # fmt: skip
    step_id, step_row, op, tx = (uuid.uuid4() for _ in range(4))
    await pool.execute(
        "INSERT INTO plan_steps (id, attestation_id, plan_id, seq, step_id, action, request_id, "
        "treasury_address, chain_id, from_address, to_address, asset_address, amount) VALUES "
        "($1, $2, $3, 0, $4, 1, $5, $6, $7, $8, $9, $10, $11)",
        step_row, attestation, uuid.uuid4(), step_id.bytes * 2, request.bytes * 2,
        b"\x0a" * 20, CHAIN, b"\x0b" * 20, b"\x0c" * 20, USDC, amount,
    )  # fmt: skip
    await pool.execute(
        "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, kind, "
        "payload, idempotency_key, status) VALUES ($1, $2, $3, $4, $5, 'PAY'::operation_kind, "
        "'{}', $6, 'Confirmed')",
        op, treasury, step_row, request, step_id.bytes * 2, "rec:" + op.hex,
    )  # fmt: skip
    when = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    await pool.execute(
        "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, from_address, "
        "status, block_number, fee_wei, confirmed_at) VALUES ($1, $2, $3, $4, 0, $5, "
        "'Confirmed', 100, 21000, $6)",
        tx, op, CHAIN, tx.bytes * 2, b"\xee" * 20, when,
    )  # fmt: skip
    await pool.execute(
        "INSERT INTO gas_ledger (id, treasury_id, transaction_id, payer, payer_address, fee_wei, "
        "reverted, day) VALUES (gen_random_uuid(), $1, $2, 'EXECUTOR', $3, 21000, false, $4)",
        treasury, tx, b"\xee" * 20, when.date(),
    )  # fmt: skip
    async with pool.acquire() as connection:
        await build_reconciliation(connection, request)
    return request


async def _seed(url: str) -> dict[str, uuid.UUID]:
    pool = await create_worker_pool(url.replace("+asyncpg", ""), min_size=1, max_size=1)
    ids: dict[str, uuid.UUID] = {}
    try:
        await pool.execute(
            "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
            "VALUES ($1, 'Anvil', true, 3, 'https://explorer.invalid', '[\"http://rpc\"]')",
            CHAIN,
        )
        await pool.execute(
            "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
            "VALUES ($1, $2, $3, 'USDC', 6, 'Circle')",
            ASSET, CHAIN, USDC,
        )  # fmt: skip
        for org in (ORG, OTHER_ORG):
            await pool.execute(
                "INSERT INTO organizations (id, name) VALUES ($1, $2)", org, str(org)
            )
        await pool.execute(
            "INSERT INTO users (id, email, status) VALUES ($1, 'f@example.test', 'active')", USER
        )
        for name, invoice, amount in (
            ("pending", "INV-P", 1_500_000),
            ("matched", "INV-M", 2_000_000),
            ("subcent", "INV-S", 1_500_001),
            ("flaky", "INV-F", 3_000_000),
            ("disc", "INV-D", 1_000_000),
        ):
            request = await _seed_request(pool, ORG, invoice, amount)
            rec = await pool.fetchval(
                "SELECT id FROM reconciliations WHERE request_id = $1", request
            )
            ids[name] = rec
        for name, status in (("matched", "Matched"), ("flaky", "Matched"), ("disc", "Discrepancy")):
            await pool.execute(
                "UPDATE reconciliations SET status = $2 WHERE id = $1", ids[name], status
            )
    finally:
        await pool.close()
    return ids


@pytest.fixture(scope="module")
def db() -> Iterator[tuple[str, dict[str, uuid.UUID]]]:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        yield database_url, asyncio.run(_seed(database_url))
    finally:
        command.downgrade(config, "base")


@dataclass
class Rig:
    service: ErpService
    erp: FakeErp
    clock: Clock
    url: str
    ids: dict[str, uuid.UUID]
    cipher: FieldCipher

    def sql(self, query: str, *args: Any) -> list[Any]:
        async def go() -> list[Any]:
            pool = await create_worker_pool(
                self.url.replace("+asyncpg", ""), min_size=1, max_size=1
            )
            try:
                return list(await pool.fetch(query, *args))
            finally:
                await pool.close()

        return asyncio.run(go())

    def sessions(self) -> async_sessionmaker[Any]:
        return async_sessionmaker(
            create_async_engine(self.url, poolclass=NullPool), expire_on_commit=False
        )


@pytest.fixture
def rig(db: tuple[str, dict[str, uuid.UUID]]) -> Iterator[Rig]:
    url, ids = db
    clock = Clock()
    erp = FakeErp(clock=clock)
    cipher = FieldCipher(FieldEncryptionKey.from_base64(secrets.token_urlsafe(32)))
    sessions = async_sessionmaker(
        create_async_engine(url, poolclass=NullPool), expire_on_commit=False
    )
    service = ErpService(
        sessions, cipher, {"xero": erp}, redirect_uri="https://app.test/cb", now=clock
    )
    holder = Rig(service, erp, clock, url, ids, cipher)
    holder.sql("DELETE FROM erp_sync_records")
    holder.sql("DELETE FROM erp_connections")
    yield holder


def connect(rig: Rig, org: uuid.UUID = ORG) -> None:
    state = rig.service.authorize_url("xero", org, USER).split("state=", 1)[1]
    asyncio.run(rig.service.connect("xero", org, USER, "good-code", state))


def sync(rig: Rig, name: str) -> list[Any]:
    return asyncio.run(rig.service.sync(ORG, Actor(USER), "xero", rig.ids[name]))


def retry(rig: Rig) -> list[Any]:
    return asyncio.run(rig.service.retry_due(ORG))


def test_tokens_are_stored_encrypted_and_bound_to_their_column(rig: Rig) -> None:
    connect(rig)
    (row,) = rig.sql(
        "SELECT access_token_enc, refresh_token_enc, external_tenant_id FROM erp_connections"
    )
    assert row["access_token_enc"].startswith("tpenc:v1:")
    assert "access-0" not in row["access_token_enc"] and "refresh-0" not in row["refresh_token_enc"]
    assert row["external_tenant_id"] == "tenant-1"
    # an envelope copied between columns does not decrypt
    from treasurypilot_core.privacy import DecryptionError

    with pytest.raises(DecryptionError):
        rig.cipher.decrypt_text(row["access_token_enc"], context="erp_connections.refresh")


def test_oauth_state_is_bound_to_org_user_and_expiry(rig: Rig) -> None:
    state = rig.service.authorize_url("xero", ORG, USER).split("state=", 1)[1]
    for org, user, tweak in (
        (OTHER_ORG, USER, None),
        (ORG, uuid.uuid4(), None),
        (ORG, USER, timedelta(minutes=11)),
    ):
        if tweak:
            rig.clock.now = START + tweak
        with pytest.raises(ErpServiceError) as caught:
            asyncio.run(rig.service.connect("xero", org, user, "good-code", state))
        assert caught.value.code == "ERP_STATE_INVALID"
    with pytest.raises(ErpServiceError):
        asyncio.run(rig.service.connect("xero", ORG, USER, "good-code", "garbage"))
    assert rig.sql("SELECT 1 FROM erp_connections") == []


def test_bill_is_pushed_as_draft_and_export_is_idempotent(rig: Rig) -> None:
    connect(rig)
    (bill,) = sync(rig, "pending")
    assert (bill.kind, bill.status, bill.external_id) == ("BILL", "Synced", "bill-1")
    assert rig.erp.bills["INV-P"]["state"] is BillState.DRAFT
    sent = rig.erp.bills["INV-P"]["bill"]
    assert (sent.currency, sent.amount_minor, sent.vendor_name) == ("USD", 150, "Acme Supplies")
    sync(rig, "pending")  # again: no second object, no second call
    assert len(rig.erp.bills) == 1 and rig.erp.create_calls == 1
    assert len(rig.sql("SELECT 1 FROM erp_sync_records")) == 1


def test_crash_between_create_and_record_reuses_the_existing_object(rig: Rig) -> None:
    connect(rig)
    sync(rig, "pending")
    rig.sql("UPDATE erp_sync_records SET status = 'Pending', external_id = NULL")
    (again,) = retry(rig)
    assert again.status == "Synced" and again.external_id == "bill-1"
    assert len(rig.erp.bills) == 1


def test_pending_reconciliation_gets_no_payment(rig: Rig) -> None:
    connect(rig)
    assert [r.kind for r in sync(rig, "pending")] == ["BILL"]


def test_payment_waits_for_human_approval_and_the_sync_never_approves(rig: Rig) -> None:
    connect(rig)
    asyncio.run(rig.service.set_payment_account(ORG, USER, "xero", "090"))
    bill, payment = sync(rig, "matched")
    assert bill.status == "Synced"
    assert (payment.status, payment.last_error) == ("AwaitingApproval", "Waiting for bill approval")
    assert rig.erp.bills["INV-M"]["state"] is BillState.DRAFT and not rig.erp.payments
    # before the poll interval nothing runs; after it, still draft -> still waiting
    assert retry(rig) == []
    rig.clock.now += timedelta(minutes=16)
    (still,) = retry(rig)
    assert still.status == "AwaitingApproval" and not rig.erp.payments
    assert rig.erp.bills["INV-M"]["state"] is BillState.DRAFT
    rig.erp.human_approves("INV-M")
    rig.clock.now += timedelta(minutes=16)
    (done,) = retry(rig)
    assert done.status == "Synced" and done.external_id == "pay-1"
    paid = rig.erp.payments[
        "0x"
        + rig.sql(
            "SELECT encode(tx_hash,'hex') h FROM reconciliation_lines "
            "WHERE reconciliation_id = $1 AND classification = 'EXTERNAL_EXPENSE'",
            rig.ids["matched"],
        )[0]["h"]
    ]["p"]
    assert (paid.amount_minor, paid.payment_account_code, paid.paid_on) == (
        200,
        "090",
        date(2026, 10, 15),
    )


def test_payment_needs_a_bank_account_code_and_resync_recovers(rig: Rig) -> None:
    connect(rig)
    _, payment = sync(rig, "matched")
    assert payment.status == "Failed" and "PAYMENT_ACCOUNT_MISSING" in (payment.last_error or "")
    assert not rig.erp.payments
    asyncio.run(rig.service.set_payment_account(ORG, USER, "xero", "090"))
    rig.erp.human_approves("INV-M")
    _, payment = sync(rig, "matched")  # an explicit re-sync revives the failed record
    assert payment.status == "Synced" and len(rig.erp.payments) == 1


def test_transient_errors_back_off_and_honour_retry_after(rig: Rig) -> None:
    connect(rig)
    rig.erp.failures = [
        ErpTransientError("rate limited", retry_after=300),
        ErpTransientError("503"),
    ]
    (bill,) = sync(rig, "pending")
    assert (bill.status, bill.attempts) == ("Pending", 1)
    assert bill.next_attempt_at == START + timedelta(seconds=300)  # Retry-After > 30 s backoff
    assert retry(rig) == []
    rig.clock.now = START + timedelta(seconds=301)
    (second,) = retry(rig)
    assert (second.status, second.attempts) == ("Pending", 2)
    assert second.next_attempt_at == rig.clock.now + timedelta(seconds=60)  # backoff doubled
    rig.clock.now += timedelta(seconds=61)
    (third,) = retry(rig)
    assert third.status == "Synced" and third.attempts == 3


def test_permanent_failure_is_not_retried_until_resynced(rig: Rig) -> None:
    connect(rig)
    (bill,) = sync(rig, "subcent")
    assert bill.status == "Failed" and "AMOUNT_NOT_REPRESENTABLE" in (bill.last_error or "")
    rig.clock.now += timedelta(days=1)
    assert retry(rig) == [] and not rig.erp.bills


def test_discrepancy_is_refused(rig: Rig) -> None:
    connect(rig)
    with pytest.raises(ErpServiceError) as caught:
        sync(rig, "disc")
    assert caught.value.code == "RECONCILIATION_DISCREPANCY"


def test_expiring_token_is_refreshed_and_the_rotated_pair_is_persisted(rig: Rig) -> None:
    connect(rig)
    rig.clock.now += timedelta(minutes=29)  # inside the 2 minute margin
    sync(rig, "pending")
    assert rig.erp.refreshes == 1
    (row,) = rig.sql("SELECT access_token_enc, refresh_token_enc FROM erp_connections")
    assert (
        rig.cipher.decrypt_text(row["refresh_token_enc"], context="erp_connections.refresh")
        == "refresh-1"
    )
    assert (
        rig.cipher.decrypt_text(row["access_token_enc"], context="erp_connections.access")
        == "access-1"
    )


def test_dead_refresh_token_flags_reauthorisation_and_audits(rig: Rig) -> None:
    connect(rig)
    rig.clock.now += timedelta(minutes=29)
    rig.erp.refresh_error = ErpAuthError("invalid_grant")
    (bill,) = sync(rig, "pending")
    assert bill.status == "Pending" and bill.external_id is None
    assert rig.sql("SELECT status FROM erp_connections")[0]["status"] == "ReauthRequired"
    actions = [r["action"] for r in rig.sql("SELECT action FROM audit_log WHERE org_id = $1", ORG)]
    assert "erp.reauth_required" in actions
    connect(rig)  # reconnecting restores the connection
    assert rig.sql("SELECT status FROM erp_connections")[0]["status"] == "Connected"


def test_every_step_is_audited_without_secrets(rig: Rig) -> None:
    connect(rig)
    sync(rig, "pending")
    rows = rig.sql(
        "SELECT action, data::text AS data FROM audit_log WHERE org_id = $1 AND action LIKE 'erp.%'",
        ORG,
    )
    assert {"erp.connected", "erp.bill_drafted"} <= {r["action"] for r in rows}
    assert not any("access-0" in r["data"] or "refresh-0" in r["data"] for r in rows)


def test_disconnect_removes_tokens_and_blocks_sync(rig: Rig) -> None:
    connect(rig)
    asyncio.run(rig.service.disconnect(ORG, USER, "xero"))
    assert rig.sql("SELECT 1 FROM erp_connections") == []
    with pytest.raises(ErpServiceError) as caught:
        sync(rig, "pending")
    assert caught.value.code == "ERP_NOT_CONNECTED"


def test_other_orgs_reconciliations_are_not_exportable(rig: Rig) -> None:
    connect(rig, OTHER_ORG)
    with pytest.raises(ErpServiceError) as caught:
        asyncio.run(rig.service.sync(OTHER_ORG, Actor(USER), "xero", rig.ids["pending"]))
    assert caught.value.code == "RECONCILIATION_NOT_FOUND"


def _client(rig: Rig, role: str) -> TestClient:
    app = create_app(settings=Settings(environment="local"))
    app.state.erp_service = rig.service

    async def member(organization_id: uuid.UUID) -> MemberAccess:
        access = SessionAccess(
            user=UserRecord(USER, "f@example.test", None, "active"),
            session_id=uuid.uuid4(),
            step_up_at=datetime.now(UTC),
        )
        return MemberAccess(access=access, organization_id=organization_id, roles=frozenset({role}))

    app.dependency_overrides[require_member] = member
    return TestClient(app)


def test_routes_roles_and_flow(rig: Rig) -> None:
    base = f"/v1/orgs/{ORG}/integrations/erp"
    owner = _client(rig, "Owner")
    url = owner.post(f"{base}/xero/authorize").json()["url"]
    state = url.split("state=", 1)[1]
    assert (
        owner.post(f"{base}/xero/callback", json={"code": "x", "state": "bad"}).status_code == 400
    )
    connected = owner.post(f"{base}/xero/callback", json={"code": "good-code", "state": state})
    assert connected.status_code == 200 and "token" not in connected.text.lower()
    assert (
        owner.get(f"{base}/providers").json()["items"][0]["connection"]["tenantName"] == "Demo Co"
    )
    # Finance may sync but not connect; Operator may do neither
    finance = _client(rig, "Finance")
    assert finance.post(f"{base}/xero/authorize").status_code == 403
    synced = finance.post(f"{base}/xero/sync", json={"reconciliationId": str(rig.ids["pending"])})
    assert synced.status_code == 200 and synced.json()["items"][0]["status"] == "Synced"
    assert finance.get(f"{base}/xero/records").json()["items"][0]["kind"] == "BILL"
    assert (
        _client(rig, "Operator")
        .post(f"{base}/xero/sync", json={"reconciliationId": str(rig.ids["pending"])})
        .status_code
        == 403
    )
    assert owner.post(f"{base}/nope/authorize").status_code == 404
    assert owner.put(f"{base}/xero/settings", json={"paymentAccountCode": "090"}).status_code == 200
    assert owner.delete(f"{base}/xero").status_code == 204
