from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from typing import Any

import aiohttp


class RpcFailure(RuntimeError):
    def __init__(self, method: str, *, reverted: bool = False, already_known: bool = False) -> None:
        super().__init__(method)
        self.reverted = reverted
        self.already_known = already_known


class JsonRpc:
    """Small RPC client that never includes an RPC URL or response body in errors."""

    def __init__(self, url: str, *, timeout: float = 10) -> None:
        if not url:
            raise ValueError("CHAIN_RPC_URL is required")
        self._url = url
        self._ids = itertools.count(1)
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def call(self, method: str, params: Sequence[Any]) -> Any:
        request_id = next(self._ids)
        try:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(timeout=self._timeout)
            async with self._session.post(
                self._url,
                json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            ) as response:
                if response.status != 200:
                    raise RpcFailure(method)
                body: Mapping[str, Any] = await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as error:
            raise RpcFailure(method) from error
        if "error" in body:
            response_error = body["error"]
            message = (
                str(response_error.get("message", "")).lower()
                if isinstance(response_error, Mapping)
                else ""
            )
            raise RpcFailure(
                method,
                reverted="revert" in message,
                already_known="already known" in message or "known transaction" in message,
            )
        if "result" not in body:
            raise RpcFailure(method)
        return body["result"]
