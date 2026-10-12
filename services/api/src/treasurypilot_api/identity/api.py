from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from treasurypilot_api.identity.auth import (
    AuthFailure,
    AuthService,
    ProfileRecord,
    SessionAccess,
    UserRecord,
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
        normalized = value.strip().casefold()
        if not _SIMPLE_EMAIL.fullmatch(normalized):
            raise ValueError("invalid email address")
        return normalized


class VerifyMagicLinkRequest(ApiModel):
    # Let malformed bearer values reach the auth service so callers always get
    # the stable TOKEN_INVALID problem response instead of schema-dependent 422s.
    token: str = Field(max_length=256)


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


class WalletView(ApiModel):
    address: str
    chain_family: str
    is_contract: bool
    linked_at: datetime


class VerifyMagicLinkResponse(ApiModel):
    user: UserView


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
async def request_magic_link(payload: MagicLinkRequest, request: Request) -> Response:
    await _service(request).request_magic_link(payload.email)
    return Response(status_code=202)


@router.post("/auth/magic-link/verify", response_model=VerifyMagicLinkResponse)
async def verify_magic_link(
    payload: VerifyMagicLinkRequest, request: Request, response: Response
) -> VerifyMagicLinkResponse:
    client_ip = request.client.host if request.client is not None else "unknown"
    verified = await _service(request).verify_magic_link(
        token=payload.token,
        client_ip=client_ip,
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
    return VerifyMagicLinkResponse(user=UserView.from_record(verified.user))


@router.post("/auth/logout", status_code=204, response_class=Response)
async def logout(request: Request) -> Response:
    settings = request.app.state.settings
    session_token = _session_cookie(request)
    if session_token is None:
        await _authenticated(request, require_csrf=True)
        raise AssertionError("unreachable")
    await _service(request).logout(
        session_token=session_token,
        csrf_cookie=request.cookies.get(settings.csrf_cookie_name),
        csrf_header=request.headers.get(settings.csrf_header_name),
    )
    response = Response(status_code=204)
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
    return response


@router.get("/me", response_model=MeResponse)
async def me(request: Request) -> MeResponse:
    access = await _authenticated(request)
    return MeResponse.from_record(await _service(request).profile(access))
