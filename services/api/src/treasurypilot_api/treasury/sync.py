from __future__ import annotations

import os
import uuid
from collections.abc import Mapping

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from treasurypilot_api.treasury.config import PlatformConfiguration
from treasurypilot_api.treasury.models import Asset, Chain, Deployment
from treasurypilot_api.treasury.onchain import verify_asset_decimals

DEPLOYMENT_ID_NAMESPACE = uuid.UUID("3c673901-8dd4-4fbb-89f2-74622778fb80")
ASSET_ID_NAMESPACE = uuid.UUID("9b0f4f43-0a4e-4a43-9d39-3c1b2f6f0a36")


ASSET_MUTABLE_COLUMNS = ("symbol", "decimals", "issuer_label", "is_test")


def asset_id(chain_id: int, address: str) -> uuid.UUID:
    """Return the stable primary key for a configured asset."""

    return uuid.uuid5(ASSET_ID_NAMESPACE, f"{chain_id}:{address.lower()}")


def deployment_id(chain_id: int, name: str, version: str) -> uuid.UUID:
    """Return the stable primary key for a configured deployment."""

    return uuid.uuid5(DEPLOYMENT_ID_NAMESPACE, f"{chain_id}:{name}:{version}")


async def sync_platform_configuration(
    session: AsyncSession,
    configuration: PlatformConfiguration,
    environ: Mapping[str, str] = os.environ,
) -> None:
    """Idempotently synchronize validated platform-owned configuration.

    Chains that are no longer configured are disabled rather than deleted so
    treasuries and deployments that reference them keep their history. Assets of
    enabled chains are added only after their on-chain decimals match (M02-D9).
    """

    for chain in sorted(configuration.chains, key=lambda item: item.chain_id):
        values = {
            "chain_id": chain.chain_id,
            "name": chain.name,
            "is_testnet": chain.is_testnet,
            "confirmations": chain.confirmations,
            "explorer_url": str(chain.explorer_url),
            "rpc_urls": [str(url) for url in chain.rpc_urls],
            "enabled": chain.enabled,
        }
        statement = insert(Chain).values(**values)
        changed = or_(
            *(Chain.__table__.c[key].is_distinct_from(value) for key, value in values.items())
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[Chain.chain_id],
                set_={
                    **{key: statement.excluded[key] for key in values if key != "chain_id"},
                    "updated_at": func.now(),
                    "version": Chain.version + 1,
                },
                where=changed,
            )
        )

    configured_chain_ids = [chain.chain_id for chain in configuration.chains]
    await session.execute(
        update(Chain)
        .where(Chain.chain_id.not_in(configured_chain_ids), Chain.enabled.is_(True))
        .values(enabled=False, updated_at=func.now(), version=Chain.version + 1)
        .execution_options(synchronize_session=False)
    )

    for manifest in sorted(configuration.manifests, key=lambda item: item.chain_id):
        for deployment in sorted(manifest.deployments, key=lambda item: (item.name, item.version)):
            values = {
                "id": deployment_id(manifest.chain_id, deployment.name, deployment.version),
                "chain_id": manifest.chain_id,
                "name": deployment.name,
                "address": deployment.address_bytes,
                "code_hash": deployment.code_hash_bytes,
                "version": deployment.version,
            }
            statement = insert(Deployment).values(**values)
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_deployments_chain_name_version",
                    set_={
                        "address": statement.excluded.address,
                        "code_hash": statement.excluded.code_hash,
                        "updated_at": func.now(),
                        "row_version": Deployment.row_version + 1,
                    },
                    where=or_(
                        Deployment.address.is_distinct_from(statement.excluded.address),
                        Deployment.code_hash.is_distinct_from(statement.excluded.code_hash),
                    ),
                )
            )

    stored = {
        (row.chain_id, row.address): row.decimals
        for row in await session.execute(select(Asset.chain_id, Asset.address, Asset.decimals))
    }
    for chain in sorted(configuration.chains, key=lambda item: item.chain_id):
        if not chain.enabled:
            continue
        for asset in chain.assets:
            if stored.get((chain.chain_id, asset.address_bytes)) != asset.decimals:
                await verify_asset_decimals(chain, asset, environ)
            values = {
                "id": asset_id(chain.chain_id, asset.address),
                "chain_id": chain.chain_id,
                "address": asset.address_bytes,
                "symbol": asset.symbol,
                "decimals": asset.decimals,
                "issuer_label": asset.issuer_label,
                "is_test": asset.is_test,
            }
            statement = insert(Asset).values(**values)
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_assets_chain_address",
                    set_={
                        **{key: statement.excluded[key] for key in ASSET_MUTABLE_COLUMNS},
                        "updated_at": func.now(),
                        "version": Asset.version + 1,
                    },
                    where=or_(
                        *(
                            Asset.__table__.c[key].is_distinct_from(statement.excluded[key])
                            for key in ASSET_MUTABLE_COLUMNS
                        )
                    ),
                )
            )

    await session.commit()
