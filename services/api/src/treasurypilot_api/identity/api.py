from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from treasurypilot_api.identity.auth import (
    AuthFailure,
    AuthService,
    ProfileRecord,
    SessionAccess,
    UserRecord,
    normalize_email,
)

_SIMPLE_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SESSION_MAX_AGE_SECONDS = 12 * 60 * 60


def _camel_case(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(word.capitalize() for word in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case, populate_by_name=True)


class MagicLinkRequest(ApiModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if not _SIMPLE_EMAIL.fullmatch(normalized):
            raise ValueError("invalid email address")
        return normalized


class VerifyMagicLinkRequest(ApiModel):
    # No schema limits: malformed or oversized bearer values reach the auth service
    # so callers always get the stable TOKEN_INVALID problem response, not a 422.
    token: str


class UserView(ApiModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    status: str

    @classmethod
    def from_record(cls, user: UserRecord) -> UserView:
        return cls(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            status=user.status,
        )


class MembershipView(ApiModel):
    id: uuid.UUID
    org_id: uuid.UUID
    roles: list[str]
    status: str
    signer_roles_active: bool


class WalletView(ApiModel):
    address: str
    chain_family: str
    is_contract: bool
    linked_at: datetime


class VerifyMagicLinkResponse(ApiModel):
    user: UserView
    # Also returned in the body because the tp_csrf cookie is host-only and is
    # unreadable from a web app served on a different origin than the API.
    csrf_token: str


class MeResponse(ApiModel):
    user: UserView
    memberships: list[MembershipView]
    wallets: list[WalletView]

    @classmethod
    def from_record(cls, profile: ProfileRecord) -> MeResponse:
        return cls(
            user=UserView.from_record(profile.user),
            memberships=[
                MembershipView(
                    id=item.id,
                    org_id=item.org_id,
                    roles=list(item.roles),
                    status=item.status,
                    signer_roles_active=item.signer_roles_active,
                )
                for item in profile.memberships
            ],
            wallets=[
                WalletView(
                    address=f"0x{item.address.hex()}",
                    chain_family=item.chain_family,
                    is_contract=item.is_contract,
                    linked_at=item.linked_at,
                )
                for item in profile.wallets
            ],
        )


def problem_response(request: Request, exc: AuthFailure) -> JSONResponse:
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


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _service(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if not isinstance(service, AuthService):
        raise AuthFailure(
            status=503,
            code="AUTH_UNAVAILABLE",
            title="Authentication unavailable",
            detail="Authentication is not configured.",
        )
    return service


def _session_cookie(request: Request) -> str | None:
    return request.cookies.get(request.app.state.settings.session_cookie_name)


async def _authenticated(request: Request, *, require_csrf: bool = False) -> SessionAccess:
    settings = request.app.state.settings
    return await _service(request).authenticate(
        session_token=_session_cookie(request),
        csrf_cookie=request.cookies.get(settings.csrf_cookie_name),
        csrf_header=request.headers.get(settings.csrf_header_name),
        require_csrf=require_csrf,
    )


router = APIRouter(prefix="/v1", tags=["identity"])


@router.post("/auth/magic-link", status_code=202, response_class=Response)
async def request_magic_link(
    payload: MagicLinkRequest, request: Request, background_tasks: BackgroundTasks
) -> Response:
    service = _service(request)
    await service.enforce_magic_link_limits(payload.email, client_ip=_client_ip(request))
    # Account lookup, DB writes, and email delivery all happen after the same 202
    # response, so known and unknown addresses follow the same request path.
    background_tasks.add_task(service.issue_and_deliver_magic_link, payload.email)
    return Response(status_code=202)


@router.post("/auth/magic-link/verify", response_model=VerifyMagicLinkResponse)
async def verify_magic_link(
    payload: VerifyMagicLinkRequest, request: Request, response: Response
) -> VerifyMagicLinkResponse:
    verified = await _service(request).verify_magic_link(
        token=payload.token,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent", "unknown"),
    )
    settings = request.app.state.settings
    response.set_cookie(
        settings.session_cookie_name,
        verified.session_token,
        max_age=SESSION_MAX_AGE_SECONDS,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        verified.csrf_token,
        max_age=SESSION_MAX_AGE_SECONDS,
        path="/",
        secure=True,
        httponly=False,
        samesite="lax",
    )
    return VerifyMagicLinkResponse(
        user=UserView.from_record(verified.user), csrf_token=verified.csrf_token
    )


def _clear_auth_cookies(request: Request, response: Response) -> None:
    settings = request.app.state.settings
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        settings.csrf_cookie_name,
        path="/",
        secure=True,
        httponly=False,
        samesite="lax",
    )


@router.post("/auth/logout", status_code=204, response_class=Response)
async def logout(request: Request) -> Response:
    settings = request.app.state.settings
    try:
        await _service(request).logout(
            session_token=_session_cookie(request),
            csrf_cookie=request.cookies.get(settings.csrf_cookie_name),
            csrf_header=request.headers.get(settings.csrf_header_name),
        )
    except AuthFailure as exc:
        if exc.status != 401:
            raise
        # The session is already expired or revoked: still drop the stale cookies.
        failure = problem_response(request, exc)
        _clear_auth_cookies(request, failure)
        return failure
    response = Response(status_code=204)
    _clear_auth_cookies(request, response)
    return response


@router.get("/me", response_model=MeResponse)
async def me(request: Request) -> MeResponse:
    access = await _authenticated(request)
    return MeResponse.from_record(await _service(request).profile(access))
