from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable


class ConsoleMagicLinkSender:
    """Intentional local-only delivery adapter that prints a usable one-time link."""

    def __init__(self, write: Callable[[str], object] | None = None) -> None:
        self._write = write or (lambda message: print(message, file=sys.stderr))

    async def send_magic_link(self, *, email: str, url: str) -> None:
        # This is a developer delivery channel, not application logging. It is selected only
        # for TP_ENVIRONMENT=local; deployed environments are forced onto Resend. Avoid echoing
        # the recipient even locally, but provide the credential so the sign-in flow is usable.
        self._write(f"TreasuryPilot local magic link (secret; do not share): {url}")


class ResendMagicLinkSender:
    ENDPOINT = "https://api.resend.com/emails"

    def __init__(self, *, api_key: str, from_email: str, timeout_seconds: float = 10.0) -> None:
        if not api_key or not from_email:
            raise ValueError("Resend API key and sender address are required")
        self._api_key = api_key
        self._from_email = from_email
        self._timeout_seconds = timeout_seconds

    async def send_magic_link(self, *, email: str, url: str) -> None:
        await asyncio.to_thread(self._send, email, url)

    def _send(self, email: str, url: str) -> None:
        body = json.dumps(
            {
                "from": self._from_email,
                "to": [email],
                "subject": "Sign in to TreasuryPilot",
                "html": (
                    "<p>Use this one-time link to sign in to TreasuryPilot.</p>"
                    f'<p><a href="{url}">Sign in</a></p>'
                    "<p>This link expires in 15 minutes.</p>"
                ),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.ENDPOINT,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "TreasuryPilot/1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError("Resend rejected the email request")
        except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            # Provider responses can echo recipients or request data. Do not propagate them.
            raise RuntimeError("Resend delivery failed") from exc
