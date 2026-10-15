import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hmac import compare_digest

import asyncpg  # type: ignore[import-untyped]
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel

from treasurypilot_core.error_tracking import (
    configure_error_tracking,
)
from treasurypilot_core.observability import configure_logging
from treasurypilot_core.observability_asgi import (
    CorrelationMiddleware,
)
from treasurypilot_core.tracing import configure_tracing
from treasurypilot_signer import __version__
from treasurypilot_signer.config import Settings, get_settings
from treasurypilot_signer.keys import ExecutorKeys
from treasurypilot_signer.models import ErrorResponse, SignRequest
from treasurypilot_signer.rpc import JsonRpc
from treasurypilot_signer.service import SignerFault, SigningService
from treasurypilot_signer.store import SignerStore

logger = logging.getLogger(__name__)


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
        rpc: JsonRpc | None = None
        application.state.signing_service = signer_override
        database_url = settings.effective_database_url
        if signer_override is None and database_url and settings.chain_rpc_url:

            async def use_signer_role(connection: asyncpg.Connection) -> None:
                await connection.execute("SET ROLE treasurypilot_signer")

            key_store = ExecutorKeys(settings)
            key_store.validate()  # refuse to start on a missing keystore or wrong password
            pool = await asyncpg.create_pool(
                _database_dsn(database_url),
                min_size=1,
                max_size=4,
                timeout=5,
                command_timeout=5,
                init=use_signer_role,
            )
            rpc = JsonRpc(settings.chain_rpc_url)
            application.state.signing_service = SigningService(
                settings,
                SignerStore(pool),
                rpc,
                key_store.for_treasury,
            )
        elif signer_override is None:
            logger.error("signer is unconfigured: DATABASE_URL and CHAIN_RPC_URL are required")
        try:
            yield
        finally:
            if rpc is not None:
                await rpc.close()
            if pool is not None:
                await pool.close()

    app.router.lifespan_context = lifespan

    @app.get("/health", response_model=HealthResponse)
    async def health(request: Request) -> JSONResponse:
        configured = getattr(request.app.state, "signing_service", None) is not None
        body = HealthResponse(
            status="ok" if configured else "unconfigured", service="signer", version=__version__
        )
        return JSONResponse(status_code=200 if configured else 503, content=body.model_dump())

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
            x_signer_secret.encode("utf-8"), settings.signer_shared_secret.encode("utf-8")
        ):
            return JSONResponse(
                status_code=401, content=ErrorResponse(code="UNAUTHORIZED").model_dump()
            )
        signing_service: SigningService | None = getattr(request.app.state, "signing_service", None)
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
