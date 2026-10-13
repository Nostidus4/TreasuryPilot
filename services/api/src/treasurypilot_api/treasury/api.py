from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from treasurypilot_api.identity.api import ApiModel, _authenticated
from treasurypilot_api.treasury.config import PlatformConfiguration
from treasurypilot_api.treasury.sync import asset_id


class AssetView(ApiModel):
    id: uuid.UUID
    symbol: str
    decimals: int
    address: str
    is_test: bool


class ChainView(ApiModel):
    chain_id: int
    name: str
    explorer_url: str
    assets: list[AssetView]


class ChainsResponse(ApiModel):
    chains: list[ChainView]


router = APIRouter(prefix="/v1", tags=["treasury"])


@router.get("/chains", response_model=ChainsResponse)
async def list_chains(request: Request) -> ChainsResponse:
    await _authenticated(request)
    # Served from the startup configuration: config is read-only at runtime (M02-D8)
    # and startup fails unless every asset was synced with verified decimals.
    configuration: PlatformConfiguration = request.app.state.platform_configuration
    return ChainsResponse(
        chains=[
            ChainView(
                chain_id=chain.chain_id,
                name=chain.name,
                explorer_url=str(chain.explorer_url),
                assets=[
                    AssetView(
                        id=asset_id(chain.chain_id, asset.address),
                        symbol=asset.symbol,
                        decimals=asset.decimals,
                        address=asset.address,
                        is_test=asset.is_test,
                    )
                    for asset in chain.assets
                ],
            )
            for chain in configuration.chains
            if chain.enabled
        ]
    )
