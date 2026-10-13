from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel

from treasurypilot_core.error_tracking import configure_error_tracking
from treasurypilot_core.observability import configure_logging
from treasurypilot_core.observability_asgi import CorrelationMiddleware
from treasurypilot_core.tracing import configure_tracing
from treasurypilot_signer import __version__
from treasurypilot_signer.config import get_settings


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging("signer", settings.log_level, settings.log_format)
    configure_tracing("signer")
    configure_error_tracking("signer")
    app = FastAPI(
        title="TreasuryPilot Signer",
        description=(
            "Internal-only signing boundary. Transaction signing is intentionally unavailable "
            "until EXE-005 implements attestation verification and simulation."
        ),
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.add_middleware(CorrelationMiddleware)
    FastAPIInstrumentor.instrument_app(app)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="signer", version=__version__)

    return app


app = create_app()
