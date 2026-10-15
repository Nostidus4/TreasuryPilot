from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from saml2 import BINDING_HTTP_POST  # type: ignore[import-untyped]
from saml2.client import Saml2Client  # type: ignore[import-untyped]
from saml2.config import Config as SAMLConfig  # type: ignore[import-untyped]
from saml2.saml import NAMEID_FORMAT_PERSISTENT  # type: ignore[import-untyped]

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import normalize_email

SAML_REQUEST_LIFETIME = timedelta(minutes=10)
SAML_RESPONSE_MAX_BYTES = 1024 * 1024
SAML_FORM_MAX_BYTES = 2 * 1024 * 1024
SAML_ISSUED_AT_MAX_AGE = timedelta(minutes=5)
SAML_FUTURE_CLOCK_SKEW = timedelta(seconds=30)
_BEARER_CONFIRMATION = "urn:oasis:names:tc:SAML:2.0:cm:bearer"
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class SAMLFailure(Exception):
    """An untrusted or invalid SAML authentication message."""


@dataclass(frozen=True, slots=True)
class SAMLLoginClaims:
    request_id: str
    issuer: str
    subject: str
    email: str
    response_id: str
    assertion_id: str
    assertion_expires_at: datetime


@lru_cache(maxsize=4)
def _load_config(
    sp_entity_id: str | None,
    acs_url: str | None,
    metadata_path: str,
    metadata_mtime_ns: int,  # cache key only: a changed file reloads
    metadata_size: int,  # cache key only
) -> SAMLConfig:
    configuration = SAMLConfig().load(
        {
            "entityid": sp_entity_id,
            "metadata": {"local": [metadata_path]},
            "only_use_keys_in_metadata": True,
            "accepted_time_diff": 0,
            "service": {
                "sp": {
                    "endpoints": {"assertion_consumer_service": [(acs_url, BINDING_HTTP_POST)]},
                    "allow_unsolicited": False,
                    "authn_requests_signed": False,
                    "want_response_signed": True,
                    "want_assertions_signed": True,
                    "want_assertions_or_response_signed": False,
                    "name_id_policy_format": NAMEID_FORMAT_PERSISTENT,
                    "allow_unknown_attributes": True,
                }
            },
        }
    )
    return configuration


def build_saml_client(settings: Settings) -> Saml2Client:
    if not settings.saml_configured:
        raise SAMLFailure("SAML is not configured")
    metadata_path = settings.saml_idp_metadata_path
    if metadata_path is None or not metadata_path.is_file():
        raise SAMLFailure("SAML IdP metadata is unavailable")
    metadata_stat = metadata_path.stat()
    if metadata_stat.st_size > 1_000_000:
        raise SAMLFailure("SAML IdP metadata is too large")
    # Parsing IdP metadata is costly and /auth/saml/start is unauthenticated: reuse the parsed
    # configuration until the metadata file changes.
    configuration = _load_config(
        settings.saml_sp_entity_id,
        settings.saml_acs_url,
        str(metadata_path),
        metadata_stat.st_mtime_ns,
        metadata_stat.st_size,
    )
    return Saml2Client(config=configuration)


def parse_login_response(
    client: Saml2Client,
    *,
    response_xml: bytes,
    request_id: str,
    sp_entity_id: str,
    acs_url: str,
    idp_entity_id: str,
    email_attribute: str,
    now: datetime,
) -> SAMLLoginClaims:
    if not response_xml or len(response_xml) > SAML_RESPONSE_MAX_BYTES:
        raise SAMLFailure("invalid SAML response size")
    now = _aware_utc(now)
    try:
        parsed = client.parse_authn_request_response(
            base64.b64encode(response_xml),
            BINDING_HTTP_POST,
            outstanding={request_id: True},
            # PySAML2 checks bearer Recipient against this exact configured ACS URL.
            conv_info={"entity_id": acs_url},
        )
    except Exception as exc:
        raise SAMLFailure("SAML response verification failed") from exc
    if parsed is None or parsed.response is None or parsed.assertion is None:
        raise SAMLFailure("SAML response is incomplete")

    response = parsed.response
    if _text(response.in_response_to) != request_id:
        raise SAMLFailure("SAML response does not match the login request")
    if _text(response.destination) != acs_url:
        raise SAMLFailure("SAML response destination does not match the ACS")
    response_issuer = _text(response.issuer)
    if response_issuer != idp_entity_id:
        raise SAMLFailure("SAML response issuer is not configured")

    assertions = list(parsed.assertions or ())
    if len(assertions) != 1:
        raise SAMLFailure("SAML response must contain one assertion")
    assertion = assertions[0]
    if _text(assertion.issuer) != idp_entity_id:
        raise SAMLFailure("SAML assertion issuer is not configured")

    if len(assertion.authn_statement or ()) != 1:
        raise SAMLFailure("SAML assertion must contain one authentication statement")
    conditions = assertion.conditions
    if conditions is None:
        raise SAMLFailure("SAML assertion has no validity conditions")
    not_before = _parse_saml_time(conditions.not_before)
    not_on_or_after = _parse_saml_time(conditions.not_on_or_after)
    if not_before is None or not_on_or_after is None or not (not_before <= now < not_on_or_after):
        raise SAMLFailure("SAML assertion is outside its validity period")
    restrictions = list(conditions.audience_restriction or ())
    if not restrictions or any(
        not any(_text(audience) == sp_entity_id for audience in (restriction.audience or ()))
        for restriction in restrictions
    ):
        raise SAMLFailure("SAML assertion audience is not the configured service provider")

    response_issued_at = _parse_saml_time(response.issue_instant)
    assertion_issued_at = _parse_saml_time(assertion.issue_instant)
    if not _recent(response_issued_at, now) or not _recent(assertion_issued_at, now):
        raise SAMLFailure("SAML response is too old or issued in the future")

    subject = assertion.subject
    name_id = subject.name_id if subject is not None else None
    subject_value = _text(name_id)
    if (
        not subject_value
        or len(subject_value) > 255
        or _text(getattr(name_id, "format", None)) != NAMEID_FORMAT_PERSISTENT
    ):
        raise SAMLFailure("SAML response must contain a persistent NameID")

    confirmations = list(subject.subject_confirmation or ()) if subject is not None else []
    matching_confirmation = False
    for confirmation in confirmations:
        data = confirmation.subject_confirmation_data
        if _text(confirmation.method) != _BEARER_CONFIRMATION or data is None:
            continue
        confirmation_not_before = _parse_saml_time(data.not_before)
        if (
            _text(data.in_response_to) != request_id
            or _text(data.recipient) != acs_url
            or (confirmation_not_before is not None and confirmation_not_before > now)
        ):
            continue
        confirmation_expires = _parse_saml_time(data.not_on_or_after)
        if confirmation_expires is None or not now < confirmation_expires:
            continue
        matching_confirmation = True
        break
    if not matching_confirmation:
        raise SAMLFailure("SAML assertion has no valid bearer confirmation")

    email = _extract_email(assertion, email_attribute)
    response_id = _text(response.id)
    assertion_id = _text(assertion.id)
    if not response_id or len(response_id) > 255 or not assertion_id or len(assertion_id) > 255:
        raise SAMLFailure("SAML response identifiers are invalid")
    return SAMLLoginClaims(
        request_id=request_id,
        issuer=idp_entity_id,
        subject=subject_value,
        email=email,
        response_id=response_id,
        assertion_id=assertion_id,
        assertion_expires_at=not_on_or_after,
    )


def _extract_email(assertion: Any, configured_name: str) -> str:
    matching_attributes: list[Any] = []
    for statement in assertion.attribute_statement or ():
        for attribute in statement.attribute or ():
            if configured_name in {
                _text(attribute.name),
                _text(attribute.friendly_name),
            }:
                matching_attributes.append(attribute)
    if len(matching_attributes) != 1:
        raise SAMLFailure("SAML response has no unique configured email attribute")
    values = list(matching_attributes[0].attribute_value or ())
    if len(values) != 1:
        raise SAMLFailure("SAML response email attribute must have one value")
    email = _text(values[0])
    if not email or len(email) > 320 or not _EMAIL_PATTERN.fullmatch(email.strip()):
        raise SAMLFailure("SAML response email attribute is invalid")
    return normalize_email(email)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    text_value = getattr(value, "text", None)
    return text_value if isinstance(text_value, str) else ""


def _parse_saml_time(value: Any) -> datetime | None:
    text_value = _text(value)
    if not text_value:
        return None
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SAMLFailure("SAML validation clock must be timezone aware")
    return value.astimezone(UTC)


def _recent(value: datetime | None, now: datetime) -> bool:
    return bool(
        value is not None and now - SAML_ISSUED_AT_MAX_AGE <= value <= now + SAML_FUTURE_CLOCK_SKEW
    )
