from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request, Response
from pydantic import Field

from treasurypilot_api.identity.api import ApiModel, _authenticated
from treasurypilot_api.identity.auth import SessionAccess, auth_unavailable, utc_now
from treasurypilot_api.identity.mfa import MfaService


class MfaCodeRequest(ApiModel):
    code: str = Field(min_length=6, max_length=24)


class TotpEnrollment(ApiModel):
    secret: str
    otpauth_uri: str


class TotpConfirmation(ApiModel):
    recovery_codes: list[str]


class StepUpResponse(ApiModel):
    expires_at: datetime


router = APIRouter(prefix="/v1/me/mfa", tags=["identity"])


def _service(request: Request) -> MfaService:
    service = getattr(request.app.state, "mfa_service", None)
    if not isinstance(service, MfaService):
        raise auth_unavailable("Second-factor storage is not configured.")
    return service


async def require_recent_mfa(request: Request) -> SessionAccess:
    """FastAPI dependency for future sensitive mutation handlers."""
    access = await _authenticated(request, require_csrf=True)
    await _service(request).require_fresh_step_up(access.user.id, access.session_id, utc_now())
    return access


@router.post("/totp/enrollment", response_model=TotpEnrollment)
async def begin_totp_enrollment(request: Request, response: Response) -> TotpEnrollment:
    access = await _authenticated(request, require_csrf=True)
    secret, uri = await _service(request).begin_enrollment(
        access.user.id, utc_now(), "TreasuryPilot"
    )
    response.headers["Cache-Control"] = "no-store"
    return TotpEnrollment(secret=secret, otpauth_uri=uri)


@router.post("/totp/confirm", response_model=TotpConfirmation)
async def confirm_totp_enrollment(
    payload: MfaCodeRequest, request: Request, response: Response
) -> TotpConfirmation:
    access = await _authenticated(request, require_csrf=True)
    codes = await _service(request).confirm_enrollment(access.user.id, payload.code, utc_now())
    response.headers["Cache-Control"] = "no-store"
    return TotpConfirmation(recovery_codes=codes)


@router.post("/step-up", response_model=StepUpResponse)
async def verify_step_up(
    payload: MfaCodeRequest, request: Request, response: Response
) -> StepUpResponse:
    access = await _authenticated(request, require_csrf=True)
    expires_at = await _service(request).verify_step_up(
        access.user.id, access.session_id, payload.code, utc_now()
    )
    response.headers["Cache-Control"] = "no-store"
    return StepUpResponse(expires_at=expires_at)
