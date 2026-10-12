import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from treasurypilot_api import __version__
from treasurypilot_api.config import Settings, get_settings
from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.api import router as identity_router
from treasurypilot_api.identity.auth import (
    AuthFailure,
    AuthRepository,
    AuthService,
    MagicLinkSender,
    SessionTokenCodec,
)
from treasurypilot_api.identity.email import ConsoleMagicLinkSender, ResendMagicLinkSender
from treasurypilot_api.identity.repository import SqlAlchemyAuthRepository


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


def _auth_service(settings: Settings) -> tuple[AuthService, AsyncEngine | None]:
    environment = settings.environment.casefold()
    console_delivery = environment in {"local", "test"}
    deployed = not console_delivery
    if deployed and not settings.database_url:
        raise ValueError("DATABASE_URL is required outside local/test environments")
    if deployed and not settings.session_secret:
        raise ValueError("TP_SESSION_SECRET is required outside local/test environments")
    if deployed and not settings.magic_link_base_url.startswith("https://"):
        raise ValueError("TP_MAGIC_LINK_BASE_URL must use HTTPS outside local/test environments")
    if deployed and (not settings.resend_api_key or not settings.resend_from_email):
        raise ValueError(
            "TP_RESEND_API_KEY and TP_RESEND_FROM_EMAIL are required outside local/test"
        )

    secret = (
        settings.session_secret.get_secret_value().encode("utf-8")
        if settings.session_secret
        else secrets.token_bytes(32)
    )
    if len(secret) < 32:
        raise ValueError("TP_SESSION_SECRET must contain at least 32 bytes")

    engine: AsyncEngine | None = None
    if settings.database_url:
        engine, sessions = create_session_factory(settings.database_url.get_secret_value())
        repository: AuthRepository = SqlAlchemyAuthRepository(sessions)
    else:
        repository = cast(AuthRepository, _UnavailableAuthRepository())

    sender: MagicLinkSender
    if console_delivery:
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
        ),
        engine,
    )


def create_app(
    *, settings: Settings | None = None, auth_service: AuthService | None = None
) -> FastAPI:
    settings = settings or get_settings()
    engine: AsyncEngine | None = None
    if auth_service is None:
        auth_service, engine = _auth_service(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        yield
        if engine is not None:
            await engine.dispose()

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
        return JSONResponse(
            status_code=exc.status,
            media_type="application/problem+json",
            content={
                "type": f"https://treasurypilot.dev/problems/{exc.code.casefold()}",
                "title": exc.title,
                "status": exc.status,
                "code": exc.code,
                "detail": exc.detail,
                "instance": request.url.path,
            },
        )

    app.include_router(identity_router)

    return app


app = create_app()
