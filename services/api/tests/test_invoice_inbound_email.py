from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from treasurypilot_api.config import Settings
from treasurypilot_api.invoices.inbound_email import (
    InboundEmailMessage,
    _sender_is_authenticated,
    sign_webhook_body,
    verify_webhook_signature,
)


def _message(
    spf: str | None,
    dkim: str | None,
    spf_domain: str | None = "example.test",
    dkim_domain: str | None = "example.test",
) -> InboundEmailMessage:
    return InboundEmailMessage.model_validate(
        {
            "messageId": "<invoice-1@example.test>",
            "sender": "billing@example.test",
            "recipient": "invoices+" + "a" * 48 + "@invoices.example.test",
            "authenticationResults": {
                "spf": spf,
                "spfDomain": spf_domain,
                "dkim": dkim,
                "dkimDomain": dkim_domain,
            },
            "attachments": [{"filename": "invoice.pdf", "contentBase64": "YWJj"}],
        }
    )


def test_email_sender_requires_a_passing_aligned_spf_or_dkim_result() -> None:
    assert _sender_is_authenticated(_message("pass", "pass"))
    assert _sender_is_authenticated(_message("pass", "fail", "example.test", "attacker.test"))
    assert not _sender_is_authenticated(_message("pass", "pass", "attacker.test", "attacker.test"))
    assert not _sender_is_authenticated(_message("none", "pass", "example.test", "attacker.test"))
    assert not _sender_is_authenticated(_message(None, None))


def test_email_webhook_signature_binds_body_and_fresh_timestamp() -> None:
    secret = b"a-provider-webhook-secret-with-more-than-32-bytes"
    body = b'{"messageId":"id"}'
    now = int(time.time())
    signature = sign_webhook_body(secret, now, body)

    assert verify_webhook_signature(secret, body, signature, now=now)
    assert not verify_webhook_signature(secret, body + b"!", signature, now=now)
    assert not verify_webhook_signature(secret, body, signature, now=now + 301)
    assert not verify_webhook_signature(secret, body, "t=broken,v1=00", now=now)


def test_inbound_email_configuration_requires_valid_domain_and_long_secret() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        inbound_email_domain="Invoices.Example.Test.",
        inbound_email_webhook_secret="a-provider-webhook-secret-with-more-than-32-bytes",
    )
    assert settings.inbound_email_domain == "invoices.example.test"
    assert settings.inbound_email_configured

    disabled = Settings(
        _env_file=None,  # type: ignore[call-arg]
        inbound_email_domain="invoices.example.test",
        inbound_email_webhook_secret="too-short",
    )
    assert not disabled.inbound_email_configured

    with pytest.raises(ValidationError):
        Settings(_env_file=None, inbound_email_domain="not a domain")  # type: ignore[call-arg]


def test_email_without_attachments_is_rejected() -> None:
    with pytest.raises(ValidationError):
        InboundEmailMessage.model_validate(
            {"messageId": "id", "sender": "billing@example.test", "attachments": []}
        )
