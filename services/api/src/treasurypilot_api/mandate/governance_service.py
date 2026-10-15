"""Persistence and chain reads for in-app Safe governance signatures (MDT-009)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from eth_abi import decode, encode
from eth_hash.auto import keccak
from eth_utils import to_checksum_address
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.compliance.kyb import KybRequired, KybService
from treasurypilot_api.identity.models import WalletLink
from treasurypilot_api.mandate.activation import build_mandate_calls
from treasurypilot_api.mandate.configuration import build_bundle_preview
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
    safe_tx_hash,
)
from treasurypilot_api.mandate.models import (
    GovernanceSignature,
    GovernanceTx,
    GovernanceTxPurpose,
    GovernanceTxStatus,
    MandateStatusEvent,
    MandateVersion,
    MandateVersionStatus,
)
from treasurypilot_api.treasury.config import (
    PlatformConfiguration,
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

logger = logging.getLogger(__name__)

_NONCE_SELECTOR = "0xaffed0e0"  # nonce()
_EXECUTION_EVENTS = {
    "0x" + keccak(b"ExecutionSuccess(bytes32,uint256)").hex(): GovernanceTxStatus.EXECUTED,
    "0x" + keccak(b"ExecutionFailure(bytes32,uint256)").hex(): GovernanceTxStatus.FAILED,
}
_ASSET_POLICY_SET_TOPIC = (
    "0x" + keccak(b"AssetPolicySet(address,bool,uint128,uint128,uint128,uint128)").hex()
)


class _ActivationBlocked(Exception):
    """Mandate read-back can never succeed; the version must move to Discrepancy."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


class GovernanceFailure(Exception):
    def __init__(self, code: str, status: int, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.status = status
        self.detail = detail


def _address(raw: bytes) -> str:
    return to_checksum_address("0x" + raw.hex())


def _address_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        raw = value
    elif isinstance(value, str):
        raw = bytes.fromhex(value.removeprefix("0x"))
    else:
        raise ValueError("chain response address is malformed")
    if len(raw) != 20:
        raise ValueError("chain response address is malformed")
    return raw


def _hex(raw: bytes) -> str:
    return "0x" + raw.hex()


def _config_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not a base-unit amount")
    return int(value)


def _config_timestamp(value: Any) -> int:
    if not isinstance(value, str):
        raise ValueError("mandate timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("mandate timestamp must include a timezone")
    return int(parsed.astimezone(UTC).timestamp())


def _config_limit(config: Mapping[str, Any], name: str) -> tuple[int, int]:
    raw = config.get(name)
    if raw is None:
        return (0, 0)
    if not isinstance(raw, Mapping):
        raise ValueError(f"{name} limits are malformed")
    return (_config_int(raw.get("perRequest", 0)), _config_int(raw.get("daily", 0)))


def _projection_hash(value: Mapping[str, Any]) -> bytes:
    def json_default(item: object) -> str:
        if isinstance(item, bytes):
            return _hex(item)
        raise TypeError(f"unsupported projection value: {type(item).__name__}")

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).digest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return _hex(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_safe(item) for item in value]
    return value


def _asset_policy_events(
    receipt: Mapping[str, Any], module_address: bytes
) -> dict[str, tuple[bool, int, int, int, int]]:
    """Return the final AssetPolicySet values emitted by this execution receipt."""
    policies: dict[str, tuple[bool, int, int, int, int]] = {}
    for log in receipt.get("logs", []):
        if not isinstance(log, Mapping):
            continue
        topics = log.get("topics", [])
        if (
            str(log.get("address", "")).lower() != _address(module_address).lower()
            or not isinstance(topics, list)
            or len(topics) < 2
            or str(topics[0]).lower() != _ASSET_POLICY_SET_TOPIC
        ):
            continue
        try:
            asset = "0x" + str(topics[1]).removeprefix("0x")[-40:].lower()
            raw = bytes.fromhex(str(log.get("data", "")).removeprefix("0x"))
            enabled, pay_request, pay_daily, refill_request, refill_daily = decode(
                ["bool", "uint128", "uint128", "uint128", "uint128"], raw
            )
        except Exception:
            continue
        policies[asset] = (
            bool(enabled),
            int(pay_request),
            int(pay_daily),
            int(refill_request),
            int(refill_daily),
        )
    return policies


class GovernanceService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        verifier: RpcSafeVerifier,
        configuration: PlatformConfiguration,
        environ: Mapping[str, str] = os.environ,
        kyb_service: KybService | None = None,
    ) -> None:
        self._kyb = kyb_service
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

    async def _require_kyb(self, organization_id: uuid.UUID, chain_id: int) -> None:
        """Mainnet activation needs KYB approval (F-111); a chain not known to be a testnet counts as mainnet."""
        chains = self._configuration.chains if self._configuration is not None else ()
        if any(c.chain_id == chain_id and c.is_testnet for c in chains):
            return
        try:
            if self._kyb is None:
                raise KybRequired(None)
            await self._kyb.require_approved(organization_id)
        except KybRequired:
            raise GovernanceFailure(
                "KYB_REQUIRED", 409, "KYB approval is required to activate a mainnet treasury."
            ) from None

    async def _read(self, chain_id: int, method: str, params: list[object]) -> Any:
        try:
            return await self._verifier.call(chain_id, method, params)
        except SafeVerificationError:
            raise GovernanceFailure(
                "WRONG_CHAIN", 422, "The treasury chain is not enabled."
            ) from None

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
        result = await self._read(
            chain_id, "eth_call", [{"to": _address(safe), "data": _NONCE_SELECTOR}, "latest"]
        )
        return int(str(result), 16)

    async def _rpc_first(
        self,
        chain: Any,
        method: str,
        params: list[Any],
        parse: Callable[[Any], Any] = lambda result: result,
    ) -> Any:
        """Return the first non-None parsed answer across HTTP providers, else None."""
        for template in chain.rpc_urls:
            if not template.startswith(("http://", "https://")):
                continue
            try:
                result = parse(
                    await asyncio.to_thread(
                        _rpc, resolve_rpc_url(template, self._environ), method, params
                    )
                )
            except Exception:
                continue
            if result is not None:
                return result
        return None

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

        def parse_address(result: Any) -> bytes | None:
            predicted = bytes.fromhex(str(result).removeprefix("0x"))
            return predicted[-20:] if len(predicted) == 32 and any(predicted[-20:]) else None

        address: bytes | None = await self._rpc_first(
            chain,
            "eth_call",
            [{"to": _address(factory), "data": _hex(data)}, "latest"],
            parse_address,
        )
        if address is not None:
            code = await self._rpc_first(chain, "eth_getCode", [_address(address), "latest"], str)
            if code is not None:
                if code != "0x":
                    raise GovernanceFailure(
                        "MODULE_ALREADY_DEPLOYED",
                        409,
                        "The deterministic module address already has code.",
                    )
                return address
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
        verified = await self._rpc_first(
            chain,
            "eth_getCode",
            [_address(deployment.address_bytes), "latest"],
            lambda code: (
                True
                if (raw := bytes.fromhex(str(code).removeprefix("0x")))
                and keccak(raw) == deployment.code_hash_bytes
                else None
            ),
        )
        if verified:
            return deployment
        raise RpcUnavailable(f"configured {name} code could not be verified on chain {chain_id}")

    async def create_module_setup(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        user_id: uuid.UUID,
        setup: Mapping[str, Any],
    ) -> dict[str, Any]:
        # Serialize per treasury so the open-setup check and the row creation are atomic.
        async with self._sessions() as lock_session, lock_session.begin():
            await lock_session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"module-setup:{treasury_id}"},
            )
            return await self._create_module_setup(
                organization_id=organization_id,
                treasury_id=treasury_id,
                user_id=user_id,
                setup=setup,
            )

    async def _create_module_setup(
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
        for buffer_wallet, minimum, target in buffers:
            if buffer_wallet != source.safe_address and target < minimum:
                raise GovernanceFailure(
                    "BUFFER_TARGET_BELOW_MINIMUM",
                    422,
                    "An operational Safe buffer target must not be below its minimum.",
                )
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
            for created_tx in created:
                # A failed cleanup must not mask the original error or skip the other rows.
                try:
                    async with self._sessions() as session, session.begin():
                        row = await self._row(session, organization_id, created_tx["id"], lock=True)
                        if row.status in (GovernanceTxStatus.COLLECTING, GovernanceTxStatus.READY):
                            row.status = GovernanceTxStatus.CANCELLED
                except Exception:
                    logger.exception("module setup rollback failed for %s", created_tx["id"])
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
        """Outcome of the submitted tx; READY means the outer tx reverted and the Safe nonce
        is unconsumed, so the stored signatures are still usable."""
        receipt = await self._read(chain_id, "eth_getTransactionReceipt", [_hex(transaction_hash)])
        if receipt is None:
            return None
        if str(receipt.get("status", "0x1")).lower() == "0x0":
            return GovernanceTxStatus.READY
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
            or treasury.status == TreasuryStatus.READY
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
            asset_address = asset.address

            def parse_module(receipt: Any) -> bytes | None:
                for log in (receipt or {}).get("logs", []):
                    topics = [str(item).lower() for item in log.get("topics", [])]
                    if (
                        str(log.get("address", "")).lower()
                        == _address(factory.address_bytes).lower()
                        and len(topics) == 3
                        and topics[0] == expected_topic.lower()
                        and topics[1] == "0x" + source.safe_address.hex().rjust(64, "0")
                        and topics[2] != "0x" + "0" * 64
                        and str(log.get("data", "")).lower()
                        == "0x" + "0" * 24 + asset_address.hex()
                    ):
                        return bytes.fromhex(topics[2][2:])[-20:]
                return None

            module = await self._rpc_first(
                chain, "eth_getTransactionReceipt", [_hex(row.exec_tx_hash)], parse_module
            )
            if module is None:
                return
            expected_runtime = (
                bytes.fromhex("363d3d373d3d3d363d73")
                + implementation.address_bytes
                + bytes.fromhex("5af43d82803e903d91602b57fd5bf3")
            )
            valid_clone = await self._rpc_first(
                chain,
                "eth_getCode",
                [_address(module), "latest"],
                lambda code: (
                    True
                    if bytes.fromhex(str(code).removeprefix("0x")) == expected_runtime
                    else None
                ),
            )
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
            enabled = await self._rpc_first(
                chain,
                "eth_call",
                [
                    {
                        "to": _address(wallet.safe_address),
                        "data": _hex(enabled_selector + encode(["address"], [module])),
                    },
                    "latest",
                ],
                lambda result: int(str(result), 16) == 1,
            )
            all_enabled = all_enabled and bool(enabled)
        if all_enabled:
            try:
                await self._require_kyb(organization_id, row.chain_id)
            except GovernanceFailure:
                return  # stays ModulePending until KYB is approved
            async with self._sessions() as session, session.begin():
                current = await session.scalar(
                    select(Treasury)
                    .where(Treasury.id == row.treasury_id, Treasury.org_id == organization_id)
                    .with_for_update()
                )
                if current is not None and current.module_address == module:
                    current.status = TreasuryStatus.READY

    async def _module_view(
        self,
        chain_id: int,
        module: bytes,
        signature: str,
        return_types: list[str],
        argument_types: list[str] | None = None,
        arguments: list[Any] | None = None,
        *,
        block_tag: str = "latest",
    ) -> tuple[Any, ...]:
        data = keccak(signature.encode("ascii"))[:4]
        if argument_types:
            data += encode(argument_types, arguments or [])
        result = await self._read(
            chain_id,
            "eth_call",
            [{"to": _address(module), "data": _hex(data)}, block_tag],
        )
        try:
            raw = bytes.fromhex(str(result).removeprefix("0x"))
            return decode(return_types, raw)
        except Exception as exc:
            raise RpcUnavailable(f"malformed {signature} response from chain {chain_id}") from exc

    async def _record_mandate_activation(
        self, *, organization_id: uuid.UUID, tx_id: uuid.UUID
    ) -> None:
        try:
            await self._read_back_mandate_activation(organization_id=organization_id, tx_id=tx_id)
        except (_ActivationBlocked, KeyError, ValueError, TypeError) as exc:
            # A permanent failure must surface to Owners instead of leaving PendingActivation forever.
            code = exc.code if isinstance(exc, _ActivationBlocked) else "MANDATE_CONFIG_INVALID"
            logger.warning("mandate activation blocked", extra={"tx_id": str(tx_id), "code": code})
            await self._mark_activation_discrepancy(
                organization_id=organization_id, tx_id=tx_id, code=code, detail=str(exc)
            )

    async def _mark_activation_discrepancy(
        self, *, organization_id: uuid.UUID, tx_id: uuid.UUID, code: str, detail: str
    ) -> None:
        from treasurypilot_api.recovery.review_queue import create_for_mandate_discrepancy

        async with self._sessions() as session, session.begin():
            tx = await self._row(session, organization_id, tx_id)
            current = await session.scalar(
                select(MandateVersion)
                .where(
                    MandateVersion.id == tx.entity_id,
                    MandateVersion.org_id == organization_id,
                    MandateVersion.status == MandateVersionStatus.PENDING_ACTIVATION,
                )
                .with_for_update()
            )
            if current is None:
                return
            current.status = MandateVersionStatus.DISCREPANCY
            await create_for_mandate_discrepancy(
                session,
                mandate_version=current,
                primary_code=code,
                actual={"detail": detail},
            )
            session.add(
                MandateStatusEvent(
                    org_id=organization_id,
                    mandate_version_id=current.id,
                    from_status=MandateVersionStatus.PENDING_ACTIVATION,
                    to_status=MandateVersionStatus.DISCREPANCY,
                    tx_hash=tx.exec_tx_hash,
                )
            )

    async def _read_back_mandate_activation(
        self, *, organization_id: uuid.UUID, tx_id: uuid.UUID
    ) -> None:
        async with self._sessions() as session:
            tx = await self._row(session, organization_id, tx_id)
            if (
                tx.purpose != GovernanceTxPurpose.MANDATE
                or tx.status != GovernanceTxStatus.EXECUTED
                or tx.entity_type != "mandate_version"
                or tx.entity_id is None
                or tx.exec_tx_hash is None
            ):
                return
            mandate = await session.scalar(
                select(MandateVersion).where(
                    MandateVersion.id == tx.entity_id,
                    MandateVersion.org_id == organization_id,
                    MandateVersion.treasury_id == tx.treasury_id,
                )
            )
            treasury = await session.scalar(
                select(Treasury).where(
                    Treasury.id == tx.treasury_id, Treasury.org_id == organization_id
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
                        TreasuryWallet.treasury_id == tx.treasury_id,
                        TreasuryWallet.org_id == organization_id,
                    )
                )
            )
            versions = list(
                await session.scalars(
                    select(MandateVersion).where(
                        MandateVersion.treasury_id == tx.treasury_id,
                        MandateVersion.org_id == organization_id,
                    )
                )
            )
            chain_assets = list(
                await session.scalars(select(Asset).where(Asset.chain_id == tx.chain_id))
            )
        if mandate is None or mandate.status != MandateVersionStatus.PENDING_ACTIVATION:
            return
        if (
            treasury is None
            or treasury.module_address is None
            or asset is None
            or asset.address is None
        ):
            raise _ActivationBlocked(
                "MANDATE_METADATA_MISSING", "Treasury module or asset metadata is missing."
            )

        chain = next(
            (
                item
                for item in self._configuration.chains
                if item.chain_id == tx.chain_id and item.enabled
            ),
            None,
        )
        if chain is None:
            raise _ActivationBlocked("MANDATE_CHAIN_DISABLED", "The treasury chain is not enabled.")
        receipt = await self._read(
            tx.chain_id, "eth_getTransactionReceipt", [_hex(tx.exec_tx_hash)]
        )
        if not isinstance(receipt, dict) or receipt.get("blockNumber") is None:
            return
        try:
            receipt_block = int(str(receipt["blockNumber"]), 16)
            latest_block = int(str(await self._read(tx.chain_id, "eth_blockNumber", [])), 16)
        except (TypeError, ValueError) as exc:
            raise RpcUnavailable(f"malformed confirmation response for {tx.id}") from exc
        if latest_block - receipt_block + 1 < chain.confirmations:
            return
        receipt_block_tag = hex(receipt_block)

        async def confirmed_view(
            module: bytes,
            signature: str,
            return_types: list[str],
            argument_types: list[str] | None = None,
            arguments: list[Any] | None = None,
        ) -> tuple[Any, ...]:
            return await self._module_view(
                tx.chain_id,
                module,
                signature,
                return_types,
                argument_types,
                arguments,
                block_tag=receipt_block_tag,
            )

        policy_events = _asset_policy_events(receipt, treasury.module_address)

        config = dict(mandate.config)
        previous = next(
            (dict(item.config) for item in versions if item.status == MandateVersionStatus.ACTIVE),
            {},
        )
        limits = config.get("limits")
        if not isinstance(limits, Mapping):
            raise _ActivationBlocked("MANDATE_CONFIG_INVALID", "Mandate limits are missing.")
        pay = _config_limit(limits, "PAY")
        refill = _config_limit(limits, "REFILL")
        supply = _config_limit(config, "supplyLimits")
        expected_mandate = (
            _config_timestamp(config.get("validFrom")),
            _config_timestamp(config.get("expiresAt")),
            _config_int(config.get("payeeCoolingSeconds", 0)),
            bytes.fromhex(str(config["executor"]).removeprefix("0x")),
            bytes.fromhex(str(config.get("guardian") or ("0x" + "00" * 20)).removeprefix("0x")),
            pay,
            refill,
            _config_int(config.get("approvalMaxAge", 0)),
            supply,
        )
        actual_mandate = await confirmed_view(
            treasury.module_address,
            "mandate()",
            [
                "(uint64,uint64,uint64,uint32,address,address,(uint128,uint128),"
                "(uint128,uint128),uint32,(uint128,uint128))"
            ],
        )
        observed_version = int(actual_mandate[0][0])
        actual_mandate_config = tuple(actual_mandate[0][1:])

        current_approvers = {
            str(value).lower() for value in config.get("approvers", []) if isinstance(value, str)
        }
        previous_approvers = {
            str(value).lower() for value in previous.get("approvers", []) if isinstance(value, str)
        }
        approver_addresses = sorted(current_approvers | previous_approvers)
        expected_approvers = [[value, value in current_approvers] for value in approver_addresses]
        actual_approvers: list[list[Any]] = []
        for value in approver_addresses:
            approved = await confirmed_view(
                treasury.module_address,
                "isApprover(address)",
                ["bool"],
                ["address"],
                [value],
            )
            actual_approvers.append([value, bool(approved[0])])

        expected_buffers: list[list[Any]] = []
        actual_buffers: list[list[Any]] = []
        configured_buffers = {
            str(item.get("wallet", "")).lower(): item
            for item in config.get("buffers", [])
            if isinstance(item, Mapping)
        }
        for wallet in sorted(wallets, key=lambda item: item.safe_address):
            wallet_address = _address(wallet.safe_address).lower()
            configured = configured_buffers.get(wallet_address, {})
            expected_pair = [
                wallet_address,
                _config_int(configured.get("minimum", 0)),
                _config_int(configured.get("target", 0)),
            ]
            buffer_value = await confirmed_view(
                treasury.module_address,
                "bufferOf(address)",
                ["uint256"],
                ["address"],
                [wallet_address],
            )
            target_value = await confirmed_view(
                treasury.module_address,
                "targetOf(address)",
                ["uint256"],
                ["address"],
                [wallet_address],
            )
            expected_buffers.append(expected_pair)
            actual_buffers.append([wallet_address, int(buffer_value[0]), int(target_value[0])])

        metadata = {
            str(item.id): "0x" + item.address.hex()
            for item in chain_assets
            if item.address is not None and not item.is_native
        }
        old_policies = {
            str(item.get("assetId")): item
            for item in previous.get("assetPolicies", [])
            if isinstance(item, Mapping)
        }
        new_policies = {
            str(item.get("assetId")): item
            for item in config.get("assetPolicies", [])
            if isinstance(item, Mapping)
        }
        configure_selector = (
            "0x"
            + keccak(
                b"configureMandate((uint64,uint64,uint32,address,address,(uint128,uint128),"
                b"(uint128,uint128),uint32,(uint128,uint128)))"
            )[:4].hex()
        )
        mandate_reconfigured = any(
            isinstance(call, Mapping)
            and str(call.get("data", "")).lower().startswith(configure_selector)
            for call in tx.calls
        )
        expected_assets: list[list[Any]] = []
        actual_assets: list[list[Any]] = []
        for asset_id in sorted(old_policies.keys() | new_policies.keys()):
            address = metadata.get(asset_id)
            if address is None:
                raise _ActivationBlocked(
                    "MANDATE_METADATA_MISSING", f"Asset {asset_id} has no on-chain address."
                )
            policy = new_policies.get(asset_id, {})
            enabled = asset_id in new_policies
            policy_limits = policy.get("limits", {}) if enabled else {}
            expected_pay_limits = _config_limit(policy_limits, "PAY")
            expected_refill_limits = _config_limit(policy_limits, "REFILL")
            policy_was_changed = mandate_reconfigured or old_policies.get(
                asset_id
            ) != new_policies.get(asset_id)
            observed_policy = policy_events.get(address.lower())
            if not policy_was_changed:
                # This unchanged policy was verified when its previous mandate became Active.
                observed_policy = (
                    enabled,
                    *expected_pay_limits,
                    *expected_refill_limits,
                )
            is_allowed = await confirmed_view(
                treasury.module_address,
                "isAssetAllowed(address)",
                ["bool"],
                ["address"],
                [address],
            )
            expected_asset_buffers = {
                str(item.get("wallet", "")).lower(): item
                for item in policy.get("buffers", [])
                if isinstance(item, Mapping)
            }
            for wallet in sorted(wallets, key=lambda item: item.safe_address):
                wallet_address = _address(wallet.safe_address).lower()
                expected_buffer = expected_asset_buffers.get(wallet_address, {})
                expected_pair = [
                    wallet_address,
                    _config_int(expected_buffer.get("minimum", 0)),
                    _config_int(expected_buffer.get("target", 0)),
                ]
                buffer_value = await confirmed_view(
                    treasury.module_address,
                    "bufferOf(address,address)",
                    ["uint256"],
                    ["address", "address"],
                    [address, wallet_address],
                )
                target_value = await confirmed_view(
                    treasury.module_address,
                    "targetOf(address,address)",
                    ["uint256"],
                    ["address", "address"],
                    [address, wallet_address],
                )
                expected_assets.append(
                    [
                        address.lower(),
                        enabled,
                        enabled,
                        *expected_pay_limits,
                        *expected_refill_limits,
                        *expected_pair,
                    ]
                )
                actual_assets.append(
                    [
                        address.lower(),
                        bool(is_allowed[0]),
                        observed_policy[0] if observed_policy is not None else None,
                        *(observed_policy[1:] if observed_policy is not None else [None] * 4),
                        wallet_address,
                        int(buffer_value[0]),
                        int(target_value[0]),
                    ]
                )

        supply_was_configured = any(
            isinstance(item.config.get("supplyLimits"), Mapping)
            and (
                _config_int(item.config["supplyLimits"].get("perRequest", 0)) > 0
                or _config_int(item.config["supplyLimits"].get("daily", 0)) > 0
            )
            for item in versions
        )
        actual_pool = await confirmed_view(treasury.module_address, "aavePool()", ["address"])
        actual_a_token = await confirmed_view(treasury.module_address, "aToken()", ["address"])
        actual_pool_address = _address_bytes(actual_pool[0])
        actual_a_token_address = _address_bytes(actual_a_token[0])
        expected_pool = bytes(20)
        expected_a_token = bytes(20)
        aave_identity_matches = True
        if supply_was_configured or actual_pool_address != bytes(20):
            manifest = next(
                (item for item in self._configuration.manifests if item.chain_id == tx.chain_id),
                None,
            )
            pool = next(
                (
                    item
                    for item in (manifest.deployments if manifest else ())
                    if item.name == "AAVE_POOL"
                ),
                None,
            )
            if pool is None:
                aave_identity_matches = False
            else:
                pool = await self._verified_deployment(tx.chain_id, "AAVE_POOL", pool.version)
                reserve = await confirmed_view(
                    pool.address_bytes,
                    "getReserveData(address)",
                    [
                        "(uint256,uint128,uint128,uint128,uint128,uint128,uint40,uint16,address,"
                        "address,address,address,uint128,uint128,uint128)"
                    ],
                    ["address"],
                    [_address(asset.address)],
                )
                expected_pool = pool.address_bytes
                expected_a_token = _address_bytes(reserve[0][8])
                token_underlying = await confirmed_view(
                    expected_a_token,
                    "UNDERLYING_ASSET_ADDRESS()",
                    ["address"],
                )
                token_pool = await confirmed_view(expected_a_token, "POOL()", ["address"])
                aave_identity_matches = (
                    actual_pool_address == expected_pool
                    and actual_a_token_address == expected_a_token
                    and _address_bytes(token_underlying[0]) == asset.address
                    and _address_bytes(token_pool[0]) == expected_pool
                )
        elif actual_a_token_address != bytes(20):
            aave_identity_matches = False

        expected_projection: dict[str, Any] = {
            "mandate": _json_safe(expected_mandate),
            "approvers": expected_approvers,
            "buffers": expected_buffers,
            "assetPolicies": expected_assets,
            "aavePool": _hex(expected_pool),
            "aToken": _hex(expected_a_token),
            "aaveIdentity": True,
        }
        actual_projection: dict[str, Any] = {
            "mandate": _json_safe(actual_mandate_config),
            "approvers": actual_approvers,
            "buffers": actual_buffers,
            "assetPolicies": actual_assets,
            "aavePool": _hex(actual_pool_address),
            "aToken": _hex(actual_a_token_address),
            "aaveIdentity": aave_identity_matches,
        }
        matches = _projection_hash(expected_projection) == _projection_hash(actual_projection)
        event_hash = tx.exec_tx_hash
        async with self._sessions() as session, session.begin():
            current = await session.scalar(
                select(MandateVersion)
                .where(
                    MandateVersion.id == mandate.id,
                    MandateVersion.org_id == organization_id,
                    MandateVersion.status == MandateVersionStatus.PENDING_ACTIVATION,
                )
                .with_for_update()
            )
            if current is None:
                return
            current.onchain_version = observed_version if observed_version else None
            if matches:
                previous_active = list(
                    await session.scalars(
                        select(MandateVersion)
                        .where(
                            MandateVersion.treasury_id == tx.treasury_id,
                            MandateVersion.org_id == organization_id,
                            MandateVersion.status == MandateVersionStatus.ACTIVE,
                        )
                        .with_for_update()
                    )
                )
                for item in previous_active:
                    item.status = MandateVersionStatus.SUPERSEDED
                    session.add(
                        MandateStatusEvent(
                            org_id=organization_id,
                            mandate_version_id=item.id,
                            from_status=MandateVersionStatus.ACTIVE,
                            to_status=MandateVersionStatus.SUPERSEDED,
                            tx_hash=event_hash,
                        )
                    )
                current.status = MandateVersionStatus.ACTIVE
                current.activated_at = datetime.now(UTC)
                to_status = MandateVersionStatus.ACTIVE
            else:
                current.status = MandateVersionStatus.DISCREPANCY
                to_status = MandateVersionStatus.DISCREPANCY
                from treasurypilot_api.recovery.review_queue import (
                    create_for_mandate_discrepancy,
                )

                await create_for_mandate_discrepancy(
                    session,
                    mandate_version=current,
                    primary_code="MANDATE_READBACK_MISMATCH",
                    expected=expected_projection,
                    actual=actual_projection,
                )
            session.add(
                MandateStatusEvent(
                    org_id=organization_id,
                    mandate_version_id=current.id,
                    from_status=MandateVersionStatus.PENDING_ACTIVATION,
                    to_status=to_status,
                    tx_hash=event_hash,
                )
            )

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        user_id: uuid.UUID,
        purpose: GovernanceTxPurpose,
        calls: list[GovernanceCall],
        safe_address: bytes | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
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
        if purpose == GovernanceTxPurpose.MODULE_SETUP:
            await self._require_kyb(organization_id, treasury.chain_id)
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
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"governance:{treasury.chain_id}:{wallet.safe_address.hex()}"},
            )
            # Read under the lock so a concurrent execution cannot leave the new row below it.
            chain_nonce = await self._nonce(treasury.chain_id, wallet.safe_address)
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
            row = GovernanceTx(
                id=uuid.uuid4(),
                org_id=organization_id,
                treasury_id=treasury_id,
                chain_id=treasury.chain_id,
                safe_address=wallet.safe_address,
                purpose=purpose,
                entity_type=entity_type,
                entity_id=entity_id,
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

    async def create_mandate_activation(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        mandate_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Create a Safe transaction for a Draft and move it into PendingActivation."""
        async with self._sessions() as session, session.begin():
            mandate = await session.scalar(
                select(MandateVersion)
                .where(
                    MandateVersion.id == mandate_id,
                    MandateVersion.treasury_id == treasury_id,
                    MandateVersion.org_id == organization_id,
                )
                .with_for_update()
            )
            if mandate is None:
                raise GovernanceFailure("MANDATE_NOT_FOUND", 404, "Mandate version not found.")
            if mandate.status != MandateVersionStatus.DRAFT:
                raise GovernanceFailure(
                    "MANDATE_NOT_DRAFT",
                    409,
                    "Only a Draft mandate can be submitted for activation.",
                )
            treasury = await session.scalar(
                select(Treasury).where(
                    Treasury.id == treasury_id, Treasury.org_id == organization_id
                )
            )
            if treasury is None:
                raise GovernanceFailure("TREASURY_NOT_FOUND", 404, "Treasury not found.")
            if treasury.module_address is None:
                raise GovernanceFailure(
                    "MODULE_NOT_READY",
                    409,
                    "Deploy and enable the treasury module before activation.",
                )
            active = await session.scalar(
                select(MandateVersion)
                .where(
                    MandateVersion.treasury_id == treasury_id,
                    MandateVersion.org_id == organization_id,
                    MandateVersion.status == MandateVersionStatus.ACTIVE,
                )
                .order_by(MandateVersion.version.desc())
                .limit(1)
            )
            chain_assets = await session.scalars(
                select(Asset).where(Asset.chain_id == treasury.chain_id)
            )
            asset_metadata: dict[str, dict[str, object]] = {
                str(asset.id): {"address": _address(asset.address)}
                for asset in chain_assets
                if asset.address is not None and not asset.is_native
            }
            previous = dict(active.config) if active is not None else None
            current = dict(mandate.config)
            preview = build_bundle_preview(previous, current, asset_metadata=asset_metadata)
            preview_calls = preview["calls"]
            if not isinstance(preview_calls, list) or not all(
                isinstance(item, dict) for item in preview_calls
            ):
                raise GovernanceFailure(
                    "MANDATE_CALL_INVALID", 422, "Mandate call preview is malformed."
                )
            if not preview_calls:
                raise GovernanceFailure(
                    "NO_CHANGES", 409, "This mandate version has no on-chain changes to activate."
                )
            try:
                encoded_calls = build_mandate_calls(
                    treasury.module_address,
                    preview_calls,
                )
            except ValueError as exc:
                raise GovernanceFailure("MANDATE_CALL_INVALID", 422, str(exc)) from None
            supply_limits = _config_limit(current, "supplyLimits")
            if any(supply_limits):
                configured_pool = await self._module_view(
                    treasury.chain_id, treasury.module_address, "aavePool()", ["address"]
                )
                if _address_bytes(configured_pool[0]) == bytes(20):
                    raise GovernanceFailure(
                        "AAVE_POOL_REQUIRED",
                        409,
                        "SUPPLY requires a treasury module initialized with an Aave pool.",
                    )
            # The row lock is held across create so concurrent submissions cannot both create a Safe tx.
            created = await self.create(
                organization_id=organization_id,
                treasury_id=treasury_id,
                user_id=user_id,
                purpose=GovernanceTxPurpose.MANDATE,
                calls=encoded_calls,
                entity_type="mandate_version",
                entity_id=mandate.id,
            )
            tx_id = uuid.UUID(str(created["id"]))
            mandate.status = MandateVersionStatus.PENDING_ACTIVATION
            mandate.governance_tx_id = tx_id
            session.add(
                MandateStatusEvent(
                    org_id=organization_id,
                    mandate_version_id=mandate.id,
                    from_status=MandateVersionStatus.DRAFT,
                    to_status=MandateVersionStatus.PENDING_ACTIVATION,
                    by_user_id=user_id,
                )
            )
            version = mandate.version
        return created | {
            "mandate": {
                "id": str(mandate_id),
                "version": version,
                "status": MandateVersionStatus.PENDING_ACTIVATION.value,
            },
            "bundlePreview": preview,
        }

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
            try:
                await self.refresh(
                    organization_id=organization_id, governance_tx_id=governance_tx_id
                )
            except RpcUnavailable:
                pass  # A plain read still returns the stored state while the chain RPC is down.
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
            kind = "DELEGATECALL " if call["operation"] == 1 else ""
            descriptions.append(
                f"{kind}call {index}: {call['to']}, value {call['value']} base units, "
                f"selector {selector}"
            )
        return f"{label}: " + "; ".join(descriptions)

    async def refresh(self, *, organization_id: uuid.UUID, governance_tx_id: uuid.UUID) -> None:
        async with self._sessions() as session:
            row = await self._row(session, organization_id, governance_tx_id)
            chain_id, safe = row.chain_id, row.safe_address
            nonce, status, purpose = row.safe_nonce, row.status, row.purpose
            submitted_hash, signed_hash = row.exec_tx_hash, row.safe_tx_hash
        next_status: GovernanceTxStatus | None = None
        if status == GovernanceTxStatus.SUBMITTED and submitted_hash is not None:
            # No receipt yet stays SUBMITTED: a lagging provider must not mislabel an executed tx.
            next_status = await self._receipt_status(chain_id, submitted_hash, safe, signed_hash)
            # Reverted outer tx: reopen unless another tx has since consumed the nonce.
            if (
                next_status == GovernanceTxStatus.READY
                and await self._nonce(chain_id, safe) > nonce
            ):
                next_status = GovernanceTxStatus.SUPERSEDED
        elif status in (GovernanceTxStatus.COLLECTING, GovernanceTxStatus.READY):
            if await self._nonce(chain_id, safe) > nonce:
                next_status = GovernanceTxStatus.SUPERSEDED
        elif status == GovernanceTxStatus.EXECUTED and purpose == GovernanceTxPurpose.MODULE_SETUP:
            # Retry the module reconciliation if a transient RPC failure skipped it earlier.
            await self._record_module_event(organization_id=organization_id, tx_id=governance_tx_id)
        elif status == GovernanceTxStatus.EXECUTED and purpose == GovernanceTxPurpose.MANDATE:
            # Retry read-back after confirmations if the first receipt check was too early.
            await self._record_mandate_activation(
                organization_id=organization_id, tx_id=governance_tx_id
            )
        if next_status is not None:
            async with self._sessions() as session, session.begin():
                row = await self._row(session, organization_id, governance_tx_id)
                # exec_tx_hash unchanged: a concurrent resubmission must not be overwritten.
                if (
                    row.status
                    in (
                        GovernanceTxStatus.COLLECTING,
                        GovernanceTxStatus.READY,
                        GovernanceTxStatus.SUBMITTED,
                    )
                    and row.exec_tx_hash == submitted_hash
                ):
                    row.status = next_status
                    if next_status == GovernanceTxStatus.READY:
                        row.exec_tx_hash = None
            if next_status == GovernanceTxStatus.EXECUTED:
                if purpose == GovernanceTxPurpose.MODULE_SETUP:
                    await self._record_module_event(
                        organization_id=organization_id, tx_id=governance_tx_id
                    )
                elif purpose == GovernanceTxPurpose.MANDATE:
                    await self._record_mandate_activation(
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
        await self.refresh(organization_id=organization_id, governance_tx_id=governance_tx_id)
        async with self._sessions() as session, session.begin():
            row = await self._row(session, organization_id, governance_tx_id, lock=True)
            # A SUBMITTED row without a receipt may be re-reported (typo or dropped tx).
            if row.status not in (GovernanceTxStatus.READY, GovernanceTxStatus.SUBMITTED):
                raise GovernanceFailure(
                    "NOT_READY", 409, "Only a ready or submitted transaction can be reported."
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
            try:
                packed = pack_signatures(
                    self._typed(row), signatures, row.owners_snapshot, row.threshold
                )
            except ValueError:
                raise GovernanceFailure(
                    "SIGNATURE_INVALID", 409, "The stored signatures no longer verify."
                ) from None
            return {
                "to": _address(row.safe_address),
                "data": _hex(
                    exec_transaction_data(
                        self._safe_tx(row), nonce=row.safe_nonce, packed_signatures=packed
                    )
                ),
            }
