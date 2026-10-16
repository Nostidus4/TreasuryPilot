"""Fake HTTP for ERP adapter tests (shared by Xero, QuickBooks, NetSuite): no network is opened."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from treasurypilot_api.integrations.erp.http import HttpRequest, HttpResponse, HttpTransportError


def reply(status: int, body: Any = None, **headers: str) -> HttpResponse:
    raw = b"" if body is None else json.dumps(body).encode()
    return HttpResponse(status, raw, {k.lower().replace("_", "-"): v for k, v in headers.items()})


class FakeHttp:
    """Matches ``(METHOD, url-prefix)`` routes in order and records every request."""

    def __init__(self) -> None:
        self.requests: list[HttpRequest] = []
        self._routes: list[tuple[str, str, Callable[[HttpRequest], HttpResponse | Exception]]] = []

    def on(
        self, method: str, prefix: str, response: HttpResponse | Exception | Callable[..., Any]
    ) -> None:
        handler = response if callable(response) else (lambda _r, value=response: value)
        self._routes.append((method, prefix, handler))

    async def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        for method, prefix, handler in self._routes:
            if request.method == method and request.url.startswith(prefix):
                result = handler(request)
                if isinstance(result, Exception):
                    raise result
                return result
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    def calls(self, method: str, prefix: str) -> list[HttpRequest]:
        return [r for r in self.requests if r.method == method and r.url.startswith(prefix)]


def transport_error() -> HttpTransportError:
    return HttpTransportError("TimeoutError")
