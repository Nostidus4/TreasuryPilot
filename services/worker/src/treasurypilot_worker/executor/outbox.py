"""Outbox executor for one plan step (EXE-007, M10 §7.3 steps 2-3).

The operation row is committed before the signer is called, and the signer's tx hash is saved in
one transaction with the ``Submitted`` status. A crash anywhere in between is recovered by running
the same step again: the signer keys its reservation by ``step_id`` and replays the original signed
transaction, so a retry yields the same hash and nonce instead of a second payment.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import aiohttp
import asyncpg  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

_SIGNER_TIMEOUT = aiohttp.ClientTimeout(total=30)


class SignerRefused(Exception):
    """A typed, definitive signer refusal (ATTESTATION_EXPIRED, FEE_CAP_EXCEEDED, ...)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SignerUnavailable(Exception):
    """Transport failure or 5xx; the outcome is unknown, so the same step may be retried."""


class SignerClient(Protocol):
    async def sign_and_send(self, request: dict[str, Any]) -> dict[str, Any]: ...


class HttpSignerClient:
    def __init__(self, base_url: str, shared_secret: str) -> None:
        self._url = base_url.rstrip("/") + "/sign-and-send"
        self._headers = {"X-Signer-Secret": shared_secret}

    async def sign_and_send(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            async with aiohttp.ClientSession(timeout=_SIGNER_TIMEOUT) as session:
                async with session.post(self._url, json=request, headers=self._headers) as reply:
                    body = await reply.json(content_type=None)
                    status = reply.status
        except (aiohttp.ClientError, TimeoutError, ValueError) as error:
            raise SignerUnavailable(type(error).__name__) from error
        if status == 200 and isinstance(body, dict):
            return body
        code = str(body.get("code")) if isinstance(body, dict) else "SIGNER_ERROR"
        if status >= 500:
            raise SignerUnavailable(code)
        raise SignerRefused(code)


@dataclass(frozen=True)
class StepExecution:
    """One attested plan step, ready for the signer. ``sign_request`` is the /sign-and-send body."""

    treasury_id: UUID
    request_id: UUID
    plan_step_id: UUID
    step_id: bytes
    kind: str  # operation_kind: PAY | REFILL | SWAP | WITHDRAW | SUPPLY
    chain_id: int
    sign_request: dict[str, Any]


@dataclass(frozen=True)
class StepOutcome:
    operation_id: UUID
    status: str
    tx_hash: str | None = None
    nonce: int | None = None


async def execute_step(
    pool: asyncpg.Pool, signer: SignerClient, step: StepExecution
) -> StepOutcome:
    """Record, sign and hand one step to the tracker. Safe to re-run at any point."""

    async with pool.acquire() as connection:
        # Transaction 1: the outbox row exists (and the attempt is counted) before any signing.
        async with connection.transaction():
            await connection.execute(
                "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, "
                "kind, payload, idempotency_key) VALUES (gen_random_uuid(), $1, $2, $3, $4, "
                "$5::operation_kind, $6::jsonb, $7) ON CONFLICT (step_id) DO NOTHING",
                step.treasury_id,
                step.plan_step_id,
                step.request_id,
                step.step_id,
                step.kind,
                json.dumps(step.sign_request["payload"]),
                "step:" + step.step_id.hex(),
            )
            operation = await connection.fetchrow(
                "SELECT id, treasury_id, status FROM operations WHERE step_id = $1 FOR UPDATE",
                step.step_id,
            )
            if operation["treasury_id"] != step.treasury_id:
                raise ValueError("step_id belongs to another treasury")
            if operation["status"] != "NotSubmitted":
                return await _existing_outcome(connection, operation)
            await connection.execute(
                "UPDATE operations SET attempts = attempts + 1 WHERE id = $1", operation["id"]
            )
        operation_id: UUID = operation["id"]

        try:
            signed = await signer.sign_and_send(step.sign_request)
            tx_hash = bytes.fromhex(str(signed["txHash"]).removeprefix("0x"))
            nonce, sender = int(signed["nonce"]), bytes.fromhex(str(signed["from"])[2:])
        except SignerRefused as error:
            await connection.execute(
                "UPDATE operations SET last_error = $2 WHERE id = $1", operation_id, error.code
            )
            raise
        except SignerUnavailable as error:
            await connection.execute(
                "UPDATE operations SET last_error = $2 WHERE id = $1", operation_id, str(error)
            )
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise SignerUnavailable("MALFORMED_SIGNER_RESPONSE") from error

        # Transaction 2: tx hash + nonce and the Submitted status commit together.
        async with connection.transaction():
            await connection.execute(
                "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, "
                "from_address) VALUES (gen_random_uuid(), $1, $2, $3, $4, $5) "
                "ON CONFLICT (chain_id, tx_hash) DO NOTHING",
                operation_id,
                step.chain_id,
                tx_hash,
                nonce,
                sender,
            )
            await connection.execute(
                "UPDATE operations SET status = 'Submitted', last_error = NULL "
                "WHERE id = $1 AND status = 'NotSubmitted'",
                operation_id,
            )
    return StepOutcome(operation_id, "Submitted", "0x" + tx_hash.hex(), nonce)


async def _existing_outcome(
    connection: asyncpg.Connection, operation: asyncpg.Record
) -> StepOutcome:
    row = await connection.fetchrow(
        "SELECT tx_hash, nonce FROM transactions WHERE operation_id = $1 "
        "ORDER BY submitted_at LIMIT 1",
        operation["id"],
    )
    logger.info("operation %s already %s; signer not called", operation["id"], operation["status"])
    if row is None:
        return StepOutcome(operation["id"], operation["status"])
    return StepOutcome(
        operation["id"], operation["status"], "0x" + bytes(row["tx_hash"]).hex(), int(row["nonce"])
    )
