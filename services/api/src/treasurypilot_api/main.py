from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from treasurypilot_api import __version__
from treasurypilot_api.config import get_settings
from treasurypilot_api.treasury.config import PlatformConfiguration, PlatformConfigurationError
from treasurypilot_api.treasury.sync import sync_platform_configuration


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configuration = PlatformConfiguration.load(
            settings.platform_chain_config_path,
            settings.deployments_dir,
        )
        application.state.platform_configuration = configuration
        if not configuration.chains:
            yield
            return
        if settings.database_url is None:
            raise PlatformConfigurationError(
                "DATABASE_URL is required when platform chains are configured"
            )

        engine = create_async_engine(settings.database_url)
        try:
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with session_factory() as session:
                await sync_platform_configuration(session, configuration)
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="TreasuryPilot API",
        summary="Human-authorized, policy-enforced treasury operations.",
        version=__version__,
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    @app.get("/v1/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="api", version=__version__)

    return app


app = create_app()
