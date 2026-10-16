import ipaddress
import json
import re
import uuid
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from treasurypilot_api.compliance.regions import parse_regions
from treasurypilot_api.identity.role_grants import OIDC_ASSIGNABLE_ROLES
from treasurypilot_core.observability import LogFormat

# services/api/src/treasurypilot_api/config.py -> repository root
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="TP_", case_sensitive=False)

    environment: str = "local"
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"
    log_format: LogFormat = "json"
    database_url: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("TP_DATABASE_URL", "DATABASE_URL"),
    )
    session_secret: SecretStr | None = None
    # Signs notification-email unsubscribe links; shared with the egress worker, never the session key.
    email_unsubscribe_key: SecretStr | None = None
    # Keys subject-erasure receipts (>= 32 bytes); fixed for the life of the receipts.
    retention_receipt_key: SecretStr | None = None
    redis_url: SecretStr | None = None
    # Signer service for the pause-only sentinel; pause falls back to a Guardian Safe tx without it.
    signer_url: str | None = None
    signer_shared_secret: SecretStr | None = None
    # Below this ETH balance (wei) the sentinel cannot be relied on to pause; the guardian health
    # check warns (MDT-010).
    sentinel_min_gas_wei: int = Field(default=5 * 10**15, ge=0)
    s3_endpoint_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TP_S3_ENDPOINT_URL", "S3_ENDPOINT_URL"),
    )
    # Browser-reachable endpoint used only to presign reads; defaults to s3_endpoint_url.
    s3_public_endpoint_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TP_S3_PUBLIC_ENDPOINT_URL", "S3_PUBLIC_ENDPOINT_URL"),
    )
    s3_bucket: str | None = Field(
        default=None, validation_alias=AliasChoices("TP_S3_BUCKET", "S3_BUCKET")
    )
    s3_access_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("TP_S3_ACCESS_KEY", "S3_ACCESS_KEY"),
    )
    s3_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("TP_S3_SECRET_KEY", "S3_SECRET_KEY"),
    )
    magic_link_base_url: str = "http://localhost:5173/verify"
    # Where the browser lands after SSO sign-in; falls back to the first CORS origin.
    web_app_url: str | None = None
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    oidc_redirect_uri: str | None = None
    oidc_organization_id: str | None = None
    oidc_group_role_map: str = "{}"
    # SAML uses a local, operator-managed IdP metadata file; no metadata URL is fetched.
    saml_sp_entity_id: str | None = None
    saml_acs_url: str | None = None
    saml_idp_metadata_path: Path | None = None
    saml_idp_entity_id: str | None = None
    saml_organization_id: uuid.UUID | None = None
    saml_email_attribute: str = "email"
    # SCIM is a single-tenant, bearer-authenticated provisioning integration.
    scim_bearer_token: SecretStr | None = None
    scim_organization_id: uuid.UUID | None = None
    # Only configured SCIM group names may grant these non-privileged work roles.
    scim_group_role_map: str = "{}"
    resend_api_key: SecretStr | None = None
    resend_from_email: str | None = None
    session_cookie_name: str = "tp_session"
    csrf_cookie_name: str = "tp_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    telegram_bot_username: str | None = None
    telegram_webhook_secret: SecretStr | None = None
    # Keys the chat-uniqueness hash; must stay fixed for the life of the data.
    telegram_chat_hash_key: SecretStr | None = None
    # Xero OAuth app (developer.xero.com). Unset leaves the Xero connector off.
    xero_client_id: str | None = None
    xero_client_secret: SecretStr | None = None
    # QuickBooks Online OAuth app (developer.intuit.com). Unset leaves the connector off.
    quickbooks_client_id: str | None = None
    quickbooks_client_secret: SecretStr | None = None
    quickbooks_sandbox: bool = False
    # NetSuite OAuth 2.0 integration (account id like 1234567 or 1234567_SB1). Unset = off.
    netsuite_account_id: str | None = None
    netsuite_client_id: str | None = None
    netsuite_client_secret: SecretStr | None = None
    erp_oauth_redirect_uri: str = "http://localhost:5173/settings/integrations/erp/callback"
    platform_chain_config_path: Path = REPOSITORY_ROOT / "deployments" / "chains.json"
    deployments_dir: Path = REPOSITORY_ROOT / "deployments"
    admin_staff_token: SecretStr | None = None
    admin_staff_id: str | None = None
    admin_ip_allowlist: str = ""
    # Fiat-denominated requests are enabled only when both fx_source_id and fx_tolerance_bps are
    # set (and an FxQuoteProvider is passed to create_app); otherwise they return 503.
    fx_source_id: str | None = Field(default=None, min_length=1)
    fx_max_quote_age_seconds: int = Field(default=60, ge=0)
    fx_depeg_threshold_bps: int = Field(default=100, ge=0, le=10_000)
    fx_tolerance_bps: int | None = Field(default=None, ge=0, le=10_000)
    # TEST only: quotes a USD-pegged stablecoin 1:1 so the local stack can value requests. Needs
    # fx_source_id and a local/test environment; never enable it on a real deployment.
    fx_test_static_provider: bool = False
    # JSON jurisdiction -> currency -> integer minor-unit threshold. No legal default is assumed.
    travel_rule_thresholds: str = "{}"
    # JSON region id -> {s3_endpoint_url, s3_bucket, s3_access_key, s3_secret_key, ...} (CMP-L04).
    data_regions: str = "{}"
    # The region this deployment's database serves; unset disables the cross-region DB guard.
    data_region: str | None = None
    # Optional vendor-neutral Travel Rule gateway. Credentials are secrets and are never logged.
    travel_rule_provider_url: str | None = Field(default=None, min_length=1)
    travel_rule_provider_api_key: SecretStr | None = None
    inbound_email_domain: str | None = None
    inbound_email_webhook_secret: SecretStr | None = None

    @field_validator("inbound_email_domain")
    @classmethod
    def _validate_inbound_email_domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        domain = value.strip().casefold().rstrip(".")
        if not re.fullmatch(
            r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain
        ):
            raise ValueError("inbound email domain must be a DNS hostname")
        return domain

    @model_validator(mode="after")
    def _validate_oidc_configuration(self) -> "Settings":
        oidc_values = (
            self.oidc_issuer,
            self.oidc_client_id,
            self.oidc_client_secret,
            self.oidc_redirect_uri,
            self.oidc_organization_id,
        )
        if any(oidc_values) and not all(oidc_values):
            raise ValueError(
                "OIDC requires issuer, client ID/secret, redirect URI and organization ID"
            )
        if all(oidc_values):
            for value in (self.oidc_issuer, self.oidc_redirect_uri):
                parsed = urlparse(value or "")
                is_loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                if parsed.scheme != "https" and not (
                    self.environment.casefold() == "local"
                    and parsed.scheme == "http"
                    and is_loopback
                ):
                    raise ValueError("OIDC issuer and redirect URI must use HTTPS")
            try:
                uuid.UUID(self.oidc_organization_id or "")
                role_map = json.loads(self.oidc_group_role_map)
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError("invalid OIDC organization ID or group role map") from exc
            if not isinstance(role_map, dict) or any(
                not isinstance(group, str)
                or not isinstance(roles, list)
                or any(
                    not isinstance(role, str) or role not in {"Operator", "Finance", "Auditor"}
                    for role in roles
                )
                for group, roles in role_map.items()
            ):
                raise ValueError("OIDC groups may map only to Operator, Finance or Auditor roles")
        return self

    @field_validator(
        "signer_url", "signer_shared_secret", "fx_source_id", "fx_tolerance_bps", mode="before"
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("signer_url")
    @classmethod
    def _signer_url_is_http(cls, value: str | None) -> str | None:
        # The shared secret is sent here: refuse file:, ftp: and the like.
        if value is not None and urlparse(value).scheme not in ("http", "https"):
            raise ValueError("signer URL must be http(s)")
        return value

    @field_validator("travel_rule_provider_url", "travel_rule_provider_api_key", mode="before")
    @classmethod
    def _blank_travel_rule_provider_is_unset(cls, value: object) -> object:
        # `.env.example` ships these empty; an empty env var must mean "not configured".
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _validate_saml_configuration(self) -> "Settings":
        saml_values = (
            self.saml_sp_entity_id,
            self.saml_acs_url,
            self.saml_idp_metadata_path,
            self.saml_idp_entity_id,
            self.saml_organization_id,
        )
        if any(saml_values) and not all(saml_values):
            raise ValueError(
                "SAML requires SP entity ID, ACS URL, IdP metadata file, IdP entity ID "
                "and organization ID"
            )
        if all(saml_values):
            if len(self.saml_sp_entity_id or "") > 500 or len(self.saml_idp_entity_id or "") > 500:
                raise ValueError("SAML entity IDs must not exceed 500 characters")
            if (
                not (self.saml_sp_entity_id or "").strip()
                or not (self.saml_idp_entity_id or "").strip()
            ):
                raise ValueError("SAML entity IDs cannot be blank")
            parsed = urlparse(self.saml_acs_url or "")
            is_loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            if parsed.scheme != "https" and not (
                self.environment.casefold() == "local" and parsed.scheme == "http" and is_loopback
            ):
                raise ValueError("SAML ACS URL must use HTTPS")
            if (
                not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "SAML ACS URL must be an absolute URL without credentials or query"
                )
            if not self.saml_email_attribute.strip() or len(self.saml_email_attribute) > 500:
                raise ValueError("SAML email attribute must contain 1 to 500 characters")
        return self

    @model_validator(mode="after")
    def _validate_travel_rule_provider(self) -> "Settings":
        provider_url = self.travel_rule_provider_url
        api_key = self.travel_rule_provider_api_key
        if (provider_url is None) != (api_key is None):
            raise ValueError("Travel Rule gateway URL and API key must be configured together")
        if provider_url is None:
            return self
        parsed = urlparse(provider_url)
        is_loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or (
                parsed.scheme != "https"
                and not (self.environment.casefold() == "local" and is_loopback)
            )
        ):
            raise ValueError("Travel Rule gateway URL must use HTTPS (except local loopback)")
        if api_key is None or not api_key.get_secret_value().strip():
            raise ValueError("Travel Rule gateway API key cannot be blank")
        return self

    @model_validator(mode="after")
    def _validate_scim_configuration(self) -> "Settings":
        if (self.scim_bearer_token is None) != (self.scim_organization_id is None):
            raise ValueError("SCIM requires both a bearer token and organization ID")
        if (
            self.scim_bearer_token is not None
            and len(self.scim_bearer_token.get_secret_value().encode("utf-8")) < 32
        ):
            raise ValueError("TP_SCIM_BEARER_TOKEN must contain at least 32 bytes")
        try:
            group_role_map = json.loads(self.scim_group_role_map)
        except json.JSONDecodeError as exc:
            raise ValueError("TP_SCIM_GROUP_ROLE_MAP must be a JSON object") from exc
        assignable_roles = OIDC_ASSIGNABLE_ROLES
        if not isinstance(group_role_map, dict) or any(
            not isinstance(group, str)
            or not group.strip()
            or len(group) > 100
            or not isinstance(roles, list)
            or not roles
            or len(roles) > len(assignable_roles)
            or any(not isinstance(role, str) or role not in assignable_roles for role in roles)
            or len({role for role in roles if isinstance(role, str)}) != len(roles)
            for group, roles in group_role_map.items()
        ):
            raise ValueError(
                "SCIM groups may map only non-empty role lists of Operator, Finance or Auditor"
            )
        normalized_names = [group.casefold() for group in group_role_map]
        if len(set(normalized_names)) != len(normalized_names):
            raise ValueError("SCIM group names must be unique ignoring case")
        if group_role_map and not self.scim_configured:
            raise ValueError("SCIM group roles require SCIM bearer token and organization ID")
        return self

    @field_validator("admin_ip_allowlist")
    @classmethod
    def _validate_admin_ip_allowlist(cls, value: str) -> str:
        # Fail at startup on a malformed CIDR instead of silently disabling admin.
        for item in value.split(","):
            if item.strip():
                ipaddress.ip_network(item.strip(), strict=False)
        return value

    @field_validator("data_regions")
    @classmethod
    def _validate_data_regions(cls, value: str) -> str:
        parse_regions(value)
        return value

    @field_validator("data_region", mode="before")
    @classmethod
    def _blank_data_region_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _validate_data_region(self) -> "Settings":
        if self.data_region is not None and self.data_region not in parse_regions(
            self.data_regions
        ):
            raise ValueError("TP_DATA_REGION must be one of the configured TP_DATA_REGIONS")
        return self

    @model_validator(mode="after")
    def _validate_fx_test_static_provider(self) -> "Settings":
        if self.fx_test_static_provider and (
            self.environment.casefold() not in {"local", "test"} or not self.fx_source_id
        ):
            raise ValueError(
                "TP_FX_TEST_STATIC_PROVIDER needs TP_ENVIRONMENT local or test and TP_FX_SOURCE_ID"
            )
        return self

    @field_validator("travel_rule_thresholds")
    @classmethod
    def _validate_travel_rule_thresholds(cls, value: str) -> str:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("TP_TRAVEL_RULE_THRESHOLDS must be a JSON object") from exc
        if not isinstance(parsed, dict):
            raise ValueError("TP_TRAVEL_RULE_THRESHOLDS must be a JSON object")
        normalized: dict[str, dict[str, int]] = {}
        for jurisdiction, currencies in parsed.items():
            if (
                not isinstance(jurisdiction, str)
                or len(jurisdiction) != 2
                or not jurisdiction.isascii()
                or not jurisdiction.isalpha()
            ):
                raise ValueError("Travel Rule jurisdictions must be two-letter country codes")
            if not isinstance(currencies, dict) or not currencies:
                raise ValueError("Each Travel Rule jurisdiction requires currency thresholds")
            normalized_currencies: dict[str, int] = {}
            for currency, threshold in currencies.items():
                if (
                    not isinstance(currency, str)
                    or len(currency) != 3
                    or not currency.isascii()
                    or not currency.isalpha()
                    or isinstance(threshold, bool)
                    or not isinstance(threshold, int)
                    or threshold < 0
                    or threshold >= 10**78
                ):
                    raise ValueError(
                        "Travel Rule thresholds require ISO codes and nonnegative integer minor units"
                    )
                if currency.upper() in normalized_currencies:
                    raise ValueError("Duplicate Travel Rule currency after normalization")
                normalized_currencies[currency.upper()] = threshold
            if jurisdiction.upper() in normalized:
                raise ValueError("Duplicate Travel Rule jurisdiction after normalization")
            normalized[jurisdiction.upper()] = normalized_currencies
        return json.dumps(normalized, sort_keys=True)

    @property
    def admin_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        return [
            ipaddress.ip_network(item.strip(), strict=False)
            for item in self.admin_ip_allowlist.split(",")
            if item.strip()
        ]

    @property
    def admin_configured(self) -> bool:
        return (
            self.admin_staff_token is not None
            and len(self.admin_staff_token.get_secret_value().encode()) >= 32
            and bool(self.admin_staff_id)
            and bool(self.admin_networks)
        )

    @property
    def oidc_configured(self) -> bool:
        return all(
            (
                self.oidc_issuer,
                self.oidc_client_id,
                self.oidc_client_secret,
                self.oidc_redirect_uri,
                self.oidc_organization_id,
            )
        )

    @property
    def saml_configured(self) -> bool:
        return all(
            (
                self.saml_sp_entity_id,
                self.saml_acs_url,
                self.saml_idp_metadata_path,
                self.saml_idp_entity_id,
                self.saml_organization_id,
            )
        )

    @property
    def inbound_email_configured(self) -> bool:
        return bool(
            self.inbound_email_domain
            and self.inbound_email_webhook_secret
            and len(self.inbound_email_webhook_secret.get_secret_value().encode()) >= 32
        )

    @property
    def scim_configured(self) -> bool:
        return self.scim_bearer_token is not None and self.scim_organization_id is not None

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
