from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from treasurypilot_api import __version__
from treasurypilot_api.admin.api import create_admin_router, create_support_grant_router
from treasurypilot_api.audit.api import AuditRepository, SqlAlchemyAuditRepository
from treasurypilot_api.audit.api import router as audit_router
from treasurypilot_api.audit.evidence import EvidenceRepository
from treasurypilot_api.audit.evidence_repository import SqlAlchemyEvidenceRepository
from treasurypilot_api.chain.routes import TokenMovementRepository
from treasurypilot_api.chain.routes import router as chain_router
from treasurypilot_api.compliance.kyb import KybService, build_kyb_service
from treasurypilot_api.compliance.screening import ScreeningService, build_screening_service
from treasurypilot_api.compliance.travel_rule import TravelRuleService, build_travel_rule_service
from treasurypilot_api.config import Settings, get_settings
from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.api import problem_response
from treasurypilot_api.identity.api import router as identity_router
from treasurypilot_api.identity.auth import (
    AuthFailure,
    AuthRepository,
    AuthService,
    MagicLinkSender,
    SessionTokenCodec,
    auth_unavailable,
    utc_now,
)
from treasurypilot_api.identity.email import ConsoleMagicLinkSender, ResendMagicLinkSender
from treasurypilot_api.identity.memberships import (
    MembershipRepository,
    SqlAlchemyMembershipRepository,
)
from treasurypilot_api.identity.memberships import router as memberships_router
from treasurypilot_api.identity.mfa import MfaService
from treasurypilot_api.identity.mfa_api import router as mfa_router
from treasurypilot_api.identity.mfa_repository import SqlAlchemyMfaRepository
from treasurypilot_api.identity.oidc_repository import OIDCIdentityRepository
from treasurypilot_api.identity.organizations import (
    OrganizationRepository,
    SqlAlchemyOrganizationRepository,
)
from treasurypilot_api.identity.organizations import (
    router as organizations_router,
)
from treasurypilot_api.identity.rate_limit import (
    MemoryRateLimiter,
    RateLimiter,
    RedisRateLimiter,
)
from treasurypilot_api.identity.repository import SqlAlchemyAuthRepository
from treasurypilot_api.identity.wallets import WalletRepository
from treasurypilot_api.invoices.api_keys import router as invoice_api_keys_router
from treasurypilot_api.invoices.documents import (
    ExtractionQueue,
    ObjectStorage,
    build_document_storage,
    build_extraction_queue,
)
from treasurypilot_api.invoices.documents import router as invoice_documents_router
from treasurypilot_api.invoices.fx import FxQuoteProvider
from treasurypilot_api.invoices.recurring import router as recurring_schedules_router
from treasurypilot_api.invoices.requests import router as requests_router
from treasurypilot_api.mandate.api import router as governance_router
from treasurypilot_api.mandate.exceptions import router as mandate_exceptions_router
from treasurypilot_api.mandate.fees import FeeHistoryProvider
from treasurypilot_api.mandate.fees import router as fee_router
from treasurypilot_api.mandate.governance_service import GovernanceService
from treasurypilot_api.mandate.payees import PayeeRepository, SqlAlchemyPayeeRepository
from treasurypilot_api.mandate.payees import router as payees_router
from treasurypilot_api.mandate.routes import (
    MandateRepository,
    SqlAlchemyMandateRepository,
)
from treasurypilot_api.mandate.routes import router as mandate_router
from treasurypilot_api.mandate.vendors import (
    FieldCipher,
    SqlAlchemyVendorRepository,
    VendorRepository,
)
from treasurypilot_api.mandate.vendors import router as vendors_router
from treasurypilot_api.notifications.preferences import (
    NotificationPreferencesRepository,
    SqlAlchemyNotificationPreferencesRepository,
)
from treasurypilot_api.notifications.preferences import router as notification_preferences_router
from treasurypilot_api.notifications.routes import (
    NotificationRepository,
    SqlAlchemyNotificationRepository,
)
from treasurypilot_api.notifications.routes import email_router as notification_email_router
from treasurypilot_api.notifications.routes import router as notifications_router
from treasurypilot_api.notifications.telegram import (
    SqlAlchemyTelegramRepository,
    TelegramRepository,
)
from treasurypilot_api.notifications.telegram import router as telegram_router
from treasurypilot_api.notifications.webhook_api import router as webhook_router
from treasurypilot_api.recovery.routes import router as review_router
from treasurypilot_api.treasury.api import router as treasury_router
from treasurypilot_api.treasury.config import PlatformConfiguration, PlatformConfigurationError
from treasurypilot_api.treasury.safe import RpcSafeVerifier
from treasurypilot_api.treasury.service import TreasuryService
from treasurypilot_api.treasury.sync import sync_platform_configuration
from treasurypilot_core.domain import FxPolicy
from treasurypilot_core.error_tracking import configure_error_tracking
from treasurypilot_core.observability import REQUEST_ID_HEADER, configure_logging
from treasurypilot_core.observability_asgi import CorrelationMiddleware
from treasurypilot_core.privacy import EncryptionConfigurationError, FieldEncryptionKey
from treasurypilot_core.privacy import FieldCipher as CoreFieldCipher
from treasurypilot_core.tracing import configure_tracing

# Fixed so every local process (``--workers``, ``--reload``) verifies the same
# cookies. Only ever used when TP_ENVIRONMENT=local.
LOCAL_SESSION_SECRET = b"treasurypilot-local-development-only-session-secret"


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class _UnavailableAuthRepository:
    def __getattr__(self, name: str) -> object:
        async def unavailable(*args: object, **kwargs: object) -> None:
            raise auth_unavailable("Authentication storage is not configured.")

        return unavailable


def _auth_service(
    settings: Settings,
) -> tuple[
    AuthService,
    AsyncEngine | None,
    RedisRateLimiter | None,
    OrganizationRepository | None,
    WalletRepository | None,
    AuditRepository | None,
    async_sessionmaker[AsyncSession] | None,
    RateLimiter,
]:
    # Only an explicit local environment relaxes the deployment checks; any other
    # value (including a shared "test" or QA env) is treated as deployed.
    local = settings.environment.casefold() == "local"
    deployed = not local
    if deployed and not settings.database_url:
        raise ValueError("DATABASE_URL is required outside the local environment")
    if deployed and not settings.session_secret:
        raise ValueError("TP_SESSION_SECRET is required outside the local environment")
    if deployed and not settings.magic_link_base_url.startswith("https://"):
        raise ValueError("TP_MAGIC_LINK_BASE_URL must use HTTPS outside the local environment")
    if deployed and (not settings.resend_api_key or not settings.resend_from_email):
        raise ValueError(
            "TP_RESEND_API_KEY and TP_RESEND_FROM_EMAIL are required outside the local environment"
        )
    if deployed and not settings.redis_url:
        raise ValueError("TP_REDIS_URL is required outside the local environment")

    secret = (
        settings.session_secret.get_secret_value().encode("utf-8")
        if settings.session_secret
        else LOCAL_SESSION_SECRET
    )
    if len(secret) < 32:
        raise ValueError("TP_SESSION_SECRET must contain at least 32 bytes")

    engine: AsyncEngine | None = None
    organization_repository: OrganizationRepository | None = None
    wallet_repository: WalletRepository | None = None
    audit_repository: AuditRepository | None = None
    sessions: async_sessionmaker[AsyncSession] | None = None
    if settings.database_url:
        engine, sessions = create_session_factory(settings.database_url.get_secret_value())
        repository: AuthRepository = SqlAlchemyAuthRepository(sessions)
        organization_repository = SqlAlchemyOrganizationRepository(sessions)
        wallet_repository = WalletRepository(sessions)
        audit_repository = SqlAlchemyAuditRepository(sessions)
    else:
        repository = cast(AuthRepository, _UnavailableAuthRepository())

    redis_limiter: RedisRateLimiter | None = None
    rate_limiter: RateLimiter
    if settings.redis_url:
        redis_limiter = RedisRateLimiter(Redis.from_url(settings.redis_url.get_secret_value()))
        rate_limiter = redis_limiter
    else:
        rate_limiter = MemoryRateLimiter(utc_now)

    sender: MagicLinkSender
    if local:
        sender = ConsoleMagicLinkSender()
    else:
        # The deployed validation above guarantees both values are available.
        assert settings.resend_api_key is not None
        assert settings.resend_from_email is not None
        sender = ResendMagicLinkSender(
            api_key=settings.resend_api_key.get_secret_value(),
            from_email=settings.resend_from_email,
        )
    return (
        AuthService(
            repository=repository,
            sender=sender,
            token_codec=SessionTokenCodec(secret),
            client_hash_secret=secret,
            magic_link_base_url=settings.magic_link_base_url,
            rate_limiter=rate_limiter,
        ),
        engine,
        redis_limiter,
        organization_repository,
        wallet_repository,
        audit_repository,
        sessions,
        rate_limiter,
    )


def create_app(
    *,
    settings: Settings | None = None,
    auth_service: AuthService | None = None,
    rate_limiter: RateLimiter | None = None,
    organization_repository: OrganizationRepository | None = None,
    wallet_repository: WalletRepository | None = None,
    audit_repository: AuditRepository | None = None,
    admin_sessions: async_sessionmaker[AsyncSession] | None = None,
    screening_service: ScreeningService | None = None,
    kyb_service: KybService | None = None,
    travel_rule_service: TravelRuleService | None = None,
    vendor_repository: VendorRepository | None = None,
    payee_repository: PayeeRepository | None = None,
    field_cipher: FieldCipher | None = None,
    mandate_repository: MandateRepository | None = None,
    treasury_service: TreasuryService | None = None,
    governance_service: GovernanceService | None = None,
    membership_repository: MembershipRepository | None = None,
    evidence_repository: EvidenceRepository | None = None,
    notification_repository: NotificationRepository | None = None,
    notification_preferences_repository: NotificationPreferencesRepository | None = None,
    document_storage: ObjectStorage | None = None,
    extraction_queue: ExtractionQueue | None = None,
    fx_quote_provider: FxQuoteProvider | None = None,
    fee_history_provider: FeeHistoryProvider | None = None,
    telegram_repository: TelegramRepository | None = None,
    mfa_service: MfaService | None = None,
    token_movement_repository: TokenMovementRepository | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging("api", settings.log_level, settings.log_format)
    configure_tracing("api")
    # Before any engine exists: SQLAlchemy is traced by wrapping engine creation.
    if not SQLAlchemyInstrumentor().is_instrumented_by_opentelemetry:
        SQLAlchemyInstrumentor().instrument()
    configure_error_tracking("api")
    engine: AsyncEngine | None = None
    admin_engine: AsyncEngine | None = None
    if admin_sessions is None and settings.admin_configured and settings.database_url is not None:
        admin_engine, admin_sessions = create_session_factory(
            settings.database_url.get_secret_value()
        )
    redis_limiter: RedisRateLimiter | None = None
    sessions: async_sessionmaker[AsyncSession] | None = None
    if auth_service is None:
        (
            auth_service,
            engine,
            redis_limiter,
            default_organizations,
            default_wallets,
            default_audit,
            sessions,
            rate_limiter,
        ) = _auth_service(settings)
        if organization_repository is None:
            organization_repository = default_organizations
        if wallet_repository is None:
            wallet_repository = default_wallets
        if audit_repository is None:
            audit_repository = default_audit
    if evidence_repository is None and sessions is not None:
        evidence_repository = SqlAlchemyEvidenceRepository(sessions)
    if rate_limiter is None:
        raise ValueError("rate_limiter is required when auth_service is injected")
    if screening_service is None and engine is not None:
        screening_service = build_screening_service(
            settings.environment, async_sessionmaker(engine, expire_on_commit=False)
        )
    if kyb_service is None and engine is not None:
        kyb_service = build_kyb_service(
            settings.environment, async_sessionmaker(engine, expire_on_commit=False)
        )
    # One field cipher shared by every service; a missing key makes each of them fail closed.
    core_cipher: CoreFieldCipher | None = None
    if engine is not None or sessions is not None:
        try:
            core_cipher = CoreFieldCipher(FieldEncryptionKey.from_environment())
        except EncryptionConfigurationError:
            core_cipher = None
    if travel_rule_service is None and engine is not None:
        travel_rule_service = build_travel_rule_service(
            settings.environment,
            async_sessionmaker(engine, expire_on_commit=False),
            thresholds_json=settings.travel_rule_thresholds,
            cipher=core_cipher,
        )

    if mandate_repository is None and engine is not None:
        mandate_repository = SqlAlchemyMandateRepository(
            async_sessionmaker(engine, expire_on_commit=False)
        )

    if membership_repository is None and engine is not None:
        membership_repository = SqlAlchemyMembershipRepository(
            async_sessionmaker(engine, expire_on_commit=False)
        )
    if notification_repository is None and engine is not None:
        notification_repository = SqlAlchemyNotificationRepository(
            async_sessionmaker(engine, expire_on_commit=False)
        )
    if telegram_repository is None and engine is not None:
        # Without a field key, linking reports TELEGRAM_UNAVAILABLE; nothing else is affected.
        chat_hash_key = settings.telegram_chat_hash_key
        telegram_repository = SqlAlchemyTelegramRepository(
            async_sessionmaker(engine, expire_on_commit=False),
            cipher=core_cipher,
            # A dedicated, rotation-independent key: changing it would let one chat
            # link to a second account (see the uniqueness hash in telegram.py).
            hash_key=chat_hash_key.get_secret_value().encode() if chat_hash_key else None,
        )
    if vendor_repository is None and sessions is not None:
        vendor_repository = SqlAlchemyVendorRepository(sessions)
    if payee_repository is None and sessions is not None:
        payee_repository = SqlAlchemyPayeeRepository(sessions)
    if notification_preferences_repository is None and sessions is not None:
        notification_preferences_repository = SqlAlchemyNotificationPreferencesRepository(sessions)

    if mfa_service is None and sessions is not None:
        # Without a field key TOTP enrolment reports MFA_UNAVAILABLE; WebAuthn still works.
        mfa_service = MfaService(
            repository=SqlAlchemyMfaRepository(sessions),
            cipher=core_cipher,
            secret=settings.session_secret.get_secret_value().encode()
            if settings.session_secret
            else LOCAL_SESSION_SECRET,
            rate_limiter=rate_limiter,
        )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configuration = PlatformConfiguration.load(
            settings.platform_chain_config_path,
            settings.deployments_dir,
        )
        application.state.platform_configuration = configuration
        if application.state.fee_history_provider is None:
            application.state.fee_history_provider = RpcSafeVerifier(configuration)
        if application.state.treasury_service is None and sessions is not None:
            application.state.treasury_service = TreasuryService(
                sessions, RpcSafeVerifier(configuration), configuration
            )
        if application.state.governance_service is None and sessions is not None:
            application.state.governance_service = GovernanceService(
                sessions,
                RpcSafeVerifier(configuration),
                configuration,
                kyb_service=application.state.kyb_service,
            )
        if settings.database_url is None:
            if configuration.chains:
                raise PlatformConfigurationError(
                    "DATABASE_URL is required when platform chains are configured"
                )
        else:
            # Sync even an empty chain list so removed chains get disabled. The
            # engine only serves this one-time sync, so release it before serving.
            sync_engine, session_factory = create_session_factory(
                settings.database_url.get_secret_value()
            )
            try:
                async with session_factory() as session:
                    await sync_platform_configuration(session, configuration)
            finally:
                await sync_engine.dispose()
        yield
        if engine is not None:
            await engine.dispose()
        if admin_engine is not None:
            await admin_engine.dispose()
        if redis_limiter is not None:
            await redis_limiter.aclose()

    app = FastAPI(
        title="TreasuryPilot API",
        summary="Human-authorized, policy-enforced treasury operations.",
        version=__version__,
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.auth_service = auth_service
    app.state.api_key_rate_limiter = rate_limiter
    app.state.organization_repository = organization_repository
    app.state.oidc_repository = (
        OIDCIdentityRepository(sessions)
        if settings.oidc_configured and sessions is not None
        else None
    )
    app.state.wallet_repository = wallet_repository
    app.state.audit_repository = audit_repository
    app.state.screening_service = screening_service
    app.state.kyb_service = kyb_service
    app.state.travel_rule_service = travel_rule_service
    app.state.vendor_repository = vendor_repository
    app.state.payee_repository = payee_repository
    app.state.field_cipher = field_cipher
    app.state.mandate_repository = mandate_repository
    app.state.review_sessions = (
        async_sessionmaker(engine, expire_on_commit=False) if engine is not None else None
    )
    app.state.treasury_service = treasury_service
    app.state.fee_history_provider = fee_history_provider
    app.state.governance_service = governance_service
    app.state.membership_repository = membership_repository
    app.state.evidence_repository = evidence_repository
    app.state.notification_repository = notification_repository
    app.state.request_sessions = sessions
    app.state.token_movement_repository = token_movement_repository
    app.state.notification_preferences_repository = notification_preferences_repository
    app.state.document_storage = document_storage or build_document_storage(settings)
    app.state.extraction_queue = extraction_queue or build_extraction_queue(settings)
    # Fiat requests need a provider plus an owner-configured policy and tolerance; without all
    # three they respond 503 FX_UNAVAILABLE.
    app.state.fx_quote_provider = fx_quote_provider
    app.state.fx_tolerance_bps = settings.fx_tolerance_bps
    app.state.fx_policy = (
        FxPolicy(
            source_id=settings.fx_source_id,
            max_quote_age_seconds=settings.fx_max_quote_age_seconds,
            depeg_threshold_bps=settings.fx_depeg_threshold_bps,
        )
        if settings.fx_source_id
        else None
    )
    app.state.telegram_repository = telegram_repository
    app.state.mfa_service = mfa_service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # Retry-After is not CORS-safelisted; the SPA needs it for 429/503 backoff.
        expose_headers=[REQUEST_ID_HEADER, "Retry-After"],
    )

    app.add_middleware(CorrelationMiddleware)
    FastAPIInstrumentor.instrument_app(app)

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    @app.get("/v1/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="api", version=__version__)

    @app.exception_handler(AuthFailure)
    async def auth_failure_handler(request: Request, exc: AuthFailure) -> JSONResponse:
        return problem_response(request, exc)

    app.include_router(identity_router)
    app.include_router(mfa_router)
    app.include_router(organizations_router)
    app.include_router(memberships_router)
    app.include_router(audit_router)
    app.include_router(treasury_router)
    app.include_router(chain_router)
    app.include_router(governance_router)
    app.include_router(mandate_exceptions_router)
    app.include_router(fee_router)
    app.include_router(create_admin_router(settings, admin_sessions))
    app.include_router(create_support_grant_router(sessions or admin_sessions))
    app.include_router(mandate_router)
    app.include_router(vendors_router)
    app.include_router(payees_router)
    app.include_router(review_router)
    app.include_router(notifications_router)
    app.include_router(webhook_router)
    app.include_router(notification_email_router)
    app.include_router(requests_router)
    app.include_router(recurring_schedules_router)
    app.include_router(invoice_api_keys_router)
    app.include_router(notification_preferences_router)
    app.include_router(invoice_documents_router)
    app.include_router(telegram_router)

    return app


app = create_app()
