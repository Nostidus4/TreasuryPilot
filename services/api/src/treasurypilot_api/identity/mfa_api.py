"""MFA enrolment and step-up routes (IDN-L01). Sensitive routes check the step-up with
``require_role(..., step_up=True)``."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Response
from pydantic import Field, model_validator

from treasurypilot_api.identity.api import ApiModel, _authenticated, _require_unscoped, _service
from treasurypilot_api.identity.auth import SessionAccess
from treasurypilot_api.identity.mfa import (
    FactorRecord,
    MfaError,
    MfaService,
    b64u_decode,
    b64u_encode,
    mfa_failure,
)

router = APIRouter(prefix="/v1/me/mfa", tags=["mfa"])


class FactorView(ApiModel):
    id: str
    kind: str
    label: str
    created_at: datetime

    @classmethod
    def of(cls, factor: FactorRecord) -> FactorView:
        return cls(
            id=str(factor.id), kind=factor.kind, label=factor.label, created_at=factor.created_at
        )


class MfaStatus(ApiModel):
    factors: list[FactorView]
    recovery_codes_remaining: int


class EnrolmentResult(ApiModel):
    factor: FactorView
    # Shown once, only when this is the first factor (or after regeneration).
    recovery_codes: list[str]


class TotpStart(ApiModel):
    factor_id: str
    otpauth_uri: str


class LabelRequest(ApiModel):
    label: str = Field(default="Authenticator app", min_length=1, max_length=100)


class TotpConfirm(ApiModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class ChallengeRequest(ApiModel):
    purpose: Literal["register", "assert"]


class ChallengeResponse(ApiModel):
    challenge: str
    rp_id: str
    allow_credentials: list[str]


class WebAuthnRegistration(ApiModel):
    label: str = Field(default="Security key", min_length=1, max_length=100)
    client_data_json: str = Field(max_length=4096)
    attestation_object: str = Field(max_length=8192)


class WebAuthnAssertion(ApiModel):
    credential_id: str = Field(max_length=1400)
    client_data_json: str = Field(max_length=4096)
    authenticator_data: str = Field(max_length=2048)
    signature: str = Field(max_length=1024)


class StepUpRequest(ApiModel):
    code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")
    recovery_code: str | None = Field(default=None, max_length=32)
    webauthn: WebAuthnAssertion | None = None

    @model_validator(mode="after")
    def exactly_one(self) -> StepUpRequest:
        if sum(v is not None for v in (self.code, self.recovery_code, self.webauthn)) != 1:
            raise ValueError("provide exactly one of code, recoveryCode or webauthn")
        return self


def _mfa(request: Request) -> MfaService:
    service = getattr(request.app.state, "mfa_service", None)
    if not isinstance(service, MfaService):
        raise mfa_failure(503, "MFA_UNAVAILABLE", "Multi-factor authentication is not configured.")
    return service


def _relying_party(request: Request) -> tuple[str, str]:
    """(rpId, origin) from the browser's Origin header, which must be a configured web origin."""

    origin = request.headers.get("origin", "")
    if origin not in request.app.state.settings.cors_origin_list:
        raise mfa_failure(400, "MFA_ORIGIN_INVALID", "Unrecognised web origin.")
    return urlparse(origin).hostname or "", origin


async def _session(request: Request, *, enrolled_step_up: bool = False) -> SessionAccess:
    """Authenticate; adding, removing or resetting factors needs a fresh step-up once enrolled."""

    access = await _authenticated(request, require_csrf=request.method != "GET")
    _require_unscoped(access)
    if enrolled_step_up and await _mfa(request).factors(access.user.id):
        _service(request).require_step_up(access)
    return access


def _factor_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise mfa_failure(404, "MFA_FACTOR_NOT_FOUND", "No such second factor.") from None


def _decode(value: str) -> bytes:
    try:
        return b64u_decode(value)
    except MfaError:
        raise mfa_failure(400, "MFA_REQUEST_INVALID", "Malformed base64url value.") from None


@router.get("", response_model=MfaStatus)
async def mfa_status(request: Request) -> MfaStatus:
    access = await _session(request)
    service = _mfa(request)
    return MfaStatus(
        factors=[FactorView.of(f) for f in await service.factors(access.user.id)],
        recovery_codes_remaining=await service.recovery_codes_remaining(access.user.id),
    )


@router.post("/totp", response_model=TotpStart, status_code=201)
async def start_totp(payload: LabelRequest, request: Request) -> TotpStart:
    access = await _session(request, enrolled_step_up=True)
    factor, uri = await _mfa(request).start_totp(
        user_id=access.user.id, email=access.user.email, label=payload.label
    )
    return TotpStart(factor_id=str(factor.id), otpauth_uri=uri)


@router.post("/totp/{factor_id}/confirm", response_model=EnrolmentResult)
async def confirm_totp(factor_id: str, payload: TotpConfirm, request: Request) -> EnrolmentResult:
    # Once enrolled, a pending factor (possibly planted earlier) only counts after a fresh step-up.
    access = await _session(request, enrolled_step_up=True)
    factor, codes = await _mfa(request).confirm_totp(
        user_id=access.user.id,
        session_id=access.session_id,
        factor_id=_factor_id(factor_id),
        code=payload.code,
    )
    return EnrolmentResult(factor=FactorView.of(factor), recovery_codes=codes)


@router.post("/webauthn/challenge", response_model=ChallengeResponse)
async def webauthn_challenge(payload: ChallengeRequest, request: Request) -> ChallengeResponse:
    access = await _session(request, enrolled_step_up=payload.purpose == "register")
    service = _mfa(request)
    rp_id, _ = _relying_party(request)
    allowed = [
        b64u_encode(f.credential_id)
        for f in await service.factors(access.user.id)
        if f.credential_id is not None
    ]
    return ChallengeResponse(
        challenge=service.challenge(payload.purpose, access.user.id),
        rp_id=rp_id,
        allow_credentials=allowed if payload.purpose == "assert" else [],
    )


@router.post("/webauthn", response_model=EnrolmentResult, status_code=201)
async def register_webauthn(payload: WebAuthnRegistration, request: Request) -> EnrolmentResult:
    access = await _session(request, enrolled_step_up=True)
    rp_id, origin = _relying_party(request)
    factor, codes = await _mfa(request).register_webauthn(
        user_id=access.user.id,
        label=payload.label,
        rp_id=rp_id,
        origin=origin,
        client_data_json=_decode(payload.client_data_json),
        attestation_object=_decode(payload.attestation_object),
    )
    return EnrolmentResult(factor=FactorView.of(factor), recovery_codes=codes)


@router.post("/step-up", status_code=204, response_class=Response)
async def step_up(payload: StepUpRequest, request: Request) -> Response:
    access = await _session(request)
    assertion = None
    rp_id = origin = ""
    if payload.webauthn is not None:
        rp_id, origin = _relying_party(request)
        assertion = {
            "credential_id": _decode(payload.webauthn.credential_id),
            "client_data_json": _decode(payload.webauthn.client_data_json),
            "authenticator_data": _decode(payload.webauthn.authenticator_data),
            "signature": _decode(payload.webauthn.signature),
        }
    await _mfa(request).step_up(
        user_id=access.user.id,
        session_id=access.session_id,
        code=payload.code,
        recovery_code=payload.recovery_code,
        assertion=assertion,
        rp_id=rp_id,
        origin=origin,
    )
    return Response(status_code=204)


@router.post("/recovery-codes", response_model=list[str])
async def regenerate_recovery_codes(request: Request) -> list[str]:
    access = await _session(request, enrolled_step_up=True)
    service = _mfa(request)
    if not await service.factors(access.user.id):
        raise mfa_failure(409, "MFA_NOT_ENROLLED", "Enrol a second factor first.")
    return await service.regenerate_recovery_codes(access.user.id)


@router.delete("/{factor_id}", status_code=204, response_class=Response)
async def delete_factor(factor_id: str, request: Request) -> Response:
    access = await _session(request, enrolled_step_up=True)
    await _mfa(request).delete_factor(user_id=access.user.id, factor_id=_factor_id(factor_id))
    return Response(status_code=204)
