"""Bridge provider adapter interface and a deterministic fake for tests (EXE-L03).

The adapter is the only code that talks to a bridge provider. ``send`` must be idempotent on
``idempotency_key`` at the provider, but the service never relies on that: it calls ``send`` at
most once per transfer and treats any ambiguous failure as Unknown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class BridgeRoute:
    provider: str
    source_chain_id: int
    destination_chain_id: int


@dataclass(frozen=True)
class BridgeSendRequest:
    transfer_id: UUID
    idempotency_key: str
    route: BridgeRoute
    amount: int  # base units on the source chain
    min_amount_out: int  # base units the destination must receive
    recipient: str  # destination treasury Safe address, 0x-hex


class ProviderState(StrEnum):
    NOT_FOUND = "NOT_FOUND"  # the provider has no record of this idempotency key
    IN_TRANSIT = "IN_TRANSIT"
    ARRIVED = "ARRIVED"
    FAILED = "FAILED"  # definitive: refunded or never executed


@dataclass(frozen=True)
class ProviderStatus:
    state: ProviderState
    amount_out: int | None = None
    ref: str | None = None


class BridgeRefused(Exception):
    """The provider definitively refused the transfer; nothing was sent."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class BridgeUnavailable(Exception):
    """Timeout or transport failure: the provider may or may not have accepted the transfer."""


class BridgeAdapter(Protocol):
    async def send(self, request: BridgeSendRequest) -> str:
        """Submit the transfer and return the provider reference."""
        ...

    async def status(self, idempotency_key: str) -> ProviderStatus: ...


class BridgeNotConfigured(Exception):
    """No adapter is configured for the provider (real endpoints are deployment config)."""


@dataclass
class FakeBridgeAdapter:
    """Deterministic in-memory provider. ``send_calls`` counts every ``send`` per key."""

    fail_send: str | None = None  # "refuse" | "timeout_before_accept" | "timeout_after_accept"
    send_calls: dict[str, int] = field(default_factory=dict)
    _transfers: dict[str, ProviderStatus] = field(default_factory=dict)
    status_error: bool = False

    async def send(self, request: BridgeSendRequest) -> str:
        key = request.idempotency_key
        self.send_calls[key] = self.send_calls.get(key, 0) + 1
        if self.fail_send == "refuse":
            raise BridgeRefused("ROUTE_UNAVAILABLE")
        if self.fail_send == "timeout_before_accept":
            raise BridgeUnavailable("timeout")
        ref = f"fake-{key}"
        self._transfers.setdefault(key, ProviderStatus(ProviderState.IN_TRANSIT, ref=ref))
        if self.fail_send == "timeout_after_accept":
            raise BridgeUnavailable("timeout")
        return ref

    async def status(self, idempotency_key: str) -> ProviderStatus:
        if self.status_error:
            raise BridgeUnavailable("status timeout")
        return self._transfers.get(idempotency_key, ProviderStatus(ProviderState.NOT_FOUND))

    def arrive(self, idempotency_key: str, amount_out: int) -> None:
        ref = self._transfers[idempotency_key].ref
        self._transfers[idempotency_key] = ProviderStatus(ProviderState.ARRIVED, amount_out, ref)

    def fail(self, idempotency_key: str) -> None:
        ref = self._transfers[idempotency_key].ref
        self._transfers[idempotency_key] = ProviderStatus(ProviderState.FAILED, None, ref)


def adapter_for(provider: str) -> BridgeAdapter:
    """Resolve a provider adapter. No real provider is wired yet: fail closed."""

    raise BridgeNotConfigured(provider)
