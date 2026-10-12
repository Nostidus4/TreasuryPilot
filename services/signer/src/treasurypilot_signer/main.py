from fastapi import FastAPI
from pydantic import BaseModel

from treasurypilot_core.observability import configure_logging
from treasurypilot_signer import __version__
from treasurypilot_signer.config import get_settings
from treasurypilot_signer.middleware import CorrelationMiddleware


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging("signer", settings.log_level, settings.log_format)
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

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="signer", version=__version__)

    return app


app = create_app()
