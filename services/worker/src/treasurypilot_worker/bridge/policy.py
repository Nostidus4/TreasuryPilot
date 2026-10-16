"""Bridge policy: allowlisted routes, separate limits, timeout (F-067). Fails closed when unset."""

from __future__ import annotations

from dataclasses import dataclass

from treasurypilot_worker.bridge.adapter import BridgeRoute
from treasurypilot_worker.config import Settings


class BridgeRejected(Exception):
    """A deterministic policy refusal; ``code`` is stable. Nothing was sent."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class BridgePolicy:
    allowed_routes: frozenset[BridgeRoute] = frozenset()
    max_transfer_amount: int = 0  # per transfer, base units; 0 disables bridging
    max_in_flight_amount: int = 0  # across open transfers of one source treasury
    timeout_seconds: int = 3600

    def check(self, route: BridgeRoute, amount: int, min_amount_out: int, in_flight: int) -> None:
        if self.max_transfer_amount <= 0 or self.max_in_flight_amount <= 0:
            raise BridgeRejected("BRIDGING_DISABLED")
        if route not in self.allowed_routes:
            raise BridgeRejected("ROUTE_NOT_ALLOWLISTED")
        if amount <= 0 or min_amount_out <= 0 or min_amount_out > amount:
            raise BridgeRejected("INVALID_AMOUNT")
        if amount > self.max_transfer_amount:
            raise BridgeRejected("TRANSFER_LIMIT_EXCEEDED")
        if in_flight + amount > self.max_in_flight_amount:
            raise BridgeRejected("IN_FLIGHT_LIMIT_EXCEEDED")


def parse_routes(spec: str) -> frozenset[BridgeRoute]:
    """``provider:srcChainId:dstChainId`` entries separated by commas."""

    routes: set[BridgeRoute] = set()
    for entry in filter(None, (part.strip() for part in spec.split(","))):
        provider, source, destination = entry.split(":")
        routes.add(BridgeRoute(provider, int(source), int(destination)))
    return frozenset(routes)


def policy_from_settings(settings: Settings) -> BridgePolicy:
    return BridgePolicy(
        allowed_routes=parse_routes(settings.bridge_allowed_routes),
        max_transfer_amount=settings.bridge_max_transfer_amount,
        max_in_flight_amount=settings.bridge_max_in_flight_amount,
        timeout_seconds=settings.bridge_timeout_seconds,
    )
