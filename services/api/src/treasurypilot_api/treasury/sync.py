from __future__ import annotations

import uuid

from sqlalchemy import func, or_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from treasurypilot_api.treasury.config import PlatformConfiguration
from treasurypilot_api.treasury.models import Chain, Deployment

DEPLOYMENT_ID_NAMESPACE = uuid.UUID("3c673901-8dd4-4fbb-89f2-74622778fb80")


def deployment_id(chain_id: int, name: str, version: str) -> uuid.UUID:
    """Return the stable primary key for a configured deployment."""

    return uuid.uuid5(DEPLOYMENT_ID_NAMESPACE, f"{chain_id}:{name}:{version}")


async def sync_platform_configuration(
    session: AsyncSession, configuration: PlatformConfiguration
) -> None:
    """Idempotently synchronize validated platform-owned configuration.

    Chains that are no longer configured are disabled rather than deleted so
    treasuries and deployments that reference them keep their history.
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

    await session.commit()
