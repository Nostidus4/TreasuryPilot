"""Period export of reconciliation lines as CSV or journal CSV (REC-004, FR-607, FR-307)."""

from __future__ import annotations

import csv
import io
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.models import AuditActorType
from treasurypilot_api.audit.writer import AuditActor, AuditEntity
from treasurypilot_api.audit.writer import write as write_audit
from treasurypilot_api.execution.models import Transaction
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import Organization, OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.mandate.models import Vendor
from treasurypilot_api.reconciliation.models import (
    AccountMapping,
    Reconciliation,
    ReconciliationLine,
)
from treasurypilot_api.treasury.models import Asset, Treasury
from treasurypilot_core.money import BaseUnits

logger = logging.getLogger(__name__)

ETH_DECIMALS = 18
SNAPSHOT_TOLERANCE = timedelta(days=1)
MAX_PERIOD_DAYS = 366

# Generic default mapping (M11-D6): class -> (debit, credit) as (code, name).
# Per-org rows in account_mappings override one side of a class at a time.
GENERIC_MAPPING: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "EXTERNAL_EXPENSE": (("6000", "Expense"), ("1110", "Wallet O_i")),
    "INTERNAL_TRANSFER": (("1110", "Wallet O_i"), ("1100", "Wallet T")),
    "CONVERSION": (("1110", "Wallet O_i"), ("1100", "Wallet T")),
    "LENDING_TRANSFER": (("1300", "Lending Position"), ("1100", "Wallet T")),
    "FEE": (("6100", "Bank & Fees"), ("1200", "Executor Gas")),
    "SUPPLY_INTEREST": (("1300", "Lending Position"), ("4100", "Interest Income")),
}
Mapping = dict[tuple[str, str], tuple[str, str]]  # (class, "DEBIT"|"CREDIT") -> (code, name)

CSV_HEADER = (
    "date",
    "request id",
    "vendor",
    "invoice no",
    "class",
    "amount",
    "asset",
    "tx hash",
    "fee (ETH)",
    "status",
    "matched by",
)
JOURNAL_HEADER = (
    "date",
    "request id",
    "class",
    "account code",
    "account name",
    "debit",
    "credit",
    "asset",
    "tx hash",
    "status",
)


class ExportTotalsMismatch(Exception):
    """Exported class totals differ from the independent on-chain totals (M11-D7)."""

    def __init__(self, diffs: list[tuple[str, str, int, int]]) -> None:
        self.diffs = diffs  # (class, asset, expected, exported)
        super().__init__(
            "export totals differ from on-chain totals: "
            + "; ".join(f"{c}/{a} expected {e} exported {x}" for c, a, e, x in diffs)
        )


class ExportAssetUnknown(Exception):
    """A line's ERC-20 has no assets row, so its decimals cannot be known."""


@dataclass(frozen=True)
class ExportLine:
    day: date | None
    request_id: uuid.UUID | None
    vendor: str
    invoice_no: str
    classification: str
    amount: int
    decimals: int
    asset: str
    tx_hash: bytes
    fee_wei: int | None
    status: str
    matched_by: str


def neutralize(value: object) -> str:
    """Prefix formula-leading cells with an apostrophe (FR-307)."""
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else text


def _dec(amount: int, decimals: int) -> str:
    return BaseUnits(amount).format(decimals)


def _hash(line: ExportLine) -> str:
    return "0x" + line.tx_hash.hex() if line.tx_hash else ""


def _check_totals(lines: list[ExportLine], expected: dict[tuple[str, str], int]) -> None:
    exported: dict[tuple[str, str], int] = defaultdict(int)
    for line in lines:
        exported[(line.classification, line.asset)] += line.amount
    diffs = [
        (c, a, expected.get((c, a), 0), exported.get((c, a), 0))
        for c, a in sorted(expected.keys() | exported.keys())
        if expected.get((c, a), 0) != exported.get((c, a), 0)
    ]
    if diffs:
        raise ExportTotalsMismatch(diffs)


def render(
    lines: list[ExportLine],
    fmt: str,
    expected: dict[tuple[str, str], int],
    mapping: Mapping | None = None,
    interest: list[ExportLine] | None = None,
) -> str:
    """Totals are checked on the reconciled lines; computed interest lines are appended after."""

    _check_totals(lines, expected)
    mapping = mapping or {}
    rendered = [(line, _dec(line.amount, line.decimals)) for line in [*lines, *(interest or [])]]
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    if fmt == "journal":
        writer.writerow(JOURNAL_HEADER)
        for line, amount in rendered:
            generic_debit, generic_credit = GENERIC_MAPPING[line.classification]
            debit = mapping.get((line.classification, "DEBIT"), generic_debit)
            credit = mapping.get((line.classification, "CREDIT"), generic_credit)
            base = (
                line.day.isoformat() if line.day else "",
                line.request_id or "",
                line.classification,
            )
            tail = (line.asset, _hash(line), line.status)
            for (code, name), dr, cr in ((debit, amount, "0"), (credit, "0", amount)):
                writer.writerow([neutralize(c) for c in (*base, code, name, dr, cr, *tail)])
    else:
        writer.writerow(CSV_HEADER)
        for line, amount in rendered:
            # FEE lines already carry the fee as their amount; other lines repeat their tx's fee.
            fee = (
                ""
                if line.fee_wei is None or line.classification == "FEE"
                else _dec(line.fee_wei, ETH_DECIMALS)
            )
            cells = (
                line.day.isoformat() if line.day else "",
                line.request_id or "",
                line.vendor,
                line.invoice_no,
                line.classification,
                amount,
                line.asset,
                _hash(line),
                fee,
                line.status,
                line.matched_by,
            )
            writer.writerow([neutralize(c) for c in cells])
    return out.getvalue()


# Independent of reconciliation_lines: sums the source rows (plan steps / gas ledger) of the
# requests that have a reconciliation. The CASE mirrors worker reconcile/build.py.
_EXPECTED_SQL = text(
    """
SELECT cls, chain_id, asset_address, SUM(amt)::text AS total FROM (
    SELECT CASE o.kind WHEN 'REFILL' THEN 'INTERNAL_TRANSFER' WHEN 'SWAP' THEN 'CONVERSION'
            WHEN 'PAY' THEN 'EXTERNAL_EXPENSE' ELSE 'LENDING_TRANSFER' END AS cls,
        ps.chain_id, ps.asset_address, ps.amount AS amt
    FROM operations o
    JOIN plan_steps ps ON ps.id = o.plan_step_id
    JOIN transactions t ON t.operation_id = o.id AND t.status = 'Confirmed'
    JOIN reconciliations r ON r.request_id = o.request_id
    WHERE o.status = 'Confirmed' AND r.org_id = :org
        AND (t.confirmed_at AT TIME ZONE 'UTC')::date BETWEEN :start AND :end
    UNION ALL
    SELECT 'FEE', t.chain_id, NULL, g.fee_wei
    FROM gas_ledger g
    JOIN transactions t ON t.id = g.transaction_id
    JOIN operations o ON o.id = t.operation_id
    JOIN reconciliations r ON r.request_id = o.request_id
    WHERE r.org_id = :org AND g.day BETWEEN :start AND :end
) x GROUP BY cls, chain_id, asset_address
"""
)


_SNAPSHOT_SQL = text(
    """
SELECT block_timestamp, (data->'aave'->>'a_token_balance')::numeric AS balance FROM snapshots
WHERE treasury_id = :treasury AND coverage = 'COMPLETE' AND data->'aave'->>'a_token_balance' IS NOT NULL
    AND block_timestamp < :before
ORDER BY block_timestamp DESC LIMIT 1
"""
)
_NET_SUPPLIED_SQL = text(
    """
SELECT COALESCE(SUM(CASE o.kind::text WHEN 'SUPPLY' THEN ps.amount ELSE -ps.amount END), 0)::text
FROM operations o
JOIN plan_steps ps ON ps.id = o.plan_step_id
JOIN transactions t ON t.operation_id = o.id AND t.status = 'Confirmed'
WHERE o.status = 'Confirmed' AND o.treasury_id = :treasury
    AND o.kind::text IN ('SUPPLY', 'WITHDRAW')
    AND t.confirmed_at > :opened AND t.confirmed_at <= :closed
"""
)


async def load_interest(
    session: AsyncSession, org_id: uuid.UUID, start: date, end: date
) -> tuple[list[ExportLine], list[str]]:
    """Supply interest per treasury: aToken growth between the COMPLETE snapshots bracketing the
    period minus net supplied. Each bracketing snapshot must lie within a day before its boundary
    (the daily UTC-midnight DAILY snapshot guarantees that); otherwise no line is emitted and a
    note is returned so the export can say why."""

    opens = datetime.combine(start, time.min, UTC)
    closes = datetime.combine(end + timedelta(days=1), time.min, UTC)
    lines: list[ExportLine] = []
    notes: list[str] = []
    treasuries = await session.execute(
        select(Treasury.id, Asset.symbol, Asset.decimals)
        .join(Asset, Asset.id == Treasury.asset_id)
        .where(Treasury.org_id == org_id)
        .order_by(Treasury.id)
    )
    for treasury, symbol, decimals in treasuries.all():
        first = (
            await session.execute(_SNAPSHOT_SQL, {"treasury": treasury, "before": opens})
        ).one_or_none()
        last = (
            await session.execute(_SNAPSHOT_SQL, {"treasury": treasury, "before": closes})
        ).one_or_none()
        if first is None and last is None:
            continue  # never snapshotted with an aToken: not a lending treasury
        if (
            first is None
            or last is None
            or first.block_timestamp < opens - SNAPSHOT_TOLERANCE
            or last.block_timestamp < closes - SNAPSHOT_TOLERANCE
            or last.block_timestamp <= first.block_timestamp
        ):
            notes.append(
                f"SUPPLY_INTEREST omitted for treasury {treasury}: no snapshots near period"
            )
            logger.warning(
                "supply interest omitted for treasury %s: no snapshots near period", treasury
            )
            continue
        net = await session.scalar(
            _NET_SUPPLIED_SQL,
            {"treasury": treasury, "opened": first.block_timestamp, "closed": last.block_timestamp},
        )
        earned = int(last.balance) - int(first.balance) - int(net or 0)
        if earned <= 0:  # rounding or missing flows: never booked as income, but never silent
            notes.append(f"SUPPLY_INTEREST omitted for treasury {treasury}: computed {earned}")
            logger.warning("supply interest for treasury %s is not positive (%s)", treasury, earned)
        else:
            lines.append(
                ExportLine(
                    day=end,
                    request_id=None,
                    vendor="",
                    invoice_no="",
                    classification="SUPPLY_INTEREST",
                    amount=earned,
                    decimals=decimals,
                    asset=symbol,
                    tx_hash=b"",
                    fee_wei=None,
                    status="Computed",
                    matched_by="",
                )
            )
    return lines, notes


async def load_mapping(session: AsyncSession, org_id: uuid.UUID) -> Mapping:
    rows = await session.scalars(select(AccountMapping).where(AccountMapping.org_id == org_id))
    return {(r.classification, r.side): (r.account_code, r.account_name) for r in rows}


async def load_lines(
    session: AsyncSession, org_id: uuid.UUID, start: date, end: date
) -> tuple[list[ExportLine], dict[tuple[str, str], int]]:
    """The period's lines and the independent expected total per (class, asset symbol)."""

    rows = await session.execute(
        select(ReconciliationLine, Reconciliation, PaymentRequest, Vendor.name, Transaction.fee_wei)
        .join(Reconciliation, Reconciliation.id == ReconciliationLine.reconciliation_id)
        .join(PaymentRequest, PaymentRequest.id == Reconciliation.request_id)
        .join(Vendor, Vendor.id == PaymentRequest.vendor_id, isouter=True)
        .join(Transaction, Transaction.id == ReconciliationLine.transaction_id)
        .where(
            Reconciliation.org_id == org_id,
            ReconciliationLine.day >= start,
            ReconciliationLine.day <= end,
        )
        .order_by(ReconciliationLine.day, ReconciliationLine.block_number, ReconciliationLine.id)
    )
    assets: dict[tuple[int, bytes | None], tuple[str, int]] = {}

    async def resolve(chain_id: int, address: bytes | None) -> tuple[str, int]:
        key = (chain_id, address)
        if key not in assets:
            asset = await session.scalar(
                select(Asset).where(Asset.chain_id == chain_id, Asset.address == address)
                if address is not None
                else select(Asset).where(Asset.chain_id == chain_id, Asset.is_native.is_(True))
            )
            if asset is not None:
                assets[key] = (asset.symbol, asset.decimals)
            elif address is None:
                # shortcut: assume ETH/18 when the chain has no native assets row, seed one to drop this.
                assets[key] = ("ETH", ETH_DECIMALS)
            else:
                raise ExportAssetUnknown("unknown asset " + address.hex())
        return assets[key]

    lines: list[ExportLine] = []
    for line, rec, req, vendor, fee_wei in rows.all():
        symbol, decimals = await resolve(req.chain_id, line.asset_address)
        lines.append(
            ExportLine(
                day=line.day,
                request_id=rec.request_id,
                vendor=vendor or "",
                invoice_no=req.invoice_no or "",
                classification=line.classification,
                amount=int(line.amount),
                decimals=decimals,
                asset=symbol,
                tx_hash=line.tx_hash,
                fee_wei=None if fee_wei is None else int(fee_wei),
                status=rec.status,
                matched_by=rec.matched_by or "",
            )
        )
    expected: dict[tuple[str, str], int] = defaultdict(int)
    for row in await session.execute(_EXPECTED_SQL, {"org": org_id, "start": start, "end": end}):
        symbol, _ = await resolve(row.chain_id, row.asset_address)
        expected[(row.cls, symbol)] += int(row.total)
    return lines, dict(expected)


router = APIRouter(prefix="/v1/orgs/{organization_id}/reconciliation", tags=["reconciliation"])
_require_finance = require_role(OrganizationRole.FINANCE, OrganizationRole.ORG_ADMIN)


@router.get(
    "/export",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
    openapi_extra={"x-organization-scoped": True},
)
async def export_reconciliation(
    organization_id: uuid.UUID,
    request: Request,
    period_from: date = Query(alias="from"),  # noqa: B008
    period_to: date = Query(alias="to"),  # noqa: B008
    export_format: str = Query(default="csv", alias="format", pattern="^(csv|journal)$"),
    member: MemberAccess = Depends(_require_finance),  # noqa: B008
) -> Response:
    if period_to < period_from:
        raise AuthFailure(
            status=422,
            code="EXPORT_PERIOD_INVALID",
            title="Invalid period",
            detail="'to' must not precede 'from'.",
        )
    if (period_to - period_from).days + 1 > MAX_PERIOD_DAYS:
        raise AuthFailure(
            status=422,
            code="EXPORT_PERIOD_TOO_LONG",
            title="Period too long",
            detail=f"The period must not exceed {MAX_PERIOD_DAYS} days.",
        )
    factory: async_sessionmaker[AsyncSession] | None = getattr(
        request.app.state, "request_sessions", None
    )
    if factory is None:
        raise AuthFailure(
            status=503,
            code="REQUESTS_UNAVAILABLE",
            title="Requests unavailable",
            detail="Request storage is not configured.",
        )
    try:
        async with factory() as session:
            lines, expected = await load_lines(
                session, member.organization_id, period_from, period_to
            )
            interest, notes = await load_interest(
                session, member.organization_id, period_from, period_to
            )
            mapping = await load_mapping(session, member.organization_id)
        body = render(lines, export_format, expected, mapping, interest)
    except ExportAssetUnknown as exc:
        raise AuthFailure(
            status=409, code="EXPORT_ASSET_UNKNOWN", title="Export aborted", detail=str(exc)
        ) from exc
    except ExportTotalsMismatch as exc:
        raise AuthFailure(
            status=409,
            code="EXPORT_TOTALS_MISMATCH",
            title="Export aborted",
            detail=str(exc),
            extensions={
                "differences": [
                    {"class": c, "asset": a, "expected": str(e), "exported": str(x)}
                    for c, a, e, x in exc.diffs
                ]
            },
        ) from exc
    name = f"reconciliation-{period_from}-{period_to}-{export_format}.csv"
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            **({"X-Export-Notes": "; ".join(notes)} if notes else {}),
        },
    )


class MappingItem(BaseModel):
    classification: str = Field(pattern="^[A-Z_]{1,32}$")
    side: str = Field(pattern="^(DEBIT|CREDIT)$")
    account_code: str = Field(alias="accountCode", pattern=r"^[0-9A-Za-z._-]+$", max_length=32)
    account_name: str = Field(alias="accountName", min_length=1, max_length=100)

    model_config = {"populate_by_name": True}


class MappingBody(BaseModel):
    items: list[MappingItem] = Field(max_length=2 * len(GENERIC_MAPPING))


class MappingOut(BaseModel):
    classification: str
    side: str
    accountCode: str
    accountName: str
    source: str  # "ORG" or "DEFAULT"


class MappingsOut(BaseModel):
    items: list[MappingOut]


def _effective(overrides: Mapping) -> MappingsOut:
    items = []
    for cls, (debit, credit) in GENERIC_MAPPING.items():
        for side, default in (("DEBIT", debit), ("CREDIT", credit)):
            code, name = overrides.get((cls, side), default)
            source = "ORG" if (cls, side) in overrides else "DEFAULT"
            items.append(
                MappingOut(
                    classification=cls, side=side, accountCode=code, accountName=name, source=source
                )
            )
    return MappingsOut(items=items)


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] | None = getattr(
        request.app.state, "request_sessions", None
    )
    if factory is None:
        raise AuthFailure(
            status=503,
            code="REQUESTS_UNAVAILABLE",
            title="Requests unavailable",
            detail="Request storage is not configured.",
        )
    return factory


@router.get(
    "/account-mappings",
    response_model=MappingsOut,
    openapi_extra={"x-organization-scoped": True},
)
async def get_account_mappings(
    organization_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_require_finance),  # noqa: B008
) -> MappingsOut:
    async with _sessions(request)() as session:
        return _effective(await load_mapping(session, member.organization_id))


@router.put(
    "/account-mappings",
    response_model=MappingsOut,
    openapi_extra={"x-organization-scoped": True},
)
async def put_account_mappings(
    organization_id: uuid.UUID,
    body: MappingBody,
    request: Request,
    member: MemberAccess = Depends(_require_finance),  # noqa: B008
) -> MappingsOut:
    """Replace the org's overrides; sides not listed fall back to the generic default."""

    slots = [(i.classification, i.side) for i in body.items]
    unknown = sorted({c for c, _ in slots} - GENERIC_MAPPING.keys())
    if unknown or len(set(slots)) != len(slots):
        raise AuthFailure(
            status=422,
            code="ACCOUNT_MAPPING_INVALID",
            title="Invalid account mapping",
            detail=f"Unknown classes {unknown}." if unknown else "Duplicate class and side.",
        )
    async with _sessions(request)() as session, session.begin():
        # Serialize concurrent replaces of the same org so the unique slot never trips.
        await session.execute(
            select(Organization.id)
            .where(Organization.id == member.organization_id)
            .with_for_update()
        )
        await session.execute(
            delete(AccountMapping).where(AccountMapping.org_id == member.organization_id)
        )
        session.add_all(
            AccountMapping(
                id=uuid.uuid4(),
                org_id=member.organization_id,
                classification=i.classification,
                side=i.side,
                account_code=i.account_code,
                account_name=i.account_name,
            )
            for i in body.items
        )
        await write_audit(
            session,
            org_id=member.organization_id,
            actor=AuditActor(AuditActorType.USER, member.user_id),
            action="reconciliation.account_mappings_replaced",
            entity=AuditEntity("organization", member.organization_id),
            data={"count": len(body.items)},
        )
        await session.flush()
        return _effective(await load_mapping(session, member.organization_id))
