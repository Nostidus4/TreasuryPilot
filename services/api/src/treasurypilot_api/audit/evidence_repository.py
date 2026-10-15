"""Read-only SQL adapter for request evidence bundles.

Only records with an explicit request or append-only attestation link are exported.
Plan rows, reconciliation rows, and EAS receipt UIDs are not persisted by this API
revision; the bundle reports that coverage gap instead of manufacturing evidence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import (
    Column,
    DateTime,
    LargeBinary,
    MetaData,
    String,
    Table,
    select,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api import __version__
from treasurypilot_api.agent.models import AiCall, Extraction
from treasurypilot_api.audit.evidence import (
    EvidenceBundle,
    EvidenceBundleInvalid,
    EvidenceNotFound,
    build_evidence_bundle,
)
from treasurypilot_api.execution.models import Operation, Transaction
from treasurypilot_api.invoices.models import (
    PaymentApproval,
    PaymentRequest,
    RequestDocument,
    RequestFlag,
)
from treasurypilot_api.mandate.models import Vendor
from treasurypilot_api.treasury.config import PlatformConfigurationError, resolve_rpc_url
from treasurypilot_api.treasury.models import Asset, Chain

# These two append-only tables are written by the worker/migrations, so they do
# not have API ORM models. Lightweight Core tables let the exporter query only
# the columns it needs without making the API the owner of those schemas.
_worker_metadata = MetaData()
_attestations = Table(
    "attestations",
    _worker_metadata,
    Column("id", PGUUID(as_uuid=True)),
    Column("plan_id", PGUUID(as_uuid=True)),
    Column("request_id", LargeBinary(32)),
    Column("plan_hash", LargeBinary(32)),
    Column("step_ids", ARRAY(LargeBinary(32))),
    Column("typed_data", JSONB),
    Column("signature", LargeBinary),
    Column("policy_signer", String(42)),
    Column("created_at", DateTime(timezone=True)),
)
_validations = Table(
    "validations",
    _worker_metadata,
    Column("id", PGUUID(as_uuid=True)),
    Column("plan_id", PGUUID(as_uuid=True)),
    Column("stage", String(16)),
    Column("decision", String(16)),
    Column("reason_codes", ARRAY(String)),
    Column("checks", JSONB),
    Column("created_at", DateTime(timezone=True)),
)


@dataclass(frozen=True, slots=True)
class ReceiptResult:
    """Facts returned by an RPC receipt lookup; no endpoint data is retained."""

    resolved: bool
    chain_id: int | None = None
    transaction_hash: str | None = None
    block_number: int | None = None
    block_hash: str | None = None
    status: str | None = None


class ReceiptVerifier(Protocol):
    async def verify(
        self,
        *,
        tx_hash: str,
        chain_id: int,
        rpc_urls: Sequence[str],
        expected_block_number: int | None,
        expected_block_hash: str | None,
    ) -> ReceiptResult: ...


def _hex(data: bytes | None) -> str | None:
    return None if data is None else "0x" + data.hex()


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _hex32(value: object) -> str | None:
    if isinstance(value, bytes):
        return _hex(value) if len(value) == 32 else None
    if isinstance(value, str):
        candidate = value.lower()
        if candidate.startswith("0x") and len(candidate) == 66:
            try:
                bytes.fromhex(candidate[2:])
            except ValueError:
                return None
            return candidate
    return None


def _assert_attestation_matches_row(
    *, typed_data: object, request_id: bytes, plan_hash: bytes, step_ids: Sequence[bytes]
) -> dict[str, Any]:
    if (
        not isinstance(request_id, bytes)
        or len(request_id) != 32
        or not isinstance(plan_hash, bytes)
        or len(plan_hash) != 32
        or not isinstance(step_ids, list | tuple)
        or any(not isinstance(step_id, bytes) or len(step_id) != 32 for step_id in step_ids)
    ):
        raise EvidenceBundleInvalid("stored attestation row is invalid")
    if not isinstance(typed_data, Mapping):
        raise EvidenceBundleInvalid("stored attestation typed data is invalid")
    message = typed_data.get("message")
    if not isinstance(message, Mapping):
        raise EvidenceBundleInvalid("stored attestation message is invalid")
    stored_step_ids = message.get("stepIds")
    if not isinstance(stored_step_ids, list):
        raise EvidenceBundleInvalid("stored attestation step ids are invalid")
    if (
        _hex32(message.get("requestId")) != _hex(request_id)
        or _hex32(message.get("planHash")) != _hex(plan_hash)
        or [_hex32(item) for item in stored_step_ids] != [_hex(item) for item in step_ids]
    ):
        raise EvidenceBundleInvalid("stored attestation does not match its append-only row")
    return dict(typed_data)


class JsonRpcReceiptVerifier:
    """Resolve a persisted transaction hash against one of its configured RPCs."""

    def __init__(self, environ: Mapping[str, str] | None = None, *, timeout: float = 5.0) -> None:
        self._environ = environ if environ is not None else os.environ
        self._timeout = timeout

    async def verify(
        self,
        *,
        tx_hash: str,
        chain_id: int,
        rpc_urls: Sequence[str],
        expected_block_number: int | None,
        expected_block_hash: str | None,
    ) -> ReceiptResult:
        for template in rpc_urls:
            try:
                url = resolve_rpc_url(template, self._environ)
                parsed = urllib.parse.urlsplit(url)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    continue
                if parsed.scheme == "http" and parsed.hostname not in {
                    "localhost",
                    "127.0.0.1",
                    "::1",
                }:
                    continue
                result = await asyncio.to_thread(
                    self._verify_url,
                    url,
                    tx_hash,
                    chain_id,
                    expected_block_number,
                    expected_block_hash,
                )
                if result.resolved:
                    return result
            except (PlatformConfigurationError, TimeoutError, OSError, ValueError):
                continue
        return ReceiptResult(resolved=False)

    def _verify_url(
        self,
        url: str,
        tx_hash: str,
        expected_chain_id: int,
        expected_block_number: int | None,
        expected_block_hash: str | None,
    ) -> ReceiptResult:
        chain_id_result = self._rpc(url, 1, "eth_chainId", [])
        receipt = self._rpc(url, 2, "eth_getTransactionReceipt", [tx_hash])
        if not isinstance(chain_id_result, str) or not isinstance(receipt, Mapping):
            return ReceiptResult(resolved=False)
        try:
            chain_id = int(chain_id_result, 16)
            actual_hash = str(receipt["transactionHash"]).lower()
            block_number = int(str(receipt["blockNumber"]), 16)
            block_hash = str(receipt["blockHash"]).lower()
            status = str(receipt.get("status", "")).lower()
        except (KeyError, TypeError, ValueError):
            return ReceiptResult(resolved=False)
        matches = (
            chain_id == expected_chain_id
            and actual_hash == tx_hash.lower()
            and (expected_block_number is None or block_number == expected_block_number)
            and (expected_block_hash is None or block_hash == expected_block_hash.lower())
        )
        return ReceiptResult(
            resolved=matches,
            chain_id=chain_id,
            transaction_hash=actual_hash,
            block_number=block_number,
            block_hash=block_hash,
            status=status,
        )

    def _rpc(self, url: str, request_id: int, method: str, params: list[Any]) -> Any:
        body = json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        ).encode()
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                payload = response.read(1_000_001)
        except (urllib.error.URLError, TimeoutError, OSError):
            raise
        if len(payload) > 1_000_000:
            raise ValueError("RPC response exceeded the configured limit")
        decoded = json.loads(payload)
        if (
            not isinstance(decoded, Mapping)
            or decoded.get("jsonrpc") != "2.0"
            or decoded.get("id") != request_id
            or decoded.get("error") is not None
        ):
            raise ValueError("RPC returned an invalid response")
        return decoded.get("result")


class SqlAlchemyEvidenceRepository:
    """Build evidence from existing organization-scoped rows and live chain receipts."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        receipt_verifier: ReceiptVerifier | None = None,
        app_version: str = __version__,
    ) -> None:
        self._sessions = sessions
        self._receipt_verifier = receipt_verifier or JsonRpcReceiptVerifier()
        self._app_version = app_version

    async def export_request(
        self, *, organization_id: uuid.UUID, request_id: uuid.UUID
    ) -> EvidenceBundle:
        async with self._sessions() as session, session.begin():
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            request_row = (
                await session.execute(
                    select(
                        PaymentRequest, Vendor.name, Asset.symbol, Asset.is_test, Chain.is_testnet
                    )
                    .outerjoin(Vendor, Vendor.id == PaymentRequest.vendor_id)
                    .join(
                        Asset,
                        (Asset.id == PaymentRequest.asset_id)
                        & (Asset.chain_id == PaymentRequest.chain_id),
                    )
                    .join(Chain, Chain.chain_id == PaymentRequest.chain_id)
                    .where(
                        PaymentRequest.id == request_id,
                        PaymentRequest.org_id == organization_id,
                    )
                )
            ).one_or_none()
            if request_row is None:
                raise EvidenceNotFound
            payment, vendor_name, asset_symbol, asset_is_test, chain_is_testnet = request_row

            approvals = list(
                await session.scalars(
                    select(PaymentApproval)
                    .where(
                        PaymentApproval.request_id == request_id,
                        PaymentApproval.revision == payment.current_revision,
                        PaymentApproval.status == "Valid",
                    )
                    .order_by(PaymentApproval.created_at.desc(), PaymentApproval.id.desc())
                    .limit(1)
                )
            )
            flags = list(
                await session.scalars(
                    select(RequestFlag)
                    .where(
                        RequestFlag.request_id == request_id,
                        RequestFlag.revision == payment.current_revision,
                    )
                    .order_by(RequestFlag.created_at, RequestFlag.id)
                )
            )
            operations = list(
                await session.scalars(
                    select(Operation)
                    .where(Operation.request_id == request_id)
                    .order_by(Operation.created_at, Operation.id)
                )
            )
            operation_ids = [row.id for row in operations]
            transaction_rows = (
                list(
                    await session.scalars(
                        select(Transaction)
                        .where(Transaction.operation_id.in_(operation_ids))
                        .order_by(Transaction.submitted_at, Transaction.id)
                    )
                )
                if operation_ids
                else []
            )
            operation_by_id = {row.id: row for row in operations}

            chain_rows = {}
            transaction_chain_ids = {row.chain_id for row in transaction_rows}
            if transaction_chain_ids:
                chain_rows = {
                    row.chain_id: row
                    for row in await session.scalars(
                        select(Chain).where(Chain.chain_id.in_(transaction_chain_ids))
                    )
                }

            ai_call_rows = list(
                await session.scalars(
                    select(AiCall)
                    .join(Extraction, Extraction.ai_call_id == AiCall.id)
                    .join(RequestDocument, RequestDocument.id == Extraction.document_id)
                    .where(RequestDocument.request_id == request_id)
                    .order_by(AiCall.created_at, AiCall.id)
                )
            )
            # A call can be linked to more than one document. Include its persisted
            # identity only once; never export input refs, tool arguments, output, or errors.
            unique_ai_calls = list({row.id: row for row in ai_call_rows}.values())

            attestation_row = None
            validation_rows = []
            if payment.onchain_request_id is not None:
                attestation_row = (
                    (
                        await session.execute(
                            select(_attestations)
                            .where(_attestations.c.request_id == payment.onchain_request_id)
                            .order_by(_attestations.c.created_at.desc(), _attestations.c.id.desc())
                            .limit(1)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if attestation_row is not None:
                    validation_rows = list(
                        (
                            await session.execute(
                                select(_validations)
                                .where(_validations.c.plan_id == attestation_row["plan_id"])
                                .order_by(_validations.c.created_at, _validations.c.id)
                            )
                        ).mappings()
                    )

            source: dict[str, Any] = {
                "request": {
                    "id": payment.id,
                    "vendor_display_name": vendor_name,
                    "amount": str(int(payment.amount)) if payment.amount is not None else "",
                    "currency": asset_symbol,
                    "fingerprint": _hex(payment.fingerprint),
                    "invoice_hash": _hex(payment.invoice_hash),
                },
                "approval": None,
                "flags": [
                    {
                        "id": flag.id,
                        "code": flag.code,
                        "severity": flag.severity,
                        "status": flag.status,
                        "acknowledged_by": str(flag.acknowledged_by)
                        if flag.acknowledged_by
                        else None,
                        "acknowledged_at": flag.acknowledged_at,
                        # ack_note and arbitrary evidence JSON are omitted to avoid PII.
                    }
                    for flag in flags
                ],
                "validations": [
                    {
                        "id": row["id"],
                        "stage": row["stage"],
                        "decision": row["decision"],
                        "reason_codes": row["reason_codes"],
                        "checks": row["checks"],
                    }
                    for row in validation_rows
                ],
                "ai_calls": [
                    {
                        "id": row.id,
                        "purpose": _enum_value(row.purpose),
                        "model": row.model,
                        "prompt_version": row.prompt_version,
                    }
                    for row in unique_ai_calls
                ],
                "operations": [
                    {
                        "id": str(row.id),
                        "plan_step_id": str(row.plan_step_id),
                        "step_id": _hex(row.step_id),
                        "kind": _enum_value(row.kind),
                        "status": _enum_value(row.status),
                        "attempts": row.attempts,
                        "created_at": row.created_at,
                    }
                    for row in operations
                ],
                "transactions": [
                    {
                        "tx_hash": _hex(row.tx_hash),
                        "chain_id": row.chain_id,
                        "block_number": row.block_number,
                        "fee_base_units": str(int(row.fee_wei))
                        if row.fee_wei is not None
                        else None,
                    }
                    for row in transaction_rows
                ],
                "verifications": [],
                "coverage": {
                    "requestStatus": _enum_value(payment.status),
                    "plan": "unavailable_until_issue_65_persists_plans_and_plan_steps",
                    "validations": "linked_by_attested_plan_id"
                    if attestation_row is not None
                    else "unavailable_without_request_to_plan_link_from_issue_65",
                    "transactionEvidence": "persisted_outbox_rows_checked_against_configured_chain_rpc",
                    "independentVerifier": "no_separate_verifier_table_is_persisted",
                    "reconciliation": "not_persisted",
                    "easUid": "not_persisted",
                    "approval": "latest_valid_approval_for_current_revision_only_signature_hash_only",
                },
                "fixture_labels": [
                    label
                    for label, enabled in (
                        ("TESTNET", chain_is_testnet),
                        ("TEST_ASSET", asset_is_test),
                    )
                    if enabled
                ],
                "app_version": self._app_version,
            }

            if approvals:
                approval = approvals[0]
                source["approval"] = {
                    "typed_data": approval.typed_data,
                    "signer_address": _hex(approval.approver_address),
                    "signature_hash": hashlib.sha256(approval.signature).hexdigest(),
                }

            if attestation_row is not None:
                signature = attestation_row["signature"]
                if not isinstance(signature, bytes) or not signature:
                    raise EvidenceBundleInvalid("stored attestation signature is invalid")
                typed_data = _assert_attestation_matches_row(
                    typed_data=attestation_row["typed_data"],
                    request_id=attestation_row["request_id"],
                    plan_hash=attestation_row["plan_hash"],
                    step_ids=attestation_row["step_ids"],
                )
                source["attestation"] = {
                    "typed_data": typed_data,
                    "signer_address": attestation_row["policy_signer"],
                    "signature_hash": hashlib.sha256(signature).hexdigest(),
                }
                source["coverage"]["attestation"] = (
                    "append_only_row_matched_to_typed_data_signature_hashed_not_cryptographically_reverified"
                )
            else:
                source["coverage"]["attestation"] = "not_persisted_for_request"

        if payment.status == "Paid" and not transaction_rows:
            raise EvidenceBundleInvalid("paid request has no persisted transaction hash")
        if any(row.chain_id != payment.chain_id for row in transaction_rows):
            raise EvidenceBundleInvalid("persisted transaction chain does not match the request")
        if any(row.chain_id not in chain_rows for row in transaction_rows):
            raise EvidenceBundleInvalid("persisted transaction chain is not configured")

        receipt_results: dict[str, ReceiptResult] = {}

        async def resolve_row(row: Transaction) -> tuple[str, ReceiptResult]:
            chain = chain_rows[row.chain_id]
            tx_hash = _hex(row.tx_hash)
            assert tx_hash is not None
            return tx_hash, await self._receipt_verifier.verify(
                tx_hash=tx_hash,
                chain_id=row.chain_id,
                rpc_urls=chain.rpc_urls,
                expected_block_number=row.block_number,
                expected_block_hash=_hex(row.block_hash),
            )

        receipt_results.update(
            dict(await asyncio.gather(*(resolve_row(row) for row in transaction_rows)))
        )
        for row in transaction_rows:
            tx_hash = _hex(row.tx_hash)
            assert tx_hash is not None
            operation = operation_by_id[row.operation_id]
            checked_at = row.confirmed_at or row.last_seen_pending_at or row.submitted_at
            receipt = receipt_results[tx_hash]
            source["verifications"].append(
                {
                    "tx_hash": tx_hash,
                    "status": _enum_value(row.status),
                    "checked_at": checked_at,
                    "details": {
                        "operationStatus": _enum_value(operation.status),
                        "crosscheck": _enum_value(row.crosscheck),
                        "confirmations": row.confirmations,
                        "receiptResolved": receipt.resolved,
                        "receiptStatus": receipt.status,
                        "receiptBlockNumber": receipt.block_number,
                    },
                }
            )

        if payment.status == "Paid":
            confirmed = any(
                _enum_value(row.status) == "Confirmed"
                and row.block_number is not None
                and _enum_value(operation_by_id[row.operation_id].status) == "Confirmed"
                and _enum_value(row.crosscheck) == "Match"
                and receipt_results.get(_hex(row.tx_hash) or "", ReceiptResult(False)).resolved
                and receipt_results[_hex(row.tx_hash) or ""].status == "0x1"
                for row in transaction_rows
            )
            if not confirmed:
                raise EvidenceBundleInvalid(
                    "paid request lacks a persisted confirmed, crosschecked transaction receipt"
                )

        async def transaction_resolves(tx: Any) -> bool:
            result = receipt_results.get(tx.tx_hash)
            return result is not None and result.resolved

        try:
            return await build_evidence_bundle(
                organization_id=organization_id,
                request_id=request_id,
                source=source,
                transaction_resolves=transaction_resolves,
            )
        except EvidenceBundleInvalid:
            raise
        except (TypeError, ValueError, KeyError) as error:
            # Fail closed without reflecting underlying rows, JSON, or RPC details.
            raise EvidenceBundleInvalid("persisted request evidence is not exportable") from error
