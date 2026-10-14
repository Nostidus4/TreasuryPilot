"""Email templates and Resend transport for in-app notifications."""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from urllib.parse import quote


@dataclass(frozen=True, slots=True)
class EmailNotification:
    title: str
    body: str
    link: str
    severity: str


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    html: str
    text: str


def render_notification_email(
    notifications: tuple[EmailNotification, ...], *, app_base_url: str, digest: bool = False
) -> RenderedEmail:
    """Render minimal, escaped email content without adding event payload details."""
    if not notifications:
        raise ValueError("an email requires at least one notification")
    base = app_base_url.rstrip("/")
    items: list[str] = []
    text_items: list[str] = []
    for item in notifications:
        url = f"{base}{item.link}"
        items.append(
            "<li><strong>"
            + html.escape(item.title)
            + "</strong><p>"
            + html.escape(item.body)
            + '</p><p><a href="'
            + html.escape(url, quote=True)
            + '">Open TreasuryPilot</a></p></li>'
        )
        text_items.append(f"{item.title}\n{item.body}\n{url}")
    subject = (
        "TreasuryPilot daily digest" if digest else f"[TreasuryPilot] {notifications[0].title}"
    )
    intro = (
        "Your TreasuryPilot notification digest:"
        if digest
        else "You have a new TreasuryPilot notification."
    )
    return RenderedEmail(
        subject=subject,
        html=f"<p>{html.escape(intro)}</p><ul>{''.join(items)}</ul>",
        text=f"{intro}\n\n" + "\n\n".join(text_items),
    )


def unsubscribe_signature(user_id: uuid.UUID, secret: str) -> str:
    if len(secret.encode()) < 32:
        raise ValueError("notification email signing secret must contain at least 32 bytes")
    return hmac.new(secret.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()


def unsubscribe_url(*, api_base_url: str, user_id: uuid.UUID, secret: str) -> str:
    signature = unsubscribe_signature(user_id, secret)
    return (
        f"{api_base_url.rstrip('/')}/v1/me/notifications/email/unsubscribe"
        f"?user_id={quote(str(user_id))}&signature={quote(signature)}"
    )


def send_resend_email(
    *,
    api_key: str,
    from_email: str,
    recipient: str,
    message: RenderedEmail,
    unsubscribe_url_value: str,
    timeout_seconds: float = 10.0,
) -> None:
    """Send through Resend. Provider error bodies are deliberately not surfaced/logged."""
    if not api_key or not from_email:
        raise ValueError("Resend API key and sender address are required")
    body = json.dumps(
        {
            "from": from_email,
            "to": [recipient],
            "subject": message.subject,
            "html": message.html,
            "text": message.text,
            "headers": {
                "List-Unsubscribe": f"<{unsubscribe_url_value}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "TreasuryPilot/1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError("Resend rejected the email request")
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise RuntimeError("Resend notification delivery failed") from exc
