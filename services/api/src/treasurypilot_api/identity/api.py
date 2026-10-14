from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import cast

from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from treasurypilot_api.identity.auth import (
    AuthFailure,
    AuthService,
    ProfileRecord,
    SessionAccess,
    UserRecord,
    auth_unavailable,
    normalize_email,
)
from treasurypilot_api.identity.oidc import (
    OIDCClient,
    OIDCFailure,
    decode_state,
    encode_state,
    new_state,
)
from treasurypilot_api.identity.oidc_repository import OIDCIdentityRepository
from treasurypilot_api.identity.wallets import SIWE_CHAIN_ID, WalletLinkService, WalletRepository

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
    owner_is_onchain: bool
    owner_checked_at: datetime | None
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


class SiweNonceResponse(ApiModel):
    nonce: str
    domain: str
    scheme: str
    chain_id: int
    expires_at: datetime


class LinkWalletRequest(ApiModel):
    message: str = Field(min_length=1, max_length=4096)
    signature: str = Field(min_length=1, max_length=4096)


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
                    owner_is_onchain=item.owner_is_onchain,
                    owner_checked_at=item.owner_checked_at,
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
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
    # Extensions first so they cannot overwrite the standard problem fields.
    content: dict[str, object] = {
        **exc.extensions,
        "type": f"https://treasurypilot.dev/problems/{exc.code.casefold()}",
        "title": exc.title,
        "status": exc.status,
        "code": exc.code,
        "detail": exc.detail,
        "instance": request.url.path,
    }
    return JSONResponse(
        status_code=exc.status,
        media_type="application/problem+json",
        headers=headers,
        content=content,
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _service(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if not isinstance(service, AuthService):
        raise auth_unavailable("Authentication is not configured.")
    return service


def _wallet_service(request: Request) -> WalletLinkService:
    repository = getattr(request.app.state, "wallet_repository", None)
    if not isinstance(repository, WalletRepository):
        raise AuthFailure(
            status=503,
            code="WALLET_VERIFICATION_UNAVAILABLE",
            title="Wallet verification unavailable",
            detail="Wallet linking is not configured.",
        )
    settings = request.app.state.settings
    return WalletLinkService(
        repository,
        allowed_origins=settings.cors_origin_list,
        platform_configuration=getattr(request.app.state, "platform_configuration", None),
    )


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


@router.get("/auth/siwe/nonce", response_model=SiweNonceResponse)
async def siwe_nonce(request: Request) -> SiweNonceResponse:
    access = await _authenticated(request)
    service = _wallet_service(request)
    challenge = await service.issue_nonce(
        user_id=access.user.id,
        origin=request.headers.get("origin"),
    )
    scheme, domain = service.origin_details(request.headers.get("origin"))
    return SiweNonceResponse(
        nonce=challenge.nonce,
        domain=domain,
        scheme=scheme,
        chain_id=SIWE_CHAIN_ID,
        expires_at=challenge.expires_at,
    )


@router.post("/me/wallets", status_code=201, response_model=WalletView)
async def link_wallet(payload: LinkWalletRequest, request: Request) -> WalletView:
    access = await _authenticated(request, require_csrf=True)
    linked = await _wallet_service(request).link_wallet(
        user_id=access.user.id,
        origin=request.headers.get("origin"),
        message_text=payload.message,
        signature=payload.signature,
    )
    return WalletView(
        address="0x" + linked.address.hex(),
        chain_family="evm",
        is_contract=linked.is_contract,
        linked_at=linked.linked_at,
    )


@router.delete("/me/wallets/{address}", status_code=204, response_class=Response)
async def unlink_wallet(address: str, request: Request) -> Response:
    access = await _authenticated(request, require_csrf=True)
    await _wallet_service(request).unlink_wallet(user_id=access.user.id, address=address)
    return Response(status_code=204)


@router.get("/auth/oidc/start", response_class=RedirectResponse)
async def oidc_start(request: Request) -> RedirectResponse:
    settings = request.app.state.settings
    if not settings.oidc_configured:
        raise AuthFailure(
            status=404,
            code="OIDC_NOT_CONFIGURED",
            title="SSO unavailable",
            detail="Enterprise sign-in is not configured.",
        )
    client = OIDCClient(
        issuer=settings.oidc_issuer or "",
        client_id=settings.oidc_client_id or "",
        client_secret=settings.oidc_client_secret.get_secret_value(),
        redirect_uri=settings.oidc_redirect_uri or "",
    )
    state = new_state()
    try:
        location = await client.authorization_url(state=state)
    except OIDCFailure:
        raise auth_unavailable("Enterprise sign-in is temporarily unavailable.") from None
    response = RedirectResponse(location, status_code=302)
    secret = _oidc_state_secret(settings)
    response.set_cookie(
        "tp_oidc_state",
        encode_state(state, secret),
        max_age=600,
        path="/v1/auth/oidc/callback",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/auth/oidc/callback", response_class=RedirectResponse)
async def oidc_callback(request: Request, code: str, state: str) -> RedirectResponse:
    settings = request.app.state.settings
    if not settings.oidc_configured:
        raise AuthFailure(
            status=404,
            code="OIDC_NOT_CONFIGURED",
            title="SSO unavailable",
            detail="Enterprise sign-in is not configured.",
        )
    try:
        oidc_state = decode_state(
            request.cookies.get("tp_oidc_state"), state, _oidc_state_secret(settings)
        )
        client = OIDCClient(
            issuer=settings.oidc_issuer or "",
            client_id=settings.oidc_client_id or "",
            client_secret=settings.oidc_client_secret.get_secret_value(),
            redirect_uri=settings.oidc_redirect_uri or "",
        )
        claims = await client.exchange(code=code, state=oidc_state)
        group_map = json.loads(settings.oidc_group_role_map)
        if not isinstance(group_map, dict) or any(
            not isinstance(group, str)
            or not isinstance(roles, list)
            or any(not isinstance(role, str) for role in roles)
            for group, roles in group_map.items()
        ):
            raise ValueError("invalid configured group role mapping")
        repository = getattr(request.app.state, "oidc_repository", None)
        if not isinstance(repository, OIDCIdentityRepository):
            raise OIDCFailure("OIDC provisioning is not configured")
        user = await repository.provision(
            issuer=settings.oidc_issuer or "",
            subject=claims.subject,
            email=claims.email,
            display_name=claims.display_name,
            organization_id=uuid.UUID(settings.oidc_organization_id or ""),
            groups=claims.groups,
            group_role_map={group: tuple(roles) for group, roles in group_map.items()},
        )
        verified = await _service(request).create_oidc_session(
            user=user,
            client_ip=_client_ip(request),
            user_agent=request.headers.get("user-agent", "unknown"),
        )
    except (OIDCFailure, ValueError):
        raise AuthFailure(
            status=401,
            code="OIDC_AUTHENTICATION_FAILED",
            title="Sign-in failed",
            detail="The identity provider could not authenticate this account.",
        ) from None
    settings = request.app.state.settings
    destination = settings.cors_origin_list[0] if settings.cors_origin_list else "/"
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie(
        settings.session_cookie_name,
        verified.session_token,
        max_age=300,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        verified.csrf_token,
        max_age=300,
        path="/",
        secure=True,
        httponly=False,
        samesite="lax",
    )
    response.delete_cookie(
        "tp_oidc_state",
        path="/v1/auth/oidc/callback",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return response


def _oidc_state_secret(settings: object) -> bytes:
    configured = getattr(settings, "session_secret", None)
    if configured is not None:
        return cast(str, configured.get_secret_value()).encode("utf-8")
    secret = getattr(settings, "oidc_client_secret", None)
    if secret is None:
        raise ValueError("OIDC state secret is not configured")
    return hashlib.sha256(cast(str, secret.get_secret_value()).encode("utf-8")).digest()


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
    if getattr(request.app.state, "wallet_repository", None) is not None:
        await _wallet_service(request).refresh_owner_statuses(user_id=access.user.id)
    return MeResponse.from_record(await _service(request).profile(access))
