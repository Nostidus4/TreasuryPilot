from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from treasurypilot_api import __version__
from treasurypilot_api.config import Settings, get_settings
from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.api import problem_response
from treasurypilot_api.identity.api import router as identity_router
from treasurypilot_api.identity.auth import (
    AuthFailure,
    AuthRepository,
    AuthService,
    MagicLinkSender,
    SessionTokenCodec,
    utc_now,
)
from treasurypilot_api.identity.email import ConsoleMagicLinkSender, ResendMagicLinkSender
from treasurypilot_api.identity.organizations import (
    OrganizationRepository,
    SqlAlchemyOrganizationRepository,
)
from treasurypilot_api.identity.organizations import (
    router as organizations_router,
)
from treasurypilot_api.identity.rate_limit import (
    MemoryRateLimiter,
    RateLimiter,
    RedisRateLimiter,
)
from treasurypilot_api.identity.repository import SqlAlchemyAuthRepository
from treasurypilot_api.mandate.routes import (
    MandateRepository,
    SqlAlchemyMandateRepository,
)
from treasurypilot_api.mandate.routes import (
    router as mandate_router,
)
from treasurypilot_api.treasury.config import PlatformConfiguration, PlatformConfigurationError
from treasurypilot_api.treasury.sync import sync_platform_configuration

# Fixed so every local process (``--workers``, ``--reload``) verifies the same
# cookies. Only ever used when TP_ENVIRONMENT=local.
LOCAL_SESSION_SECRET = b"treasurypilot-local-development-only-session-secret"


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class _UnavailableAuthRepository:
    def __getattr__(self, name: str) -> object:
        async def unavailable(*args: object, **kwargs: object) -> None:
            raise AuthFailure(
                status=503,
                code="AUTH_UNAVAILABLE",
                title="Authentication unavailable",
                detail="Authentication storage is not configured.",
            )

        return unavailable


def _auth_service(
    settings: Settings,
) -> tuple[
    AuthService,
    AsyncEngine | None,
    RedisRateLimiter | None,
    OrganizationRepository | None,
]:
    # Only an explicit local environment relaxes the deployment checks; any other
    # value (including a shared "test" or QA env) is treated as deployed.
    local = settings.environment.casefold() == "local"
    deployed = not local
    if deployed and not settings.database_url:
        raise ValueError("DATABASE_URL is required outside the local environment")
    if deployed and not settings.session_secret:
        raise ValueError("TP_SESSION_SECRET is required outside the local environment")
    if deployed and not settings.magic_link_base_url.startswith("https://"):
        raise ValueError("TP_MAGIC_LINK_BASE_URL must use HTTPS outside the local environment")
    if deployed and (not settings.resend_api_key or not settings.resend_from_email):
        raise ValueError(
            "TP_RESEND_API_KEY and TP_RESEND_FROM_EMAIL are required outside the local environment"
        )
    if deployed and not settings.redis_url:
        raise ValueError("TP_REDIS_URL is required outside the local environment")

    secret = (
        settings.session_secret.get_secret_value().encode("utf-8")
        if settings.session_secret
        else LOCAL_SESSION_SECRET
    )
    if len(secret) < 32:
        raise ValueError("TP_SESSION_SECRET must contain at least 32 bytes")

    engine: AsyncEngine | None = None
    organization_repository: OrganizationRepository | None = None
    if settings.database_url:
        engine, sessions = create_session_factory(settings.database_url.get_secret_value())
        repository: AuthRepository = SqlAlchemyAuthRepository(sessions)
        organization_repository = SqlAlchemyOrganizationRepository(sessions)
    else:
        repository = cast(AuthRepository, _UnavailableAuthRepository())

    redis_limiter: RedisRateLimiter | None = None
    rate_limiter: RateLimiter
    if settings.redis_url:
        redis_limiter = RedisRateLimiter(Redis.from_url(settings.redis_url.get_secret_value()))
        rate_limiter = redis_limiter
    else:
        rate_limiter = MemoryRateLimiter(utc_now)

    sender: MagicLinkSender
    if local:
        sender = ConsoleMagicLinkSender()
    else:
        # The deployed validation above guarantees both values are available.
        assert settings.resend_api_key is not None
        assert settings.resend_from_email is not None
        sender = ResendMagicLinkSender(
            api_key=settings.resend_api_key.get_secret_value(),
            from_email=settings.resend_from_email,
        )
    return (
        AuthService(
            repository=repository,
            sender=sender,
            token_codec=SessionTokenCodec(secret),
            client_hash_secret=secret,
            magic_link_base_url=settings.magic_link_base_url,
            rate_limiter=rate_limiter,
        ),
        engine,
        redis_limiter,
        organization_repository,
    )


def create_app(
    *,
    settings: Settings | None = None,
    auth_service: AuthService | None = None,
    organization_repository: OrganizationRepository | None = None,
    mandate_repository: MandateRepository | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    engine: AsyncEngine | None = None
    redis_limiter: RedisRateLimiter | None = None
    if auth_service is None:
        auth_service, engine, redis_limiter, default_organizations = _auth_service(settings)
        if organization_repository is None:
            organization_repository = default_organizations
    if mandate_repository is None and engine is not None:
        mandate_repository = SqlAlchemyMandateRepository(
            async_sessionmaker(engine, expire_on_commit=False)
        )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configuration = PlatformConfiguration.load(
            settings.platform_chain_config_path,
            settings.deployments_dir,
        )
        application.state.platform_configuration = configuration
        if settings.database_url is None:
            if configuration.chains:
                raise PlatformConfigurationError(
                    "DATABASE_URL is required when platform chains are configured"
                )
        else:
            # Sync even an empty chain list so removed chains get disabled. The
            # engine only serves this one-time sync, so release it before serving.
            sync_engine = create_async_engine(settings.database_url.get_secret_value())
            try:
                session_factory = async_sessionmaker(sync_engine, expire_on_commit=False)
                async with session_factory() as session:
                    await sync_platform_configuration(session, configuration)
            finally:
                await sync_engine.dispose()
        yield
        if engine is not None:
            await engine.dispose()
        if redis_limiter is not None:
            await redis_limiter.aclose()

    app = FastAPI(
        title="TreasuryPilot API",
        summary="Human-authorized, policy-enforced treasury operations.",
        version=__version__,
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.auth_service = auth_service
    app.state.organization_repository = organization_repository
    app.state.mandate_repository = mandate_repository
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

    @app.exception_handler(AuthFailure)
    async def auth_failure_handler(request: Request, exc: AuthFailure) -> JSONResponse:
        return problem_response(request, exc)

    app.include_router(identity_router)
    app.include_router(organizations_router)
    app.include_router(mandate_router)

    return app


app = create_app()
