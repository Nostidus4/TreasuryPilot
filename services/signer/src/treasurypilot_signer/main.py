from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hmac import compare_digest

import asyncpg  # type: ignore[import-untyped]
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel

from treasurypilot_core.error_tracking import (  # type: ignore[import-untyped]
    configure_error_tracking,
)
from treasurypilot_core.observability import configure_logging  # type: ignore[import-untyped]
from treasurypilot_core.observability_asgi import (  # type: ignore[import-untyped]
    CorrelationMiddleware,
)
from treasurypilot_core.tracing import configure_tracing  # type: ignore[import-untyped]
from treasurypilot_signer import __version__
from treasurypilot_signer.config import Settings, get_settings
from treasurypilot_signer.keys import ExecutorKeys
from treasurypilot_signer.models import ErrorResponse, SignRequest
from treasurypilot_signer.rpc import JsonRpc
from treasurypilot_signer.service import SignerFault, SigningService
from treasurypilot_signer.store import SignerStore


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


def _database_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def create_app(
    *, settings_override: Settings | None = None, signer_override: SigningService | None = None
) -> FastAPI:
    settings = settings_override or get_settings()
    configure_logging("signer", settings.log_level, settings.log_format)
    configure_tracing("signer")
    configure_error_tracking("signer")
    app = FastAPI(
        title="TreasuryPilot Signer",
        description="Internal-only transaction signing boundary for attested execution steps.",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.add_middleware(CorrelationMiddleware)
    FastAPIInstrumentor.instrument_app(app)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        pool: asyncpg.Pool | None = None
        application.state.signing_service = signer_override
        database_url = settings.effective_database_url
        if signer_override is None and database_url and settings.chain_rpc_url:

            async def use_signer_role(connection: asyncpg.Connection) -> None:
                await connection.execute("SET ROLE treasurypilot_signer")

            pool = await asyncpg.create_pool(
                _database_dsn(database_url),
                min_size=1,
                max_size=4,
                timeout=5,
                command_timeout=5,
                init=use_signer_role,
            )
            key_store = ExecutorKeys(settings)
            application.state.signing_service = SigningService(
                settings,
                SignerStore(pool),
                JsonRpc(settings.chain_rpc_url),
                key_store.for_treasury,
            )
        try:
            yield
        finally:
            if pool is not None:
                await pool.close()

    app.router.lifespan_context = lifespan

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="signer", version=__version__)

    @app.post("/sign-and-send", response_model=dict[str, str | int])
    async def sign_and_send(
        payload: SignRequest,
        request: Request,
        x_signer_secret: str | None = Header(default=None, alias="X-Signer-Secret"),
    ) -> JSONResponse:
        if not settings.signer_shared_secret:
            return JSONResponse(
                status_code=503,
                content=ErrorResponse(code="SIGNER_NOT_CONFIGURED").model_dump(),
            )
        if x_signer_secret is None or not compare_digest(
            x_signer_secret, settings.signer_shared_secret
        ):
            return JSONResponse(
                status_code=401, content=ErrorResponse(code="UNAUTHORIZED").model_dump()
            )
        signing_service: SigningService | None = request.app.state.signing_service
        if signing_service is None:
            return JSONResponse(
                status_code=503,
                content=ErrorResponse(code="SIGNER_NOT_CONFIGURED").model_dump(),
            )
        try:
            result = await signing_service.sign_and_send(payload)
        except SignerFault as error:
            return JSONResponse(
                status_code=error.status_code,
                content=ErrorResponse(code=error.code).model_dump(),
            )
        return JSONResponse(status_code=200, content=result.model_dump(by_alias=True))

    return app


app = create_app()
