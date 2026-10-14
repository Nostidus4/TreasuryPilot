"""Persistence and chain reads for in-app Safe governance signatures (MDT-009)."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Mapping
from typing import Any

from eth_abi import encode
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
    enable_module_data,
    exec_transaction_data,
    module_factory_create_data,
    module_factory_predict_data,
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
from treasurypilot_api.treasury.models import (
    Asset,
    Treasury,
    TreasuryStatus,
    TreasuryWallet,
    WalletRole,
)
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

    async def _treasury_setup(
        self, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> tuple[Treasury, Asset, list[TreasuryWallet]]:
        async with self._sessions() as session:
            treasury = await session.scalar(
                select(Treasury).where(
                    Treasury.id == treasury_id, Treasury.org_id == organization_id
                )
            )
            if treasury is None:
                raise GovernanceFailure("TREASURY_NOT_FOUND", 404, "Treasury not found.")
            asset = await session.scalar(select(Asset).where(Asset.id == treasury.asset_id))
            wallets = list(
                await session.scalars(
                    select(TreasuryWallet)
                    .where(
                        TreasuryWallet.treasury_id == treasury_id,
                        TreasuryWallet.org_id == organization_id,
                    )
                    .order_by(TreasuryWallet.role, TreasuryWallet.label)
                )
            )
        if asset is None:
            raise GovernanceFailure("ASSET_NOT_FOUND", 409, "Treasury asset is unavailable.")
        if not any(wallet.role == WalletRole.SOURCE for wallet in wallets):
            raise GovernanceFailure("SAFE_NOT_FOUND", 409, "Treasury source Safe is unavailable.")
        return treasury, asset, wallets

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

    async def predict_module_address(
        self, *, chain_id: int, safe: bytes, factory: bytes, salt: bytes
    ) -> bytes:
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
        data = module_factory_predict_data(safe_t=safe, salt=salt)
        for template in chain.rpc_urls:
            if not template.startswith(("http://", "https://")):
                continue
            try:
                result = await asyncio.to_thread(
                    _rpc,
                    resolve_rpc_url(template, self._environ),
                    "eth_call",
                    [{"to": _address(factory), "data": _hex(data)}, "latest"],
                )
                predicted = bytes.fromhex(str(result).removeprefix("0x"))
                if len(predicted) != 32 or not any(predicted[-20:]):
                    continue
                return predicted[-20:]
            except Exception:
                continue
        raise RpcUnavailable(f"no RPC provider answered for chain {chain_id}")

    async def _verified_deployment(self, chain_id: int, name: str, version: str) -> Any:
        manifest = next(
            (item for item in self._configuration.manifests if item.chain_id == chain_id), None
        )
        deployment = next(
            (
                item
                for item in (manifest.deployments if manifest else ())
                if item.name == name and item.version == version
            ),
            None,
        )
        if deployment is None:
            raise GovernanceFailure(
                "MODULE_DEPLOYMENT_UNAVAILABLE",
                503,
                f"The verified {name} deployment is not configured for this chain.",
            )
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
                code = await asyncio.to_thread(
                    _rpc,
                    resolve_rpc_url(template, self._environ),
                    "eth_getCode",
                    [_address(deployment.address_bytes), "latest"],
                )
                raw = bytes.fromhex(str(code).removeprefix("0x"))
                if raw and keccak(raw) == deployment.code_hash_bytes:
                    return deployment
            except Exception:
                continue
        raise RpcUnavailable(f"configured {name} code could not be verified on chain {chain_id}")

    async def create_module_setup(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        user_id: uuid.UUID,
        setup: Mapping[str, Any],
    ) -> dict[str, Any]:
        treasury, asset, wallets = await self._treasury_setup(organization_id, treasury_id)
        if treasury.module_address is not None or treasury.status.value not in (
            "Draft",
            "ModulePending",
        ):
            raise GovernanceFailure(
                "MODULE_ALREADY_CONFIGURED",
                409,
                "This treasury already has a module setup in progress.",
            )
        async with self._sessions() as session:
            existing = await session.scalar(
                select(GovernanceTx.id)
                .where(
                    GovernanceTx.org_id == organization_id,
                    GovernanceTx.treasury_id == treasury_id,
                    GovernanceTx.purpose == GovernanceTxPurpose.MODULE_SETUP,
                    GovernanceTx.status.in_(
                        [
                            GovernanceTxStatus.COLLECTING,
                            GovernanceTxStatus.READY,
                            GovernanceTxStatus.SUBMITTED,
                        ]
                    ),
                )
                .limit(1)
            )
        if existing is not None:
            raise GovernanceFailure(
                "MODULE_SETUP_IN_PROGRESS", 409, "A module setup transaction is already open."
            )
        source = next(wallet for wallet in wallets if wallet.role == WalletRole.SOURCE)
        operational = [wallet for wallet in wallets if wallet.role == WalletRole.OPERATIONAL]
        if not 1 <= len(operational) <= 2:
            raise GovernanceFailure(
                "INVALID_WALLET_SET", 409, "Treasury needs one or two operational Safes."
            )

        factory = await self._verified_deployment(
            treasury.chain_id, "TREASURY_MODULE_FACTORY", "1.0.0"
        )
        await self._verified_deployment(
            treasury.chain_id, "TREASURY_MODULE_IMPLEMENTATION", "1.0.0"
        )
        await self._verified_deployment(treasury.chain_id, "SAFE_MULTISEND_CALL_ONLY", "1.4.1")
        safe_addresses = [wallet.safe_address for wallet in [source, *operational]]
        try:
            safe_info = await self._verifier.verify(
                treasury.chain_id, [_address(address) for address in safe_addresses]
            )
        except RpcUnavailable:
            raise
        except SafeVerificationError as exc:
            raise GovernanceFailure(
                exc.code, 422, "A treasury Safe could not be verified."
            ) from None

        mandate = setup["mandate"]

        def limit(name: str) -> tuple[int, int]:
            return int(mandate[name]["perRequest"]), int(mandate[name]["daily"])

        def safe_address_text(value: str) -> bytes:
            return bytes.fromhex(value.removeprefix("0x"))

        tuple_mandate = (
            int(mandate["validFrom"]),
            int(mandate["expiresAt"]),
            int(mandate["payeeCoolingSeconds"]),
            safe_address_text(mandate["executor"]),
            safe_address_text(mandate["guardian"] or "0x" + "00" * 20),
            limit("pay"),
            limit("refill"),
            int(mandate["approvalMaxAge"]),
            limit("supply"),
        )
        approvers = [safe_address_text(item) for item in mandate["approvers"]]
        buffers_by_address = {item["wallet"].lower(): item for item in setup["buffers"]}
        expected_wallets = {"0x" + item.hex() for item in safe_addresses}
        if set(buffers_by_address) != expected_wallets:
            raise GovernanceFailure(
                "BUFFER_SET_INVALID",
                422,
                "Supply one buffer entry for T and each operational Safe.",
            )
        if asset.address is None:
            raise GovernanceFailure(
                "ASSET_UNSUPPORTED", 422, "A native asset cannot initialize the module."
            )
        buffers = [
            (
                wallet.safe_address,
                int(buffers_by_address[_address(wallet.safe_address).lower()]["minimum"]),
                int(buffers_by_address[_address(wallet.safe_address).lower()]["target"]),
            )
            for wallet in [source, *operational]
        ]
        supply_per_request, supply_daily = limit("supply")
        aave = None
        manifest = next(
            item for item in self._configuration.manifests if item.chain_id == treasury.chain_id
        )
        if supply_per_request or supply_daily:
            aave = next((item for item in manifest.deployments if item.name == "AAVE_POOL"), None)
            if aave is None:
                raise GovernanceFailure(
                    "AAVE_POOL_UNAVAILABLE", 503, "Aave pool is not configured."
                )
            await self._verified_deployment(treasury.chain_id, "AAVE_POOL", aave.version)
        aave_address = aave.address_bytes if aave else bytes(20)
        salt = keccak(b"TreasuryPilot.module.v1:" + treasury.id.bytes)
        predicted = await self.predict_module_address(
            chain_id=treasury.chain_id,
            safe=source.safe_address,
            factory=factory.address_bytes,
            salt=salt,
        )
        create_data = module_factory_create_data(
            asset=asset.address,
            operational=[item.safe_address for item in operational],
            mandate=tuple_mandate,
            approvers=approvers,
            buffers=buffers,
            aave_pool=aave_address,
            salt=salt,
        )
        source_calls = [
            GovernanceCall(factory.address_bytes, 0, create_data),
            GovernanceCall(source.safe_address, 0, enable_module_data(predicted)),
        ]
        created = []
        try:
            for wallet, _info in zip([source, *operational], safe_info, strict=True):
                calls = (
                    source_calls
                    if wallet.role == WalletRole.SOURCE
                    else [GovernanceCall(wallet.safe_address, 0, enable_module_data(predicted))]
                )
                created.append(
                    await self.create(
                        organization_id=organization_id,
                        treasury_id=treasury_id,
                        user_id=user_id,
                        purpose=GovernanceTxPurpose.MODULE_SETUP,
                        calls=calls,
                        safe_address=wallet.safe_address,
                    )
                )
        except Exception:
            async with self._sessions() as session, session.begin():
                for created_tx in created:
                    row = await self._row(session, organization_id, created_tx["id"], lock=True)
                    if row.status in (GovernanceTxStatus.COLLECTING, GovernanceTxStatus.READY):
                        row.status = GovernanceTxStatus.CANCELLED
            raise
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(Treasury).where(
                    Treasury.id == treasury_id, Treasury.org_id == organization_id
                )
            )
            if row is not None:
                row.status = row.status.__class__.MODULE_PENDING
        return {
            "governanceTx": created[0],
            "operationalGovernanceTxs": created[1:],
            "predictedModuleAddress": _address(predicted),
            "status": "ModulePending",
        }

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

    async def _record_module_event(self, *, organization_id: uuid.UUID, tx_id: uuid.UUID) -> None:
        async with self._sessions() as session:
            row = await self._row(session, organization_id, tx_id)
            treasury = await session.scalar(
                select(Treasury).where(
                    Treasury.id == row.treasury_id, Treasury.org_id == organization_id
                )
            )
            asset = (
                await session.scalar(select(Asset).where(Asset.id == treasury.asset_id))
                if treasury is not None
                else None
            )
            wallets = list(
                await session.scalars(
                    select(TreasuryWallet).where(
                        TreasuryWallet.treasury_id == row.treasury_id,
                        TreasuryWallet.org_id == organization_id,
                    )
                )
            )
        if (
            row.purpose != GovernanceTxPurpose.MODULE_SETUP
            or row.status != GovernanceTxStatus.EXECUTED
            or treasury is None
            or asset is None
            or asset.address is None
            or row.exec_tx_hash is None
        ):
            return
        source = next((item for item in wallets if item.role == WalletRole.SOURCE), None)
        if source is None:
            return
        manifest = next(
            (item for item in self._configuration.manifests if item.chain_id == row.chain_id), None
        )
        factory = next(
            (
                item
                for item in (manifest.deployments if manifest else ())
                if item.name == "TREASURY_MODULE_FACTORY" and item.version == "1.0.0"
            ),
            None,
        )
        implementation = next(
            (
                item
                for item in (manifest.deployments if manifest else ())
                if item.name == "TREASURY_MODULE_IMPLEMENTATION" and item.version == "1.0.0"
            ),
            None,
        )
        if factory is None or implementation is None:
            return
        chain = next(
            (
                item
                for item in self._configuration.chains
                if item.chain_id == row.chain_id and item.enabled
            ),
            None,
        )
        if chain is None:
            return
        module = treasury.module_address
        if module is None and row.safe_address == source.safe_address:
            expected_topic = _hex(keccak(b"TreasuryModuleCreated(address,address,address)"))
            for template in chain.rpc_urls:
                if not template.startswith(("http://", "https://")):
                    continue
                try:
                    receipt = await asyncio.to_thread(
                        _rpc,
                        resolve_rpc_url(template, self._environ),
                        "eth_getTransactionReceipt",
                        [_hex(row.exec_tx_hash)],
                    )
                    if receipt is None:
                        continue
                    for log in receipt.get("logs", []):
                        topics = [str(item).lower() for item in log.get("topics", [])]
                        if (
                            str(log.get("address", "")).lower()
                            == _address(factory.address_bytes).lower()
                            and len(topics) == 3
                            and topics[0] == expected_topic.lower()
                            and topics[1] == "0x" + source.safe_address.hex().rjust(64, "0")
                            and topics[2] != "0x" + "0" * 64
                            and str(log.get("data", "")).lower()
                            == "0x" + "0" * 24 + asset.address.hex()
                        ):
                            module = bytes.fromhex(topics[2][2:])[-20:]
                            break
                    break
                except Exception:
                    continue
            if module is None:
                return
            expected_runtime = (
                bytes.fromhex("363d3d373d3d3d363d73")
                + implementation.address_bytes
                + bytes.fromhex("5af43d82803e903d91602b57fd5bf3")
            )
            valid_clone = False
            for template in chain.rpc_urls:
                if not template.startswith(("http://", "https://")):
                    continue
                try:
                    code = await asyncio.to_thread(
                        _rpc,
                        resolve_rpc_url(template, self._environ),
                        "eth_getCode",
                        [_address(module), "latest"],
                    )
                    if bytes.fromhex(str(code).removeprefix("0x")) == expected_runtime:
                        valid_clone = True
                        break
                except Exception:
                    continue
            if not valid_clone:
                return
            async with self._sessions() as session, session.begin():
                current = await session.scalar(
                    select(Treasury)
                    .where(Treasury.id == row.treasury_id, Treasury.org_id == organization_id)
                    .with_for_update()
                )
                if current is not None and current.module_address in (None, module):
                    current.module_address = module
                    current.status = TreasuryStatus.MODULE_PENDING
        if module is None:
            return
        enabled_selector = keccak(b"isModuleEnabled(address)")[:4]
        all_enabled = True
        for wallet in wallets:
            enabled = False
            for template in chain.rpc_urls:
                if not template.startswith(("http://", "https://")):
                    continue
                try:
                    result = await asyncio.to_thread(
                        _rpc,
                        resolve_rpc_url(template, self._environ),
                        "eth_call",
                        [
                            {
                                "to": _address(wallet.safe_address),
                                "data": _hex(enabled_selector + encode(["address"], [module])),
                            },
                            "latest",
                        ],
                    )
                    enabled = int(str(result), 16) == 1
                    break
                except Exception:
                    continue
            all_enabled = all_enabled and enabled
        if all_enabled:
            async with self._sessions() as session, session.begin():
                current = await session.scalar(
                    select(Treasury)
                    .where(Treasury.id == row.treasury_id, Treasury.org_id == organization_id)
                    .with_for_update()
                )
                if current is not None and current.module_address == module:
                    current.status = TreasuryStatus.READY

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        user_id: uuid.UUID,
        purpose: GovernanceTxPurpose,
        calls: list[GovernanceCall],
        safe_address: bytes | None = None,
    ) -> dict[str, Any]:
        if safe_address is None:
            treasury, wallet = await self._source(organization_id, treasury_id)
        else:
            async with self._sessions() as session:
                wallet_row = await session.execute(
                    select(Treasury, TreasuryWallet)
                    .join(TreasuryWallet, TreasuryWallet.treasury_id == Treasury.id)
                    .where(
                        Treasury.id == treasury_id,
                        Treasury.org_id == organization_id,
                        TreasuryWallet.org_id == organization_id,
                        TreasuryWallet.safe_address == safe_address,
                    )
                )
                item = wallet_row.one_or_none()
            if item is None:
                raise GovernanceFailure("SAFE_NOT_FOUND", 404, "Treasury Safe not found.")
            treasury, wallet = item
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
            if next_status == GovernanceTxStatus.EXECUTED:
                await self._record_module_event(
                    organization_id=organization_id, tx_id=governance_tx_id
                )

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
