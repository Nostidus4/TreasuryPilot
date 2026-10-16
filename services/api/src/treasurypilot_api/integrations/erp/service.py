"""ERP sync orchestration: OAuth connections, idempotent export, retries and audit.

Shape of one export: a ``erp_sync_records`` row is committed *before* any network call and
carries a deterministic idempotency key, so a crash or retry re-sends the same key and the
adapter reuses the object it already created. A bill is only ever created as a draft; the
payment waits (``AwaitingApproval``) until a human has approved the bill in the ERP.
"""

from __future__ import annotations

import json
import secrets
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.models import AuditActorType
from treasurypilot_api.audit.writer import AuditActor, AuditEntity
from treasurypilot_api.audit.writer import write as write_audit
from treasurypilot_api.integrations.erp.mapping import (
    DEFAULT_EXPENSE_ACCOUNT,
    ReconciledPayment,
    export_key,
    to_bill,
    to_payment,
)
from treasurypilot_api.integrations.erp.models import ErpConnection, ErpSyncRecord
from treasurypilot_api.integrations.erp.provider import (
    BillState,
    ErpAuthError,
    ErpContext,
    ErpError,
    ErpPermanentError,
    ErpProvider,
    ErpTransientError,
    TokenSet,
)
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.mandate.models import Vendor
from treasurypilot_api.reconciliation.export import load_mapping
from treasurypilot_api.reconciliation.models import Reconciliation, ReconciliationLine
from treasurypilot_api.treasury.models import Asset
from treasurypilot_core.privacy import DecryptionError, FieldCipher

STATE_CONTEXT = "erp_oauth_state"
STATE_TTL = timedelta(minutes=10)
REFRESH_MARGIN = timedelta(minutes=2)
APPROVAL_POLL = timedelta(minutes=15)
BACKOFF_BASE = timedelta(seconds=30)
BACKOFF_CAP = timedelta(hours=1)
MAX_ATTEMPTS = 8


class ErpServiceError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


@dataclass(frozen=True, slots=True)
class Actor:
    """Who triggered an action; ``user_id`` None means the system (scheduled retry)."""

    user_id: uuid.UUID | None

    def audit(self) -> AuditActor:
        if self.user_id is None:
            return AuditActor(AuditActorType.SYSTEM, None)
        return AuditActor(AuditActorType.USER, self.user_id)


def _token_context(kind: str) -> str:
    return f"erp_connections.{kind}"


class ErpService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cipher: FieldCipher,
        providers: Mapping[str, ErpProvider],
        *,
        redirect_uri: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._cipher = cipher
        self._providers = providers
        self._redirect_uri = redirect_uri
        self._now = now

    # --- providers & OAuth ---------------------------------------------------------------

    def provider(self, key: str) -> ErpProvider:
        found = self._providers.get(key)
        if found is None:
            raise ErpServiceError(404, "ERP_PROVIDER_UNKNOWN", "Unknown or unconfigured ERP.")
        return found

    def provider_keys(self) -> list[str]:
        return sorted(self._providers)

    def authorize_url(self, provider_key: str, org_id: uuid.UUID, user_id: uuid.UUID) -> str:
        provider = self.provider(provider_key)
        state = self._cipher.encrypt_text(
            json.dumps(
                {
                    "o": str(org_id),
                    "u": str(user_id),
                    "p": provider_key,
                    "x": (self._now() + STATE_TTL).timestamp(),
                    "n": secrets.token_hex(8),
                }
            ),
            context=STATE_CONTEXT,
        )
        return provider.authorize_url(state, self._redirect_uri)

    def _check_state(
        self, state: str, provider_key: str, org_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        try:
            data = json.loads(self._cipher.decrypt_text(state, context=STATE_CONTEXT))
            valid = (
                data["o"] == str(org_id)
                and data["u"] == str(user_id)
                and data["p"] == provider_key
                and float(data["x"]) >= self._now().timestamp()
            )
        except (DecryptionError, ValueError, KeyError, TypeError):
            valid = False
        if not valid:
            raise ErpServiceError(400, "ERP_STATE_INVALID", "The authorisation state is invalid.")

    def _seal(self, tokens: TokenSet) -> dict[str, object]:
        return {
            "access_token_enc": self._cipher.encrypt_text(
                tokens.access_token, context=_token_context("access")
            ),
            "refresh_token_enc": self._cipher.encrypt_text(
                tokens.refresh_token, context=_token_context("refresh")
            ),
            "token_expires_at": tokens.expires_at,
            "scopes": tokens.scopes or None,
        }

    async def connect(
        self, provider_key: str, org_id: uuid.UUID, user_id: uuid.UUID, code: str, state: str
    ) -> ErpConnection:
        provider = self.provider(provider_key)
        self._check_state(state, provider_key, org_id, user_id)
        try:
            tokens = await provider.exchange_code(code, self._redirect_uri)
            tenant = await provider.resolve_tenant(tokens.access_token)
        except ErpError as error:
            raise ErpServiceError(502, "ERP_CONNECT_FAILED", str(error)) from None
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(ErpConnection)
                .where(ErpConnection.org_id == org_id, ErpConnection.provider == provider_key)
                .with_for_update()
            )
            if row is None:
                row = ErpConnection(
                    id=uuid.uuid4(),
                    org_id=org_id,
                    provider=provider_key,
                    external_tenant_id=tenant.tenant_id,
                    tenant_name=tenant.name,
                    connected_by=user_id,
                    **self._seal(tokens),
                )
                session.add(row)
            else:
                row.external_tenant_id = tenant.tenant_id
                row.tenant_name = tenant.name
                row.status = "Connected"
                row.connected_by = user_id
                row.updated_at = self._now()
                for name, value in self._seal(tokens).items():
                    setattr(row, name, value)
            await session.flush()
            await write_audit(
                session,
                org_id=org_id,
                actor=AuditActor(AuditActorType.USER, user_id),
                action="erp.connected",
                entity=AuditEntity("erp_connection", row.id),
                data={"provider": provider_key, "tenantId": tenant.tenant_id},
            )
            return row

    async def connection(self, session: AsyncSession, org_id: uuid.UUID, key: str) -> ErpConnection:
        row = await session.scalar(
            select(ErpConnection).where(
                ErpConnection.org_id == org_id, ErpConnection.provider == key
            )
        )
        if row is None:
            raise ErpServiceError(404, "ERP_NOT_CONNECTED", "This ERP is not connected.")
        return row

    async def get_connection(self, org_id: uuid.UUID, key: str) -> ErpConnection | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(ErpConnection).where(
                    ErpConnection.org_id == org_id, ErpConnection.provider == key
                )
            )

    async def disconnect(self, org_id: uuid.UUID, user_id: uuid.UUID, key: str) -> None:
        async with self._sessions() as session, session.begin():
            row = await self.connection(session, org_id, key)
            await session.delete(row)
            await session.flush()
            await write_audit(
                session,
                org_id=org_id,
                actor=AuditActor(AuditActorType.USER, user_id),
                action="erp.disconnected",
                entity=AuditEntity("erp_connection", row.id),
                data={"provider": key},
            )

    async def set_payment_account(
        self, org_id: uuid.UUID, user_id: uuid.UUID, key: str, code: str
    ) -> ErpConnection:
        async with self._sessions() as session, session.begin():
            row = await self.connection(session, org_id, key)
            row.payment_account_code = code
            row.updated_at = self._now()
            await write_audit(
                session,
                org_id=org_id,
                actor=AuditActor(AuditActorType.USER, user_id),
                action="erp.settings_changed",
                entity=AuditEntity("erp_connection", row.id),
                data={"provider": key, "paymentAccountCode": code},
            )
            return row

    # --- tokens --------------------------------------------------------------------------

    async def _context(self, connection_id: uuid.UUID) -> ErpContext:
        """Decrypt the access token, refreshing (and persisting the rotated pair) if due."""

        async with self._sessions() as session:
            row = await session.scalar(
                select(ErpConnection).where(ErpConnection.id == connection_id).with_for_update()
            )
            if row is None:
                raise ErpServiceError(404, "ERP_NOT_CONNECTED", "This ERP is not connected.")
            if row.status != "Connected":
                raise ErpAuthError("The connection needs to be re-authorised")
            provider = self.provider(row.provider)
            try:
                if row.token_expires_at - REFRESH_MARGIN <= self._now():
                    refresh = self._cipher.decrypt_text(
                        row.refresh_token_enc, context=_token_context("refresh")
                    )
                    tokens = await provider.refresh(refresh)
                    for name, value in self._seal(tokens).items():
                        setattr(row, name, value)
                    row.updated_at = self._now()
                    access = tokens.access_token
                else:
                    access = self._cipher.decrypt_text(
                        row.access_token_enc, context=_token_context("access")
                    )
            except (ErpAuthError, DecryptionError):
                row.status = "ReauthRequired"
                row.updated_at = self._now()
                await write_audit(
                    session,
                    org_id=row.org_id,
                    actor=AuditActor(AuditActorType.SYSTEM, None),
                    action="erp.reauth_required",
                    entity=AuditEntity("erp_connection", row.id),
                    data={"provider": row.provider},
                )
                await session.commit()  # keep the status change before re-raising
                raise ErpAuthError("The connection needs to be re-authorised") from None
            context = ErpContext(row.external_tenant_id, access)
            await session.commit()  # persist a rotated refresh token before using it
            return context

    # --- export --------------------------------------------------------------------------

    async def _load(
        self, session: AsyncSession, org_id: uuid.UUID, reconciliation_id: uuid.UUID
    ) -> ReconciledPayment:
        row = (
            await session.execute(
                select(Reconciliation, PaymentRequest, Vendor.name, Asset.symbol, Asset.decimals)
                .join(PaymentRequest, PaymentRequest.id == Reconciliation.request_id)
                .join(Vendor, Vendor.id == PaymentRequest.vendor_id)
                .join(Asset, Asset.id == PaymentRequest.asset_id)
                .where(Reconciliation.id == reconciliation_id, Reconciliation.org_id == org_id)
            )
        ).one_or_none()
        if row is None:
            raise ErpServiceError(
                404, "RECONCILIATION_NOT_FOUND", "The reconciliation is unavailable."
            )
        rec, request, vendor, symbol, decimals = row
        if rec.status == "Discrepancy":
            raise ErpServiceError(
                409, "RECONCILIATION_DISCREPANCY", "Resolve the discrepancy first."
            )
        if (
            request.invoice_no is None
            or request.issue_date is None
            or request.due_at is None
            or request.amount is None
        ):
            raise ErpServiceError(409, "REQUEST_INCOMPLETE", "The request has no invoice data.")
        line = await session.scalar(
            select(ReconciliationLine)
            .where(
                ReconciliationLine.reconciliation_id == rec.id,
                ReconciliationLine.classification == "EXTERNAL_EXPENSE",
            )
            .order_by(ReconciliationLine.block_number.desc(), ReconciliationLine.id)
            .limit(1)
        )
        mapping = await load_mapping(session, org_id)
        code = mapping.get(("EXTERNAL_EXPENSE", "DEBIT"), (DEFAULT_EXPENSE_ACCOUNT, ""))[0]
        return ReconciledPayment(
            reconciliation_id=rec.id,
            request_id=request.id,
            status=rec.status,
            invoice_no=request.invoice_no,
            vendor_name=vendor,
            issue_date=request.issue_date,
            due_date=request.due_at,
            amount=int(request.amount),
            asset_symbol=symbol,
            asset_decimals=int(decimals),
            fiat_amount_minor=(
                int(request.fiat_amount_minor_units)
                if request.fiat_amount_minor_units is not None
                else None
            ),
            fiat_currency=request.fiat_currency,
            tx_hash=line.tx_hash if line else None,
            paid_on=line.day if line else None,
            expense_account_code=code,
        )

    async def sync(
        self, org_id: uuid.UUID, actor: Actor, provider_key: str, reconciliation_id: uuid.UUID
    ) -> list[ErpSyncRecord]:
        """Queue (idempotently) and run the bill and, once Matched, the payment."""

        self.provider(provider_key)
        async with self._sessions() as session, session.begin():
            connection = await self.connection(session, org_id, provider_key)
            data = await self._load(session, org_id, reconciliation_id)
            kinds = ["BILL"]
            if data.status == "Matched":
                kinds.append("PAYMENT")
            ids: list[uuid.UUID] = []
            for kind in kinds:
                record = await session.scalar(
                    select(ErpSyncRecord)
                    .where(
                        ErpSyncRecord.connection_id == connection.id,
                        ErpSyncRecord.reconciliation_id == reconciliation_id,
                        ErpSyncRecord.kind == kind,
                    )
                    .with_for_update()
                )
                if record is None:
                    record = ErpSyncRecord(
                        id=uuid.uuid4(),
                        org_id=org_id,
                        connection_id=connection.id,
                        reconciliation_id=reconciliation_id,
                        kind=kind,
                        idempotency_key=export_key(kind, reconciliation_id, connection.id),
                    )
                    session.add(record)
                elif record.status == "Failed":
                    record.status = (
                        "Pending"  # an explicit re-sync gives a failed record a new life
                    )
                    record.attempts = 0
                    record.next_attempt_at = self._now()
                await session.flush()
                ids.append(record.id)
        return [await self.run_record(rid, actor) for rid in ids]

    async def retry_due(
        self, org_id: uuid.UUID | None = None, limit: int = 50
    ) -> list[ErpSyncRecord]:
        """Run every record whose backoff has elapsed; safe to call from a scheduler."""

        async with self._sessions() as session:
            query = (
                select(ErpSyncRecord.id)
                .where(
                    ErpSyncRecord.status.in_(("Pending", "AwaitingApproval")),
                    ErpSyncRecord.next_attempt_at <= self._now(),
                )
                .order_by(ErpSyncRecord.kind, ErpSyncRecord.next_attempt_at)
                .limit(limit)
            )
            if org_id is not None:
                query = query.where(ErpSyncRecord.org_id == org_id)
            ids = list(await session.scalars(query))
        return [await self.run_record(rid, Actor(None)) for rid in ids]

    async def run_record(self, record_id: uuid.UUID, actor: Actor) -> ErpSyncRecord:
        async with self._sessions() as session:
            record = await session.get(ErpSyncRecord, record_id)
            if record is None:
                raise ErpServiceError(404, "ERP_SYNC_NOT_FOUND", "Unknown sync record.")
            if record.status == "Synced":
                return record
            connection = await session.get(ErpConnection, record.connection_id)
            assert connection is not None  # FK
            provider = self.provider(connection.provider)
            kind, org_id, record_key = record.kind, record.org_id, record.idempotency_key
            data = await self._load(session, org_id, record.reconciliation_id)
            account = connection.payment_account_code
            bill_record = None
            if kind == "PAYMENT":
                bill_record = await session.scalar(
                    select(ErpSyncRecord).where(
                        ErpSyncRecord.connection_id == record.connection_id,
                        ErpSyncRecord.reconciliation_id == record.reconciliation_id,
                        ErpSyncRecord.kind == "BILL",
                    )
                )
        outcome: tuple[str, str | None, str | None, str | None] = ("Pending", None, None, None)
        delay: timedelta | None = None
        try:
            if kind == "PAYMENT" and (bill_record is None or bill_record.status != "Synced"):
                bill_record = await self.run_record(bill_record.id, actor) if bill_record else None
                if bill_record is None or bill_record.status != "Synced":
                    raise ErpTransientError("The bill is not in the ERP yet")
            context = await self._context(record.connection_id)
            if kind == "BILL":
                created = await provider.create_draft_bill(context, to_bill(data, record_key))
                outcome = ("Synced", created.external_id, created.status, None)
            else:
                assert bill_record is not None and bill_record.external_id is not None
                if not account:
                    raise ErpPermanentError("PAYMENT_ACCOUNT_MISSING: set the bank account code")
                status = await provider.bill_status(context, bill_record.external_id)
                if status.state is BillState.DRAFT:
                    outcome = ("AwaitingApproval", None, status.raw, "Waiting for bill approval")
                    delay = APPROVAL_POLL
                elif status.state is BillState.APPROVED:
                    paid = await provider.create_payment(
                        context, to_payment(data, account, record_key), bill_record.external_id
                    )
                    outcome = ("Synced", paid.external_id, paid.status, None)
                else:
                    raise ErpPermanentError(
                        f"BILL_{status.state.value}: bill cannot take a payment"
                    )
        except ErpTransientError as error:
            outcome = ("Pending", None, None, str(error)[:200])
            delay = max(
                timedelta(seconds=error.retry_after or 0), self._backoff(record.attempts + 1)
            )
        except ErpAuthError as error:
            outcome = ("Pending", None, None, str(error)[:200])
            delay = BACKOFF_CAP
        except ErpPermanentError as error:
            outcome = ("Failed", None, None, str(error)[:200])
        return await self._finish(record_id, actor, outcome, delay)

    @staticmethod
    def _backoff(attempt: int) -> timedelta:
        delay: timedelta = BACKOFF_BASE * (2 ** min(attempt - 1, 20))
        return min(delay, BACKOFF_CAP)

    async def _finish(
        self,
        record_id: uuid.UUID,
        actor: Actor,
        outcome: tuple[str, str | None, str | None, str | None],
        delay: timedelta | None,
    ) -> ErpSyncRecord:
        status, external_id, external_status, error = outcome
        async with self._sessions() as session, session.begin():
            record = await session.scalar(
                select(ErpSyncRecord).where(ErpSyncRecord.id == record_id).with_for_update()
            )
            assert record is not None
            record.attempts += 1
            if status == "Pending" and record.attempts >= MAX_ATTEMPTS:
                status = "Failed"
            record.status = status
            record.last_error = error
            record.updated_at = self._now()
            if external_id:
                record.external_id = external_id
            if external_status is not None:
                record.external_status = external_status
            record.next_attempt_at = self._now() + (delay or timedelta(0))
            action = {
                "Synced": "erp.bill_drafted" if record.kind == "BILL" else "erp.payment_recorded",
                "Failed": "erp.sync_failed",
            }.get(status)
            if action:
                await write_audit(
                    session,
                    org_id=record.org_id,
                    actor=actor.audit(),
                    action=action,
                    entity=AuditEntity("erp_sync_record", record.id),
                    data={
                        "kind": record.kind,
                        "reconciliationId": str(record.reconciliation_id),
                        "externalId": record.external_id,
                        "attempts": record.attempts,
                        "error": record.last_error,
                    },
                )
            await session.flush()
            session.expunge(record)
            return record

    async def records(self, org_id: uuid.UUID, key: str) -> list[ErpSyncRecord]:
        async with self._sessions() as session:
            connection = await self.connection(session, org_id, key)
            return list(
                await session.scalars(
                    select(ErpSyncRecord)
                    .where(ErpSyncRecord.connection_id == connection.id)
                    .order_by(ErpSyncRecord.created_at.desc())
                    .limit(200)
                )
            )
