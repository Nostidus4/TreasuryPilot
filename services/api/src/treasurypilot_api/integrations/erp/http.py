"""HTTP client abstraction for ERP providers.

Providers talk to this protocol only, so tests inject a fake and production uses the
stdlib client below. Redirects are refused so credentials never follow one.
"""

from __future__ import annotations

import asyncio
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None
    timeout: float = 20.0


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)


class HttpTransportError(Exception):
    """The request never produced a response (DNS, TLS, timeout, reset)."""


class HttpClient(Protocol):
    async def send(self, request: HttpRequest) -> HttpResponse: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


class UrllibHttpClient:
    """Default client: stdlib urllib in a worker thread (httpx is not a runtime dependency)."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_NoRedirect)

    def _send(self, request: HttpRequest) -> HttpResponse:
        if not request.url.startswith("https://"):
            raise HttpTransportError("ERP requests must use HTTPS")
        prepared = urllib.request.Request(  # noqa: S310 - scheme checked above
            request.url, data=request.body, headers=dict(request.headers), method=request.method
        )
        try:
            with self._opener.open(prepared, timeout=request.timeout) as response:  # noqa: S310
                return HttpResponse(
                    response.status,
                    response.read(),
                    {k.lower(): v for k, v in response.headers.items()},
                )
        except urllib.error.HTTPError as error:
            body = error.read()
            return HttpResponse(error.code, body, {k.lower(): v for k, v in error.headers.items()})
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise HttpTransportError(type(error).__name__) from None

    async def send(self, request: HttpRequest) -> HttpResponse:
        return await asyncio.to_thread(self._send, request)
