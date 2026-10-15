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


# Refusals no retry can fix: the attestation, payload or chain is wrong for this step. The
# operation is marked Abandoned so it never sits in NotSubmitted looking retryable. Other
# refusals (e.g. SIMULATION_REVERTED) stay NotSubmitted with last_error for a later decision.
TERMINAL_REFUSALS = frozenset(
    {
        "ATTESTATION_INVALID",
        "ATTESTATION_EXPIRED",
        "PAYLOAD_MISMATCH",
        "FEE_CAP_EXCEEDED",
        "CHAIN_NOT_ALLOWED",
        "NONCE_REUSED",
    }
)
# Mirrors treasurypilot_api.execution.models.OperationKind (the worker cannot import the api).
_OPERATION_KINDS = frozenset({"PAY", "REFILL", "SWAP", "WITHDRAW", "SUPPLY"})


class SignerRefused(Exception):
    """A typed, definitive signer refusal (ATTESTATION_EXPIRED, FEE_CAP_EXCEEDED, ...)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    @property
    def terminal(self) -> bool:
        return self.code in TERMINAL_REFUSALS


class TreasuryPaused(Exception):
    """The treasury is paused or revoked; no operation is created or signed."""


class SignerMisconfigured(Exception):
    """HTTP 401 from the signer: our shared secret is wrong. A deploy error, not a refusal."""


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
                    status = reply.status
                    try:
                        body = await reply.json(content_type=None)
                    except ValueError:  # non-JSON body: fall back to the status code alone
                        body = None
        except (aiohttp.ClientError, TimeoutError) as error:
            raise SignerUnavailable(type(error).__name__) from error
        if status == 200:
            if isinstance(body, dict):
                return body
            raise SignerUnavailable("MALFORMED_SIGNER_RESPONSE")
        code = str(body.get("code")) if isinstance(body, dict) else "SIGNER_ERROR"
        if status == 401:
            raise SignerMisconfigured("signer rejected the shared secret")
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


def _validate(step: StepExecution) -> None:
    """Reject a step whose fields disagree with the request the signer will act on."""

    request = step.sign_request
    if step.kind not in _OPERATION_KINDS:
        raise ValueError(f"unknown operation kind {step.kind!r}")
    if str(request.get("treasuryId")) != str(step.treasury_id):
        raise ValueError("sign_request treasuryId does not match the step treasury")
    try:
        signer_step_id = request["plan"]["steps"][request["stepSeq"]]["stepId"]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("sign_request has no plan step at stepSeq") from error
    if str(signer_step_id).lower().removeprefix("0x") != step.step_id.hex():
        raise ValueError("step_id does not match the signer's plan step id")


def _parse_reply(signed: dict[str, Any]) -> tuple[bytes, int, bytes]:
    tx_hash = bytes.fromhex(str(signed["txHash"]).removeprefix("0x"))
    sender = bytes.fromhex(str(signed["from"]).removeprefix("0x"))
    nonce = int(signed["nonce"])
    if len(tx_hash) != 32 or len(sender) != 20 or nonce < 0:
        raise ValueError("bad txHash, from or nonce length")
    return tx_hash, nonce, sender


_PAUSED_SQL = (
    "SELECT (t.status IN ('Paused', 'Revoked') OR COALESCE(bp.paused, false)) AS paused "
    "FROM treasuries t LEFT JOIN backend_pause bp ON bp.treasury_id = t.id WHERE t.id = $1"
)


async def _require_not_paused(connection: asyncpg.Connection, treasury_id: UUID) -> None:
    if await connection.fetchval(_PAUSED_SQL, treasury_id):
        raise TreasuryPaused(str(treasury_id))


async def execute_step(
    pool: asyncpg.Pool, signer: SignerClient, step: StepExecution
) -> StepOutcome:
    """Record, sign and hand one step to the tracker. Safe to re-run at any point.

    A terminal refusal (``TERMINAL_REFUSALS``) marks the operation Abandoned and re-raises.
    ``plan_steps`` is append-only and carries no status, so there is no step state to update here;
    EXE-008 owns plan-level progress.
    """

    _validate(step)
    async with pool.acquire() as connection:
        # Transaction 1: the outbox row exists (and the attempt is counted) before any signing.
        async with connection.transaction():
            await _require_not_paused(connection, step.treasury_id)
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

        # A pause can land between transaction 1 and here; the operation stays NotSubmitted.
        await _require_not_paused(connection, step.treasury_id)
        try:
            tx_hash, nonce, sender = _parse_reply(await signer.sign_and_send(step.sign_request))
        except SignerRefused as error:
            await _record_failure(connection, operation_id, error.code, abandon=error.terminal)
            raise
        except SignerUnavailable as error:
            await _record_failure(connection, operation_id, str(error))
            raise
        except (KeyError, TypeError, ValueError) as error:
            await _record_failure(connection, operation_id, "MALFORMED_SIGNER_RESPONSE")
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


async def _record_failure(
    connection: asyncpg.Connection, operation_id: UUID, error: str, *, abandon: bool = False
) -> None:
    # Conditional: a concurrent run may already have moved the operation past NotSubmitted.
    await connection.execute(
        "UPDATE operations SET last_error = $2, status = CASE WHEN $3 THEN "
        "'Abandoned'::operation_status ELSE status END "
        "WHERE id = $1 AND status = 'NotSubmitted'",
        operation_id,
        error,
        abandon,
    )


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
