"""Idempotent recurring-draft generation using the worker's database boundary."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import asyncpg  # type: ignore[import-untyped]
from eth_abi import encode
from eth_hash.auto import keccak

from treasurypilot_core.fingerprint import fingerprint, normalize
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.recurrence import RecurrenceCadence, period_at, period_invoice_number

logger = logging.getLogger(__name__)

_DUE_SCHEDULES = """
SELECT s.*
FROM recurring_payment_schedules AS s
WHERE s.status = 'Active' AND s.next_period <= $1
ORDER BY s.next_period, s.id
LIMIT $2
FOR UPDATE SKIP LOCKED
"""


async def _insert_period(
    connection: asyncpg.Connection, schedule: asyncpg.Record, today: date
) -> bool:
    period_date = schedule["next_period"]
    if schedule["end_date"] is not None and period_date > schedule["end_date"]:
        await connection.execute(
            "UPDATE recurring_payment_schedules SET status='Completed', version=version+1, updated_at=now() WHERE id=$1",
            schedule["id"],
        )
        return False

    exists = await connection.fetchval(
        "SELECT id FROM recurring_payment_periods WHERE schedule_id=$1 AND period_date=$2",
        schedule["id"],
        period_date,
    )
    if exists is not None:
        return False

    details = await connection.fetchrow(
        """SELECT v.normalized_ref, a.address AS asset_address, a.decimals,
                  t.asset_id AS treasury_asset_id, p.status AS payee_status
           FROM treasuries AS t
           JOIN vendors AS v ON v.id=$2 AND v.org_id=$3
           JOIN assets AS a ON a.id=$4 AND a.chain_id=t.chain_id
           JOIN payees AS p ON p.id=$5 AND p.treasury_id=$1 AND p.vendor_id=$2
           WHERE t.id=$1 AND t.org_id=$3""",
        schedule["treasury_id"],
        schedule["vendor_id"],
        schedule["org_id"],
        schedule["asset_id"],
        schedule["payee_id"],
    )
    if details is None or details["treasury_asset_id"] != schedule["asset_id"]:
        raise ValueError(
            "recurring template no longer matches its treasury, vendor, payee, or asset"
        )
    if details["payee_status"] == "Deactivated":
        raise ValueError("recurring template payee is deactivated")
    if details["asset_address"] is None or len(details["asset_address"]) != 20:
        raise ValueError("recurring payment asset must be an ERC-20 address")

    invoice_no = period_invoice_number(schedule["invoice_no_template"], period_date)
    due_date = period_date + timedelta(days=schedule["due_days_after_issue"])
    amount = int(schedule["amount"])
    value = fingerprint(
        details["normalized_ref"],
        invoice_no,
        BaseUnits(amount),
        "0x" + details["asset_address"].hex(),
    )
    duplicate_id = await connection.fetchval(
        """SELECT id FROM payment_requests
           WHERE treasury_id=$1 AND fingerprint=$2
             AND status NOT IN ('Rejected', 'Cancelled', 'Expired')
           ORDER BY id LIMIT 1""",
        schedule["treasury_id"],
        value,
    )
    if duplicate_id is not None:
        raise ValueError(f"generated invoice duplicates active request {duplicate_id}")

    request_id = uuid.uuid4()
    last_editor_id = schedule["last_edited_by"] or schedule["created_by"]
    invoice_hash = keccak(
        encode(
            ["string", "string", "uint256", "address", "string", "string", "bytes32"],
            [
                normalize(details["normalized_ref"]),
                normalize(invoice_no),
                amount,
                details["asset_address"],
                period_date.isoformat(),
                due_date.isoformat(),
                bytes(32),
            ],
        )
    )
    onchain_id = keccak(
        encode(
            ["string", "bytes16", "bytes16"],
            ["TP_REQ_V1", schedule["org_id"].bytes, request_id.bytes],
        )
    )
    terms = schedule["terms"]
    if isinstance(terms, str):
        terms = json.loads(terms)
    terms_hash = (
        keccak(json.dumps(terms, sort_keys=True, separators=(",", ":")).encode())
        if terms is not None
        else None
    )
    await connection.execute(
        """INSERT INTO payment_requests
           (id, org_id, treasury_id, chain_id, vendor_id, payee_id, invoice_no,
            issue_date, due_at, amount, asset_id, paying_wallet_id, terms, terms_hash,
            fingerprint, invoice_hash, onchain_request_id, source, status, current_revision,
            created_by, last_edited_by, note, tags, cost_center)
           SELECT $1, $2, $3, t.chain_id, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb,
                  $13, $14, $15, $16, 'RECURRING', 'Draft', 1, $17, $18, $19, $20, $21
           FROM treasuries AS t WHERE t.id=$3 AND t.org_id=$2""",
        request_id,
        schedule["org_id"],
        schedule["treasury_id"],
        schedule["vendor_id"],
        schedule["payee_id"],
        invoice_no,
        period_date,
        due_date,
        amount,
        schedule["asset_id"],
        schedule["paying_wallet_id"],
        json.dumps(terms, separators=(",", ":")) if terms is not None else None,
        terms_hash,
        value,
        invoice_hash,
        onchain_id,
        schedule["created_by"],
        last_editor_id,
        schedule["note"],
        schedule["tags"],
        schedule["cost_center"],
    )
    snapshot = {
        "treasuryId": str(schedule["treasury_id"]),
        "vendorId": str(schedule["vendor_id"]),
        "payeeId": str(schedule["payee_id"]),
        "invoiceNo": invoice_no,
        "issueDate": period_date.isoformat(),
        "dueDate": due_date.isoformat(),
        "amount": str(amount),
        "assetId": str(schedule["asset_id"]),
        "payingWalletId": str(schedule["paying_wallet_id"])
        if schedule["paying_wallet_id"]
        else None,
        "terms": terms,
    }
    await connection.execute(
        "INSERT INTO request_revisions (id, request_id, revision, snapshot, edited_by) VALUES ($1,$2,1,$3::jsonb,$4)",
        uuid.uuid4(),
        request_id,
        json.dumps(snapshot, separators=(",", ":")),
        last_editor_id,
    )
    await connection.execute(
        """INSERT INTO request_status_events (id, request_id, "from", "to", actor_type, actor_id, reason)
           VALUES ($1,$2,NULL,'Draft','SYSTEM',NULL,$3)""",
        uuid.uuid4(),
        request_id,
        f"recurring schedule {schedule['id']} period {period_date.isoformat()} generated",
    )
    flags: list[tuple[str, dict[str, Any]]] = []
    if due_date < today:
        flags.append(("DUE_DATE_PAST", {"dueDate": due_date.isoformat()}))
    if due_date > period_date + timedelta(days=120):
        flags.append(("DUE_DATE_FAR", {"dueDate": due_date.isoformat(), "thresholdDays": 120}))
    paid_to_payee = await connection.fetchval(
        "SELECT id FROM payment_requests WHERE payee_id=$1 AND status='Paid' LIMIT 1",
        schedule["payee_id"],
    )
    if paid_to_payee is None:
        flags.append(("FIRST_PAYMENT_TO_PAYEE", {"payeeId": str(schedule["payee_id"])}))
    paid_count = await connection.fetchval(
        "SELECT count(*) FROM payment_requests WHERE vendor_id=$1 AND status='Paid'",
        schedule["vendor_id"],
    )
    if paid_count < 5:
        flags.append(("NO_BASELINE", {"minimumHistory": 5}))
    for code, evidence in flags:
        await connection.execute(
            """INSERT INTO flags (id, request_id, revision, code, severity, evidence, source)
               VALUES ($1,$2,1,$3,'LOW',$4::jsonb,'DETERMINISTIC')""",
            uuid.uuid4(),
            request_id,
            code,
            json.dumps(evidence, separators=(",", ":")),
        )
    next_index = schedule["period_index"] + 1
    next_date = period_at(
        schedule["start_date"],
        RecurrenceCadence(schedule["cadence"]),
        schedule["interval"],
        next_index,
    )
    status = (
        "Completed"
        if schedule["end_date"] is not None and next_date > schedule["end_date"]
        else "Active"
    )
    await connection.execute(
        """INSERT INTO recurring_payment_periods (id, schedule_id, period_date, request_id, status)
           VALUES ($1,$2,$3,$4,'Generated')""",
        uuid.uuid4(),
        schedule["id"],
        period_date,
        request_id,
    )
    await connection.execute(
        """UPDATE recurring_payment_schedules
           SET period_index=$2, next_period=$3, status=$4, version=version+1, updated_at=now()
           WHERE id=$1""",
        schedule["id"],
        next_index,
        next_date,
        status,
    )
    return True


async def generate_due_recurring_drafts(
    connection: asyncpg.Connection, *, today: date | None = None, batch_size: int = 100
) -> dict[str, int]:
    """Create due drafts in locked PostgreSQL transactions; redeliveries are idempotent."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    run_date = today or datetime.now(UTC).date()
    generated = 0
    errors = 0
    async with connection.transaction():
        schedules = await connection.fetch(_DUE_SCHEDULES, run_date, batch_size)
        for claimed in schedules:
            schedule_id = claimed["id"]
            for _ in range(100):  # bound catch-up work for templates with a long outage
                schedule = await connection.fetchrow(
                    "SELECT * FROM recurring_payment_schedules WHERE id=$1", schedule_id
                )
                if (
                    schedule is None
                    or schedule["status"] != "Active"
                    or schedule["next_period"] > run_date
                ):
                    break
                try:
                    async with connection.transaction():
                        made_draft = await _insert_period(connection, schedule, run_date)
                    if made_draft:
                        generated += 1
                except (ValueError, asyncpg.PostgresError) as error:
                    errors += 1
                    if isinstance(error, ValueError | asyncpg.UniqueViolationError):
                        await connection.execute(
                            "UPDATE recurring_payment_schedules SET status='Paused', version=version+1, updated_at=now() WHERE id=$1 AND status='Active'",
                            schedule_id,
                        )
                    logger.warning(
                        "recurring_period_not_generated",
                        extra={
                            "schedule_id": str(schedule_id),
                            "period": schedule["next_period"].isoformat(),
                            "error": str(error),
                        },
                    )
                    break
    return {"generated": generated, "errors": errors}
