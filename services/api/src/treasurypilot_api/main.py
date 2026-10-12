from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from treasurypilot_api import __version__
from treasurypilot_api.config import get_settings
from treasurypilot_api.middleware import CorrelationMiddleware
from treasurypilot_core.observability import configure_logging


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging("api", settings.log_level, settings.log_format)
    app = FastAPI(
        title="TreasuryPilot API",
        summary="Human-authorized, policy-enforced treasury operations.",
        version=__version__,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(CorrelationMiddleware)

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    @app.get("/v1/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="api", version=__version__)

    return app


app = create_app()
