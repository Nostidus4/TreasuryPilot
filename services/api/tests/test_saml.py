from __future__ import annotations

import base64
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlparse
from uuid import uuid4
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from saml2 import BINDING_HTTP_POST, BINDING_HTTP_REDIRECT, time_util
from saml2.saml import NAMEID_FORMAT_PERSISTENT

from treasurypilot_api import identity as identity_package
from treasurypilot_api.config import Settings
from treasurypilot_api.identity.api import _safe_saml_idp_location
from treasurypilot_api.identity.auth import AuthService, SessionTokenCodec, UserRecord, utc_now
from treasurypilot_api.identity.rate_limit import MemoryRateLimiter
from treasurypilot_api.identity.saml import (
    SAMLFailure,
    _extract_email,
    build_saml_client,
    parse_login_response,
)
from treasurypilot_api.identity.saml_repository import SAMLIdentityError, SAMLIdentityRepository
from treasurypilot_api.main import create_app

SP_ENTITY_ID = "https://app.example/saml"
ACS_URL = "https://api.example/v1/auth/saml/acs"
IDP_ENTITY_ID = "https://id.example/saml"
REQUEST_ID = "_request-123"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
SIGNED_REQUEST_ID = "_signed-request-123"
PROTOCOL_NS = "urn:oasis:names:tc:SAML:2.0:protocol"
ASSERTION_NS = "urn:oasis:names:tc:SAML:2.0:assertion"
DSIG_NS = "http://www.w3.org/2000/09/xmldsig#"


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
    assert client.config.getattr("only_use_keys_in_metadata") is True
    service = client.config.getattr("endpoints", "sp")
    assert service["assertion_consumer_service"] == [(ACS_URL, BINDING_HTTP_POST)]
    assert (
        client.metadata.single_sign_on_service(IDP_ENTITY_ID, binding=BINDING_HTTP_REDIRECT)[0][
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
    assert client.arguments["args"] == (base64.b64encode(b"<signed-response/>"), BINDING_HTTP_POST)


@pytest.mark.skipif(shutil.which("xmlsec1") is None, reason="xmlsec1 is required by PySAML2")
def test_real_saml_signed_response_is_accepted_and_tampered_or_unsigned_messages_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The signed fixture uses the deterministic NOW timestamp. Make PySAML2's own
    # timestamp validation use that same clock instead of the wall clock.
    monkeypatch.setattr(time_util, "utc_now", lambda: int(NOW.timestamp()))
    fixture_path = Path(__file__).parent / "fixtures" / "saml_signed_response.xml"
    response_xml = fixture_path.read_bytes()
    response_root = ET.fromstring(response_xml)
    certificate = response_root.findtext(f".//{{{DSIG_NS}}}X509Certificate")
    assert certificate
    metadata_path = tmp_path / "trusted-idp.xml"
    metadata_path.write_text(
        f'''<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
            xmlns:ds="{DSIG_NS}" entityID="{IDP_ENTITY_ID}">
          <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
            <md:KeyDescriptor use="signing"><ds:KeyInfo><ds:X509Data>
              <ds:X509Certificate>{certificate}</ds:X509Certificate>
            </ds:X509Data></ds:KeyInfo></md:KeyDescriptor>
            <md:SingleSignOnService Binding="{BINDING_HTTP_REDIRECT}"
                Location="https://id.example/sso" />
          </md:IDPSSODescriptor>
        </md:EntityDescriptor>''',
        encoding="utf-8",
    )
    client = build_saml_client(_settings(metadata_path))
    claims = parse_login_response(
        client,
        response_xml=response_xml,
        request_id=SIGNED_REQUEST_ID,
        sp_entity_id=SP_ENTITY_ID,
        acs_url=ACS_URL,
        idp_entity_id=IDP_ENTITY_ID,
        email_attribute="email",
        now=NOW,
    )
    assert claims.email == "person@example.com"
    assert claims.subject == "persistent-signed-subject"

    tampered_root = ET.fromstring(response_xml)
    tampered_email = tampered_root.find(f".//{{{ASSERTION_NS}}}AttributeValue")
    assert tampered_email is not None
    tampered_email.text = "attacker@example.com"
    tampered_response = ET.tostring(tampered_root, encoding="utf-8", xml_declaration=True)
    with pytest.raises(SAMLFailure):
        parse_login_response(
            client,
            response_xml=tampered_response,
            request_id=SIGNED_REQUEST_ID,
            sp_entity_id=SP_ENTITY_ID,
            acs_url=ACS_URL,
            idp_entity_id=IDP_ENTITY_ID,
            email_attribute="email",
            now=NOW,
        )

    unsigned_root = ET.fromstring(response_xml)
    for parent in unsigned_root.iter():
        for child in list(parent):
            if child.tag == f"{{{DSIG_NS}}}Signature":
                parent.remove(child)
    unsigned_response = ET.tostring(unsigned_root, encoding="utf-8", xml_declaration=True)
    with pytest.raises(SAMLFailure):
        parse_login_response(
            client,
            response_xml=unsigned_response,
            request_id=SIGNED_REQUEST_ID,
            sp_entity_id=SP_ENTITY_ID,
            acs_url=ACS_URL,
            idp_entity_id=IDP_ENTITY_ID,
            email_attribute="email",
            now=NOW,
        )


class _RouteSAMLRepository(SAMLIdentityRepository):
    def __init__(self, organization_id: object, user: UserRecord) -> None:
        self.organization_id = organization_id
        self.user = user
        self.requests: dict[str, dict[str, object]] = {}

    async def create_request(
        self,
        *,
        request_id: str,
        relay_state: str,
        browser_nonce: str,
        organization_id: object,
        now: datetime,
        expires_at: datetime,
    ) -> None:
        self.requests[relay_state] = {
            "request_id": request_id,
            "browser_nonce": browser_nonce,
            "organization_id": organization_id,
            "expires_at": expires_at,
            "consumed": False,
        }

    async def find_pending_request(
        self, *, relay_state: str, browser_nonce: str, now: datetime
    ) -> tuple[str, object] | None:
        item = self.requests.get(relay_state)
        if (
            item is None
            or item["browser_nonce"] != browser_nonce
            or item["consumed"]
            or item["expires_at"] <= now
        ):
            return None
        return str(item["request_id"]), item["organization_id"]

    async def complete_login(
        self,
        *,
        request_id: str,
        relay_state: str,
        browser_nonce: str,
        organization_id: object,
        issuer: str,
        subject: str,
        email: str,
        response_id: str,
        assertion_id: str,
        assertion_expires_at: datetime,
        now: datetime,
    ) -> UserRecord:
        item = self.requests.get(relay_state)
        if (
            item is None
            or item["request_id"] != request_id
            or item["browser_nonce"] != browser_nonce
            or item["organization_id"] != organization_id
            or item["consumed"]
        ):
            raise SAMLIdentityError("SAML login request is invalid or already used")
        item["consumed"] = True
        return self.user


class _RouteAuthRepository:
    def __init__(self) -> None:
        self.sessions: list[dict[str, object]] = []

    async def create_session(self, **values: object) -> None:
        self.sessions.append(values)


class _RouteMagicLinkSender:
    async def send_magic_link(self, *, email: str, url: str) -> None:
        return None


class _RouteSAMLClient:
    def __init__(self) -> None:
        self.request_number = 0

    def prepare_for_authenticate(
        self,
        *,
        entityid: str,
        relay_state: str,
        binding: str,
        response_binding: str,
        nameid_format: str,
    ) -> tuple[str, dict[str, object]]:
        self.request_number += 1
        request_id = f"_route-request-{self.request_number}"
        location = "https://id.example/sso?SAMLRequest=opaque&RelayState=" + quote(relay_state)
        return request_id, {"headers": [("Location", location)]}


def test_saml_routes_bind_acs_to_browser_cookie_relay_state_and_one_time_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization_id = uuid4()
    user = UserRecord(
        id=uuid4(), email="person@example.com", display_name="SAML User", status="active"
    )
    saml_repository = _RouteSAMLRepository(organization_id, user)
    auth_repository = _RouteAuthRepository()
    secret = b"saml-route-test-secret-with-at-least-32-bytes"
    rate_limiter = MemoryRateLimiter(utc_now)
    auth_service = AuthService(
        repository=auth_repository,  # type: ignore[arg-type]
        sender=_RouteMagicLinkSender(),  # type: ignore[arg-type]
        token_codec=SessionTokenCodec(secret),
        client_hash_secret=secret,
        magic_link_base_url="https://app.example.test/auth/verify",
        rate_limiter=rate_limiter,
    )
    settings = Settings(
        environment="local",
        saml_sp_entity_id=SP_ENTITY_ID,
        saml_acs_url=ACS_URL,
        saml_idp_metadata_path=tmp_path / "unused-idp.xml",
        saml_idp_entity_id=IDP_ENTITY_ID,
        saml_organization_id=organization_id,
        web_app_url="https://app.example.test",
    )
    app = create_app(
        settings=settings,
        auth_service=auth_service,
        rate_limiter=rate_limiter,
    )
    app.state.saml_repository = saml_repository
    saml_client = _RouteSAMLClient()
    monkeypatch.setattr(identity_package.api, "build_saml_client", lambda _: saml_client)

    def parse_response(
        client: object,
        *,
        response_xml: bytes,
        request_id: str,
        sp_entity_id: str,
        acs_url: str,
        idp_entity_id: str,
        email_attribute: str,
        now: datetime,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            request_id=request_id,
            issuer=IDP_ENTITY_ID,
            subject="persistent-route-subject",
            email="person@example.com",
            response_id=f"{request_id}-response",
            assertion_id=f"{request_id}-assertion",
            assertion_expires_at=now + timedelta(minutes=2),
        )

    monkeypatch.setattr(identity_package.api, "parse_login_response", parse_response)

    def start_login(client: TestClient) -> tuple[str, str]:
        started = client.get("/v1/auth/saml/start", follow_redirects=False)
        assert started.status_code == 302
        relay_state = parse_qs(urlparse(started.headers["location"]).query)["RelayState"][0]
        browser_cookie = client.cookies.get("__Host-tp_saml_browser")
        assert browser_cookie is not None
        return relay_state, browser_cookie

    def acs_body(relay_state: str) -> dict[str, str]:
        import base64

        return {
            "SAMLResponse": base64.b64encode(b"mock response").decode("ascii"),
            "RelayState": relay_state,
        }

    with TestClient(app, base_url="https://app.example.test") as client:
        relay_state, browser_cookie = start_login(client)
        client.cookies.set("__Host-tp_saml_browser", "x" * 43)
        mismatch = client.post(
            "/v1/auth/saml/acs", data=acs_body(relay_state), follow_redirects=False
        )
        assert mismatch.status_code == 401

        client.cookies.set("__Host-tp_saml_browser", browser_cookie)
        wrong_relay = client.post(
            "/v1/auth/saml/acs", data=acs_body(relay_state + "-other"), follow_redirects=False
        )
        assert wrong_relay.status_code == 401

        success = client.post(
            "/v1/auth/saml/acs", data=acs_body(relay_state), follow_redirects=False
        )
        assert success.status_code == 303
        assert success.headers["location"] == "https://app.example.test"
        assert len(auth_repository.sessions) == 1

        replay = client.post(
            "/v1/auth/saml/acs", data=acs_body(relay_state), follow_redirects=False
        )
        assert replay.status_code == 401

    with TestClient(app, base_url="https://app.example.test") as no_cookie_client:
        second_relay_state, _ = start_login(no_cookie_client)
        no_cookie_client.cookies.clear()
        missing_cookie = no_cookie_client.post(
            "/v1/auth/saml/acs",
            data=acs_body(second_relay_state),
            follow_redirects=False,
        )
        assert missing_cookie.status_code == 401

    # IdPs and proxies may line-wrap the base64 SAMLResponse.
    with TestClient(app, base_url="https://app.example.test") as wrapped_client:
        wrapped_relay_state, _ = start_login(wrapped_client)
        wrapped = acs_body(wrapped_relay_state)
        wrapped["SAMLResponse"] = "\r\n".join(
            wrapped["SAMLResponse"][i : i + 4] for i in range(0, len(wrapped["SAMLResponse"]), 4)
        )
        wrapped_response = wrapped_client.post(
            "/v1/auth/saml/acs", data=wrapped, follow_redirects=False
        )
        assert wrapped_response.status_code == 303

    with TestClient(app, base_url="https://app.example.test") as limited_client:
        statuses = {
            limited_client.get("/v1/auth/saml/start", follow_redirects=False).status_code
            for _ in range(25)
        }
        assert statuses == {302, 429}


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
