"""Period export of reconciliation lines as CSV or journal CSV (REC-004, FR-607, FR-307)."""

from __future__ import annotations

import csv
import io
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.execution.models import Transaction
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.mandate.models import Vendor
from treasurypilot_api.reconciliation.models import Reconciliation, ReconciliationLine
from treasurypilot_api.treasury.models import Asset
from treasurypilot_core.money import BaseUnits

ETH_DECIMALS = 18

# Generic default mapping (M11-D6): class -> (debit, credit) as (code, name).
# shortcut: per-org account_mappings table and PUT endpoint not built, add with exports persistence.
GENERIC_MAPPING: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "EXTERNAL_EXPENSE": (("6000", "Expense"), ("1110", "Wallet O_i")),
    "INTERNAL_TRANSFER": (("1110", "Wallet O_i"), ("1100", "Wallet T")),
    "CONVERSION": (("1110", "Wallet O_i"), ("1100", "Wallet T")),
    "LENDING_TRANSFER": (("1300", "Lending Position"), ("1100", "Wallet T")),
    "FEE": (("6100", "Bank & Fees"), ("1200", "Executor Gas")),
}

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
    """Exported class totals differ from the on-chain amounts (M11-D7)."""


@dataclass(frozen=True)
class ExportLine:
    day: date | None
    request_id: uuid.UUID
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
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def _dec(amount: int, decimals: int) -> str:
    return BaseUnits(amount).format(decimals)


def _check_totals(lines: list[ExportLine], rendered: list[tuple[ExportLine, str]]) -> None:
    onchain: dict[tuple[str, str], int] = defaultdict(int)
    exported: dict[tuple[str, str], int] = defaultdict(int)
    for line, text in rendered:
        key = (line.classification, line.asset)
        onchain[key] += line.amount
        exported[key] += int(Decimal(text).scaleb(line.decimals))
    if onchain != exported or len(rendered) != len(lines):
        raise ExportTotalsMismatch("export totals differ from on-chain totals")


def render(lines: list[ExportLine], fmt: str) -> str:
    rendered = [(line, _dec(line.amount, line.decimals)) for line in lines]
    _check_totals(lines, rendered)
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    if fmt == "journal":
        writer.writerow(JOURNAL_HEADER)
        for line, amount in rendered:
            debit, credit = GENERIC_MAPPING[line.classification]
            base = (
                line.day.isoformat() if line.day else "",
                line.request_id,
                line.classification,
            )
            tail = (line.asset, "0x" + line.tx_hash.hex(), line.status)
            for (code, name), dr, cr in ((debit, amount, "0"), (credit, "0", amount)):
                writer.writerow([neutralize(c) for c in (*base, code, name, dr, cr, *tail)])
    else:
        writer.writerow(CSV_HEADER)
        for line, amount in rendered:
            fee = "" if line.fee_wei is None else _dec(line.fee_wei, ETH_DECIMALS)
            cells = (
                line.day.isoformat() if line.day else "",
                line.request_id,
                line.vendor,
                line.invoice_no,
                line.classification,
                amount,
                line.asset,
                "0x" + line.tx_hash.hex(),
                fee,
                line.status,
                line.matched_by,
            )
            writer.writerow([neutralize(c) for c in cells])
    return out.getvalue()


async def load_lines(
    session: AsyncSession, org_id: uuid.UUID, start: date, end: date
) -> list[ExportLine]:
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
    lines: list[ExportLine] = []
    for line, rec, req, vendor, fee_wei in rows.all():
        key = (req.chain_id, line.asset_address)
        if key not in assets:
            # Native (NULL address) is ETH; unknown ERC-20 aborts rather than guessing decimals.
            asset = await session.scalar(
                select(Asset).where(Asset.chain_id == key[0], Asset.address == key[1])
                if key[1] is not None
                else select(Asset).where(Asset.chain_id == key[0], Asset.is_native.is_(True))
            )
            if asset is not None:
                assets[key] = (asset.symbol, asset.decimals)
            elif key[1] is None:
                assets[key] = ("ETH", ETH_DECIMALS)
            else:
                raise ExportTotalsMismatch("unknown asset for " + key[1].hex())
        symbol, decimals = assets[key]
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
    return lines


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
    async with factory() as session:
        lines = await load_lines(session, member.organization_id, period_from, period_to)
    try:
        body = render(lines, export_format)
    except ExportTotalsMismatch as exc:
        raise AuthFailure(
            status=409, code="EXPORT_TOTALS_MISMATCH", title="Export aborted", detail=str(exc)
        ) from exc
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="reconciliation-{export_format}.csv"'
        },
    )
