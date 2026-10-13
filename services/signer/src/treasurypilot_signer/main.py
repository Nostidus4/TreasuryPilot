from fastapi import FastAPI
from pydantic import BaseModel

from treasurypilot_core.observability import CONTEXT_IDS, CorrelationMiddleware, configure_logging
from treasurypilot_signer import __version__


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


def create_app() -> FastAPI:
    configure_logging("signer")
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
    # Internal-only boundary: the worker's correlation ids are trusted as sent.
    app.add_middleware(CorrelationMiddleware, trusted_ids=CONTEXT_IDS)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="signer", version=__version__)

    return app


app = create_app()
