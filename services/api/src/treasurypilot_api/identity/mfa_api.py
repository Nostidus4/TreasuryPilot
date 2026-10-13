from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import Field

from treasurypilot_api.identity.api import ApiModel, _authenticated
from treasurypilot_api.identity.auth import SessionAccess, auth_unavailable, utc_now
from treasurypilot_api.identity.mfa import MfaService
from treasurypilot_api.identity.webauthn import WebAuthnMfaService


class MfaCodeRequest(ApiModel):
    code: str = Field(min_length=6, max_length=24)


class TotpEnrollment(ApiModel):
    secret: str
    otpauth_uri: str


class TotpConfirmation(ApiModel):
    recovery_codes: list[str]


class StepUpResponse(ApiModel):
    expires_at: datetime


class WebAuthnChallengeResponse(ApiModel):
    challenge_id: uuid.UUID
    options: dict[str, Any]


class WebAuthnVerifyRequest(ApiModel):
    challenge_id: uuid.UUID
    credential: dict[str, Any]


router = APIRouter(prefix="/v1/me/mfa", tags=["identity"])


def _service(request: Request) -> MfaService:
    service = getattr(request.app.state, "mfa_service", None)
    if not isinstance(service, MfaService):
        raise auth_unavailable("Second-factor storage is not configured.")
    return service


def _webauthn_service(request: Request) -> WebAuthnMfaService:
    service = getattr(request.app.state, "webauthn_service", None)
    if not isinstance(service, WebAuthnMfaService):
        raise auth_unavailable("WebAuthn is not configured.")
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
        access.user.id, access.session_id, utc_now(), "TreasuryPilot"
    )
    response.headers["Cache-Control"] = "no-store"
    return TotpEnrollment(secret=secret, otpauth_uri=uri)


@router.post("/totp/confirm", response_model=TotpConfirmation)
async def confirm_totp_enrollment(
    payload: MfaCodeRequest, request: Request, response: Response
) -> TotpConfirmation:
    access = await _authenticated(request, require_csrf=True)
    codes = await _service(request).confirm_enrollment(
        access.user.id, access.session_id, payload.code, utc_now()
    )
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


@router.post("/webauthn/registration/options", response_model=WebAuthnChallengeResponse)
async def begin_webauthn_registration(
    request: Request, response: Response
) -> WebAuthnChallengeResponse:
    access = await _authenticated(request, require_csrf=True)
    challenge_id, options = await _webauthn_service(request).begin_registration(
        access.user.id, access.session_id, access.user.email, utc_now()
    )
    response.headers["Cache-Control"] = "no-store"
    return WebAuthnChallengeResponse(challenge_id=challenge_id, options=options)


@router.post("/webauthn/registration/verify", status_code=204, response_class=Response)
async def complete_webauthn_registration(
    payload: WebAuthnVerifyRequest, request: Request
) -> Response:
    access = await _authenticated(request, require_csrf=True)
    await _webauthn_service(request).complete_registration(
        access.user.id, access.session_id, payload.challenge_id, payload.credential, utc_now()
    )
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post("/webauthn/authentication/options", response_model=WebAuthnChallengeResponse)
async def begin_webauthn_authentication(
    request: Request, response: Response
) -> WebAuthnChallengeResponse:
    access = await _authenticated(request, require_csrf=True)
    challenge_id, options = await _webauthn_service(request).begin_authentication(
        access.user.id, access.session_id, utc_now()
    )
    response.headers["Cache-Control"] = "no-store"
    return WebAuthnChallengeResponse(challenge_id=challenge_id, options=options)


@router.post("/webauthn/authentication/verify", response_model=StepUpResponse)
async def complete_webauthn_authentication(
    payload: WebAuthnVerifyRequest, request: Request, response: Response
) -> StepUpResponse:
    access = await _authenticated(request, require_csrf=True)
    expires_at = await _webauthn_service(request).complete_authentication(
        access.user.id, access.session_id, payload.challenge_id, payload.credential, utc_now()
    )
    response.headers["Cache-Control"] = "no-store"
    return StepUpResponse(expires_at=expires_at)
