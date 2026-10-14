from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from saml2 import BINDING_HTTP_POST, BINDING_HTTP_REDIRECT
from saml2.saml import NAMEID_FORMAT_PERSISTENT

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.api import _safe_saml_idp_location
from treasurypilot_api.identity.saml import (
    SAMLFailure,
    _extract_email,
    build_saml_client,
    parse_login_response,
)

SP_ENTITY_ID = "https://app.example/saml"
ACS_URL = "https://api.example/v1/auth/saml/acs"
IDP_ENTITY_ID = "https://id.example/saml"
REQUEST_ID = "_request-123"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def _settings(metadata_path: Path) -> Settings:
    return Settings(
        environment="local",
        saml_sp_entity_id=SP_ENTITY_ID,
        saml_acs_url=ACS_URL,
        saml_idp_metadata_path=metadata_path,
        saml_idp_entity_id=IDP_ENTITY_ID,
        saml_organization_id=uuid4(),
    )


def _text(value: str) -> SimpleNamespace:
    return SimpleNamespace(text=value)


def _parsed_response(**overrides: object) -> SimpleNamespace:
    issue_instant = (NOW - timedelta(seconds=10)).isoformat()
    response = SimpleNamespace(
        in_response_to=REQUEST_ID,
        destination=ACS_URL,
        issuer=_text(IDP_ENTITY_ID),
        issue_instant=issue_instant,
        id="_response-123",
    )
    conditions = SimpleNamespace(
        not_before=(NOW - timedelta(seconds=30)).isoformat(),
        not_on_or_after=(NOW + timedelta(minutes=4)).isoformat(),
        audience_restriction=[SimpleNamespace(audience=[_text(SP_ENTITY_ID)])],
    )
    confirmation_data = SimpleNamespace(
        in_response_to=REQUEST_ID,
        recipient=ACS_URL,
        not_before=None,
        not_on_or_after=(NOW + timedelta(minutes=2)).isoformat(),
    )
    assertion = SimpleNamespace(
        issuer=_text(IDP_ENTITY_ID),
        authn_statement=[object()],
        conditions=conditions,
        issue_instant=issue_instant,
        id="_assertion-123",
        subject=SimpleNamespace(
            name_id=SimpleNamespace(text="persistent-subject", format=NAMEID_FORMAT_PERSISTENT),
            subject_confirmation=[
                SimpleNamespace(
                    method="urn:oasis:names:tc:SAML:2.0:cm:bearer",
                    subject_confirmation_data=confirmation_data,
                )
            ],
        ),
        attribute_statement=[
            SimpleNamespace(
                attribute=[
                    SimpleNamespace(
                        name="mail",
                        friendly_name="email",
                        attribute_value=[_text("Person@Example.com")],
                    )
                ]
            )
        ],
    )
    parsed = SimpleNamespace(response=response, assertion=assertion, assertions=[assertion])
    for key, value in overrides.items():
        target, attribute = key.split(".", maxsplit=1)
        setattr(response if target == "response" else assertion, attribute, value)
    return parsed


class _FakeSamlClient:
    def __init__(self, parsed: SimpleNamespace) -> None:
        self.parsed = parsed
        self.arguments: dict[str, object] = {}

    def parse_authn_request_response(self, *args: object, **kwargs: object) -> SimpleNamespace:
        self.arguments = {"args": args, **kwargs}
        return self.parsed


@pytest.mark.skipif(shutil.which("xmlsec1") is None, reason="xmlsec1 is required by PySAML2")
def test_saml_client_uses_local_metadata_and_requires_signed_correlated_responses(
    tmp_path: Path,
) -> None:
    metadata = tmp_path / "idp.xml"
    metadata.write_text(
        f'''<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata"
            entityID="{IDP_ENTITY_ID}">
          <IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
            <SingleSignOnService Binding="{BINDING_HTTP_REDIRECT}"
                Location="https://id.example/sso" />
          </IDPSSODescriptor>
        </EntityDescriptor>''',
        encoding="utf-8",
    )
    client = build_saml_client(_settings(metadata))
    assert client.config.getattr("allow_unsolicited", "sp") is False
    assert client.config.getattr("want_response_signed", "sp") is True
    assert client.config.getattr("want_assertions_signed", "sp") is True
    assert client.config.getattr("only_use_keys_in_metadata", "sp") is True
    service = client.config.getattr("endpoints", "sp")
    assert service["assertion_consumer_service"] == [(ACS_URL, BINDING_HTTP_POST)]
    assert (
        client.metadata[IDP_ENTITY_ID].single_sign_on_service(binding=BINDING_HTTP_REDIRECT)[0][
            "location"
        ]
        == "https://id.example/sso"
    )


def test_saml_response_requires_signature_verifier_correlation_and_persistent_identity() -> None:
    client = _FakeSamlClient(_parsed_response())
    claims = parse_login_response(
        client,
        response_xml=b"<signed-response/>",
        request_id=REQUEST_ID,
        sp_entity_id=SP_ENTITY_ID,
        acs_url=ACS_URL,
        idp_entity_id=IDP_ENTITY_ID,
        email_attribute="email",
        now=NOW,
    )
    assert claims.email == "person@example.com"
    assert claims.subject == "persistent-subject"
    assert claims.response_id == "_response-123"
    assert claims.assertion_id == "_assertion-123"
    assert client.arguments["outstanding"] == {REQUEST_ID: True}
    assert client.arguments["conv_info"] == {"entity_id": ACS_URL}


@pytest.mark.parametrize(
    "overrides",
    [
        {"response.in_response_to": "_another-request"},
        {"response.destination": "https://evil.example/acs"},
        {"response.issuer": _text("https://evil.example/idp")},
        {"assertion.issuer": _text("https://evil.example/idp")},
        {"assertion.conditions": None},
        {"assertion.authn_statement": []},
    ],
)
def test_saml_response_rejects_request_destination_issuer_and_time_mismatches(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(SAMLFailure):
        parse_login_response(
            _FakeSamlClient(_parsed_response(**overrides)),
            response_xml=b"<signed-response/>",
            request_id=REQUEST_ID,
            sp_entity_id=SP_ENTITY_ID,
            acs_url=ACS_URL,
            idp_entity_id=IDP_ENTITY_ID,
            email_attribute="email",
            now=NOW,
        )


def test_saml_response_rejects_wrong_audience_and_confirmation() -> None:
    parsed = _parsed_response()
    parsed.assertion.conditions.audience_restriction = [
        SimpleNamespace(audience=[_text("https://other.example/saml")])
    ]
    with pytest.raises(SAMLFailure, match="audience"):
        parse_login_response(
            _FakeSamlClient(parsed),
            response_xml=b"<signed-response/>",
            request_id=REQUEST_ID,
            sp_entity_id=SP_ENTITY_ID,
            acs_url=ACS_URL,
            idp_entity_id=IDP_ENTITY_ID,
            email_attribute="email",
            now=NOW,
        )

    parsed = _parsed_response()
    parsed.assertion.subject.subject_confirmation[
        0
    ].subject_confirmation_data.recipient = "https://other.example/acs"
    with pytest.raises(SAMLFailure, match="bearer confirmation"):
        parse_login_response(
            _FakeSamlClient(parsed),
            response_xml=b"<signed-response/>",
            request_id=REQUEST_ID,
            sp_entity_id=SP_ENTITY_ID,
            acs_url=ACS_URL,
            idp_entity_id=IDP_ENTITY_ID,
            email_attribute="email",
            now=NOW,
        )


def test_saml_email_attribute_must_be_unique_and_valid() -> None:
    parsed = _parsed_response()
    assert _extract_email(parsed.assertion, "mail") == "person@example.com"
    with pytest.raises(SAMLFailure):
        _extract_email(parsed.assertion, "missing")
    parsed.assertion.attribute_statement[0].attribute[0].attribute_value.append(
        _text("second@example.com")
    )
    with pytest.raises(SAMLFailure):
        _extract_email(parsed.assertion, "email")


def test_saml_redirect_only_uses_https_or_local_loopback() -> None:
    settings = SimpleNamespace(environment="production")
    assert _safe_saml_idp_location("https://id.example/sso", settings)
    assert not _safe_saml_idp_location("http://id.example/sso", settings)
    assert not _safe_saml_idp_location("https://user:pass@id.example/sso", settings)
    settings.environment = "local"
    assert _safe_saml_idp_location("http://localhost:8080/sso", settings)
    assert not _safe_saml_idp_location("http://evil.example/sso", settings)
