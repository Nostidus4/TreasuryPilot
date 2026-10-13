"""Persistence and chain reads for in-app Safe governance signatures (MDT-009)."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Mapping
from typing import Any

from eth_hash.auto import keccak
from eth_utils import to_checksum_address
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.models import WalletLink
from treasurypilot_api.mandate.governance import (
    GovernanceCall,
    SafeTransaction,
    build_safe_transaction,
    exec_transaction_data,
    pack_signatures,
    recover_owner,
)
from treasurypilot_api.mandate.models import (
    GovernanceSignature,
    GovernanceTx,
    GovernanceTxPurpose,
    GovernanceTxStatus,
)
from treasurypilot_api.treasury.config import (
    PlatformConfiguration,
    PlatformConfigurationError,
    resolve_rpc_url,
)
from treasurypilot_api.treasury.models import Treasury, TreasuryWallet, WalletRole
from treasurypilot_api.treasury.safe import (
    RpcSafeVerifier,
    RpcUnavailable,
    SafeVerificationError,
    _rpc,
)

_NONCE_SELECTOR = "0xaffed0e0"  # nonce()
_EXECUTION_EVENTS = {
    "0x" + keccak(b"ExecutionSuccess(bytes32,uint256)").hex(): GovernanceTxStatus.EXECUTED,
    "0x" + keccak(b"ExecutionFailure(bytes32,uint256)").hex(): GovernanceTxStatus.FAILED,
}


class GovernanceFailure(Exception):
    def __init__(self, code: str, status: int, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.status = status
        self.detail = detail


def _address(raw: bytes) -> str:
    return to_checksum_address("0x" + raw.hex())


def _hex(raw: bytes) -> str:
    return "0x" + raw.hex()


class GovernanceService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        verifier: RpcSafeVerifier,
        configuration: PlatformConfiguration,
        *,
        environ: Mapping[str, str] = os.environ,
    ) -> None:
        self._sessions = sessions
        self._verifier = verifier
        self._configuration = configuration
        self._environ = environ

    async def _source(
        self, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> tuple[Treasury, TreasuryWallet]:
        async with self._sessions() as session:
            row = await session.execute(
                select(Treasury, TreasuryWallet)
                .join(TreasuryWallet, TreasuryWallet.treasury_id == Treasury.id)
                .where(
                    Treasury.id == treasury_id,
                    Treasury.org_id == organization_id,
                    TreasuryWallet.org_id == organization_id,
                    TreasuryWallet.role == WalletRole.SOURCE,
                )
            )
            item = row.one_or_none()
        if item is None:
            raise GovernanceFailure("TREASURY_NOT_FOUND", 404, "Treasury not found.")
        return item

    async def _nonce(self, chain_id: int, safe: bytes) -> int:
        chain = next(
            (
                item
                for item in self._configuration.chains
                if item.chain_id == chain_id and item.enabled
            ),
            None,
        )
        if chain is None:
            raise GovernanceFailure("WRONG_CHAIN", 422, "The treasury chain is not enabled.")
        for template in chain.rpc_urls:
            if not template.startswith(("http://", "https://")):
                continue
            try:
                url = resolve_rpc_url(template, self._environ)
                result = await asyncio.to_thread(
                    _rpc,
                    url,
                    "eth_call",
                    [{"to": _address(safe), "data": _NONCE_SELECTOR}, "latest"],
                )
                return int(str(result), 16)
            except (OSError, ValueError, PlatformConfigurationError):
                continue
            except Exception:
                continue
        raise RpcUnavailable(f"no RPC provider answered for chain {chain_id}")

    async def _receipt_status(
        self, chain_id: int, transaction_hash: bytes, safe: bytes, safe_tx_hash: bytes
    ) -> GovernanceTxStatus | None:
        chain = next(
            (
                item
                for item in self._configuration.chains
                if item.chain_id == chain_id and item.enabled
            ),
            None,
        )
        if chain is None:
            return None
        for template in chain.rpc_urls:
            if not template.startswith(("http://", "https://")):
                continue
            try:
                url = resolve_rpc_url(template, self._environ)
                receipt = await asyncio.to_thread(
                    _rpc, url, "eth_getTransactionReceipt", [_hex(transaction_hash)]
                )
            except Exception:
                continue
            if receipt is None:
                return None
            if str(receipt.get("status", "0x1")).lower() == "0x0":
                return GovernanceTxStatus.FAILED
            for log in receipt.get("logs", []):
                topics = log.get("topics", [])
                event = str(topics[0]).lower() if topics else ""
                if (
                    str(log.get("address", "")).lower() == _address(safe).lower()
                    and len(topics) >= 2
                    and str(topics[1]).lower() == _hex(safe_tx_hash).lower()
                    and event in _EXECUTION_EVENTS
                ):
                    return _EXECUTION_EVENTS[event]
            return None
        raise RpcUnavailable(f"no RPC provider answered for chain {chain_id}")

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        user_id: uuid.UUID,
        purpose: GovernanceTxPurpose,
        calls: list[GovernanceCall],
    ) -> dict[str, Any]:
        treasury, wallet = await self._source(organization_id, treasury_id)
        safe = "0x" + wallet.safe_address.hex()
        try:
            info = (await self._verifier.verify(treasury.chain_id, [safe]))[0]
        except RpcUnavailable:
            raise
        except SafeVerificationError as exc:
            raise GovernanceFailure(
                exc.code, 422, "The source Safe could not be verified."
            ) from None
        multisend = None
        if len(calls) > 1:
            manifest = next(
                (
                    item
                    for item in self._configuration.manifests
                    if item.chain_id == treasury.chain_id
                ),
                None,
            )
            deployment = (
                next(
                    (
                        item
                        for item in manifest.deployments
                        if item.name == "SAFE_MULTISEND_CALL_ONLY" and item.version == "1.4.1"
                    ),
                    None,
                )
                if manifest is not None
                else None
            )
            if deployment is None:
                raise GovernanceFailure(
                    "MULTISEND_UNAVAILABLE",
                    503,
                    "MultiSendCallOnly v1.4.1 is not configured for this chain.",
                )
            multisend = deployment.address_bytes
        try:
            tx = build_safe_transaction(calls, multisend_call_only=multisend)
        except ValueError as exc:
            raise GovernanceFailure("CALL_INVALID", 422, str(exc)) from None
        chain_nonce = await self._nonce(treasury.chain_id, wallet.safe_address)
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"governance:{treasury.chain_id}:{wallet.safe_address.hex()}"},
            )
            await session.execute(
                text(
                    "UPDATE governance_txs SET status='Superseded', version=version+1, updated_at=now() "
                    "WHERE chain_id=:chain AND safe_address=:safe AND status IN "
                    "('Collecting'::governance_tx_status,'Ready'::governance_tx_status) "
                    "AND safe_nonce < :nonce"
                ),
                {"chain": treasury.chain_id, "safe": wallet.safe_address, "nonce": chain_nonce},
            )
            highest = await session.scalar(
                select(GovernanceTx.safe_nonce)
                .where(
                    GovernanceTx.chain_id == treasury.chain_id,
                    GovernanceTx.safe_address == wallet.safe_address,
                    GovernanceTx.status.in_(
                        [
                            GovernanceTxStatus.COLLECTING,
                            GovernanceTxStatus.READY,
                            GovernanceTxStatus.SUBMITTED,
                        ]
                    ),
                )
                .order_by(GovernanceTx.safe_nonce.desc())
                .limit(1)
            )
            nonce = max(chain_nonce, int(highest) + 1 if highest is not None else chain_nonce)
            typed = tx.typed_data(
                chain_id=treasury.chain_id, safe_address=wallet.safe_address, nonce=nonce
            )
            from treasurypilot_api.mandate.governance import safe_tx_hash

            row = GovernanceTx(
                id=uuid.uuid4(),
                org_id=organization_id,
                treasury_id=treasury_id,
                chain_id=treasury.chain_id,
                safe_address=wallet.safe_address,
                purpose=purpose,
                calls=[item.as_json() for item in calls],
                to=tx.to,
                value=tx.value,
                data=tx.data,
                operation=tx.operation,
                safe_nonce=nonce,
                safe_tx_hash=safe_tx_hash(typed),
                threshold=info.threshold,
                owners_snapshot=[bytes.fromhex(owner[2:]) for owner in info.owners],
                status=GovernanceTxStatus.COLLECTING,
                created_by=user_id,
                updated_by=user_id,
            )
            session.add(row)
            try:
                await session.flush()
            except IntegrityError:
                raise GovernanceFailure(
                    "NONCE_CONFLICT", 409, "A governance transaction already uses this Safe nonce."
                ) from None
        return await self.get(
            organization_id=organization_id,
            governance_tx_id=row.id,
            refresh_chain=False,
        )

    async def _row(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        tx_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> GovernanceTx:
        statement = select(GovernanceTx).where(
            GovernanceTx.org_id == organization_id, GovernanceTx.id == tx_id
        )
        if lock:
            statement = statement.with_for_update()
        row = await session.scalar(statement)
        if row is None:
            raise GovernanceFailure(
                "GOVERNANCE_TX_NOT_FOUND", 404, "Governance transaction not found."
            )
        return row

    @staticmethod
    def _safe_tx(row: GovernanceTx) -> SafeTransaction:
        calls = tuple(
            GovernanceCall(
                bytes.fromhex(item["to"].removeprefix("0x")),
                int(item["value"]),
                bytes.fromhex(item["data"].removeprefix("0x")),
                int(item["operation"]),
            )
            for item in row.calls
        )
        return SafeTransaction(row.to, int(row.value), row.data, row.operation, calls)

    @classmethod
    def _typed(cls, row: GovernanceTx) -> dict[str, Any]:
        return cls._safe_tx(row).typed_data(
            chain_id=row.chain_id, safe_address=row.safe_address, nonce=row.safe_nonce
        )

    async def get(
        self,
        *,
        organization_id: uuid.UUID,
        governance_tx_id: uuid.UUID,
        refresh_chain: bool = True,
    ) -> dict[str, Any]:
        if refresh_chain:
            await self.refresh(organization_id=organization_id, governance_tx_id=governance_tx_id)
        async with self._sessions() as session:
            row = await self._row(session, organization_id, governance_tx_id)
            signatures = list(
                await session.scalars(
                    select(GovernanceSignature)
                    .where(
                        GovernanceSignature.org_id == organization_id,
                        GovernanceSignature.governance_tx_id == governance_tx_id,
                    )
                    .order_by(GovernanceSignature.owner_address)
                )
            )
            result = {
                "id": row.id,
                "treasuryId": row.treasury_id,
                "purpose": row.purpose.value,
                "safeAddress": _address(row.safe_address),
                "to": _address(row.to),
                "value": str(row.value),
                "data": _hex(row.data),
                "operation": row.operation,
                "nonce": row.safe_nonce,
                "safeTxHash": _hex(row.safe_tx_hash),
                "decodedCalls": row.calls,
                "humanSummary": self._summary(row),
                "typedData": self._typed(row),
                "threshold": row.threshold,
                "owners": [_address(address) for address in row.owners_snapshot],
                "status": row.status.value,
                "execTxHash": _hex(row.exec_tx_hash) if row.exec_tx_hash else None,
                "signatures": [
                    {
                        "owner": _address(item.owner_address),
                        "signature": _hex(item.signature),
                        "at": item.at,
                    }
                    for item in signatures
                ],
            }
        return result

    @staticmethod
    def _summary(row: GovernanceTx) -> str:
        label = row.purpose.value.replace("_", " ").title()
        descriptions = []
        for index, call in enumerate(row.calls, start=1):
            data = str(call["data"]).removeprefix("0x")
            selector = "0x" + data[:8] if len(data) >= 8 else "0x"
            descriptions.append(
                f"call {index}: {call['to']}, value {call['value']} base units, selector {selector}"
            )
        return f"{label}: " + "; ".join(descriptions)

    async def refresh(self, *, organization_id: uuid.UUID, governance_tx_id: uuid.UUID) -> None:
        async with self._sessions() as session:
            row = await self._row(session, organization_id, governance_tx_id)
            chain_id, safe = row.chain_id, row.safe_address
            nonce, status = row.safe_nonce, row.status
            submitted_hash, signed_hash = row.exec_tx_hash, row.safe_tx_hash
        next_status: GovernanceTxStatus | None = None
        if status == GovernanceTxStatus.SUBMITTED and submitted_hash is not None:
            next_status = await self._receipt_status(chain_id, submitted_hash, safe, signed_hash)
            if next_status is None and await self._nonce(chain_id, safe) > nonce:
                next_status = GovernanceTxStatus.SUPERSEDED
        elif status in (GovernanceTxStatus.COLLECTING, GovernanceTxStatus.READY):
            if await self._nonce(chain_id, safe) > nonce:
                next_status = GovernanceTxStatus.SUPERSEDED
        if next_status is not None:
            async with self._sessions() as session, session.begin():
                row = await self._row(session, organization_id, governance_tx_id)
                if row.status in (
                    GovernanceTxStatus.COLLECTING,
                    GovernanceTxStatus.READY,
                    GovernanceTxStatus.SUBMITTED,
                ):
                    row.status = next_status

    async def sign(
        self,
        *,
        organization_id: uuid.UUID,
        governance_tx_id: uuid.UUID,
        user_id: uuid.UUID,
        signature: bytes,
    ) -> dict[str, Any]:
        await self.refresh(organization_id=organization_id, governance_tx_id=governance_tx_id)
        async with self._sessions() as session, session.begin():
            row = await self._row(session, organization_id, governance_tx_id, lock=True)
            if row.status not in (GovernanceTxStatus.COLLECTING, GovernanceTxStatus.READY):
                raise GovernanceFailure(
                    "SUPERSEDED",
                    409,
                    "This governance transaction is no longer open for signatures.",
                )
            try:
                signer = recover_owner(self._typed(row), signature)
            except ValueError:
                raise GovernanceFailure(
                    "SIGNATURE_INVALID", 400, "The SafeTx signature is invalid."
                ) from None
            if signer not in row.owners_snapshot:
                raise GovernanceFailure(
                    "NOT_SAFE_OWNER", 403, "The signing wallet is not an owner of this Safe."
                )
            linked = set(
                await session.scalars(
                    select(WalletLink.address).where(
                        WalletLink.user_id == user_id, WalletLink.unlinked_at.is_(None)
                    )
                )
            )
            if signer not in linked:
                raise GovernanceFailure(
                    "NOT_SAFE_OWNER",
                    403,
                    "Link the Safe owner wallet to your account before signing.",
                )
            existing = await session.scalar(
                select(GovernanceSignature.id).where(
                    GovernanceSignature.governance_tx_id == row.id,
                    GovernanceSignature.owner_address == signer,
                )
            )
            if existing is not None:
                raise GovernanceFailure("ALREADY_SIGNED", 409, "This owner has already signed.")
            session.add(
                GovernanceSignature(
                    org_id=organization_id,
                    governance_tx_id=row.id,
                    owner_address=signer,
                    signature=signature,
                    signed_by_user=user_id,
                )
            )
            count = (
                int(
                    await session.scalar(
                        select(func.count())
                        .select_from(GovernanceSignature)
                        .where(GovernanceSignature.governance_tx_id == row.id)
                    )
                    or 0
                )
                + 1
            )
            if count >= row.threshold:
                row.status = GovernanceTxStatus.READY
            row.updated_by = user_id
            await session.flush()
        return await self.get(
            organization_id=organization_id,
            governance_tx_id=governance_tx_id,
            refresh_chain=False,
        )

    async def submitted(
        self,
        *,
        organization_id: uuid.UUID,
        governance_tx_id: uuid.UUID,
        user_id: uuid.UUID,
        transaction_hash: bytes,
    ) -> dict[str, Any]:
        if len(transaction_hash) != 32:
            raise GovernanceFailure("TX_HASH_INVALID", 422, "Transaction hash must be 32 bytes.")
        async with self._sessions() as session, session.begin():
            row = await self._row(session, organization_id, governance_tx_id)
            if row.status != GovernanceTxStatus.READY:
                raise GovernanceFailure(
                    "NOT_READY", 409, "Only a ready transaction can be submitted."
                )
            linked = set(
                await session.scalars(
                    select(WalletLink.address).where(
                        WalletLink.user_id == user_id, WalletLink.unlinked_at.is_(None)
                    )
                )
            )
            if not linked.intersection(row.owners_snapshot):
                raise GovernanceFailure(
                    "NOT_SAFE_OWNER",
                    403,
                    "Link a Safe owner wallet to your account before submitting.",
                )
            row.exec_tx_hash = transaction_hash
            row.status = GovernanceTxStatus.SUBMITTED
            row.updated_by = user_id
        return await self.get(
            organization_id=organization_id,
            governance_tx_id=governance_tx_id,
            refresh_chain=False,
        )

    async def exec_call(
        self, *, organization_id: uuid.UUID, governance_tx_id: uuid.UUID
    ) -> dict[str, str]:
        await self.refresh(organization_id=organization_id, governance_tx_id=governance_tx_id)
        async with self._sessions() as session:
            row = await self._row(session, organization_id, governance_tx_id)
            if row.status != GovernanceTxStatus.READY:
                raise GovernanceFailure(
                    "NOT_READY", 409, "The Safe owner threshold has not been reached."
                )
            signatures = list(
                await session.execute(
                    select(GovernanceSignature.owner_address, GovernanceSignature.signature).where(
                        GovernanceSignature.governance_tx_id == row.id
                    )
                )
            )
            packed = pack_signatures(
                self._typed(row), signatures, row.owners_snapshot, row.threshold
            )
            return {
                "to": _address(row.safe_address),
                "data": _hex(
                    exec_transaction_data(
                        self._safe_tx(row), nonce=row.safe_nonce, packed_signatures=packed
                    )
                ),
            }
