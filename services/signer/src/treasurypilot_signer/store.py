from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg  # type: ignore[import-untyped]


class NonceAlreadyBound(Exception):
    """The attestation nonce was previously bound to another plan hash."""


class StepAlreadyUsed(Exception):
    """The attested step was previously used with different transaction data."""


@dataclass(frozen=True)
class ReservedNonce:
    transaction_nonce: int
    replacement: bool


class SignerStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def reserve(
        self,
        *,
        attestation_nonce: int,
        plan_hash: bytes,
        step_id: bytes,
        payload_hash: bytes,
        executor: bytes,
        pending_nonce: int,
    ) -> ReservedNonce:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                # Serialize nonce allocation per EOA, including two different plans that
                # reach the signer concurrently.
                await connection.execute(
                    "INSERT INTO signer.nonces (address, next_nonce) VALUES ($1, $2) "
                    "ON CONFLICT (address) DO NOTHING",
                    executor,
                    pending_nonce,
                )
                lane = await connection.fetchrow(
                    "SELECT next_nonce FROM signer.nonces WHERE address = $1 FOR UPDATE", executor
                )
                await connection.execute(
                    "INSERT INTO signer.nonce_bindings (nonce, plan_hash) VALUES ($1, $2) "
                    "ON CONFLICT (nonce) DO NOTHING",
                    attestation_nonce,
                    plan_hash,
                )
                binding = await connection.fetchrow(
                    "SELECT plan_hash FROM signer.nonce_bindings WHERE nonce = $1 FOR UPDATE",
                    attestation_nonce,
                )
                if binding is not None and bytes(binding["plan_hash"]) != plan_hash:
                    raise NonceAlreadyBound
                existing = await connection.fetchrow(
                    "SELECT plan_hash, payload_hash, transaction_nonce "
                    "FROM signer.attestation_uses WHERE nonce = $1 AND step_id = $2 FOR UPDATE",
                    attestation_nonce,
                    step_id,
                )
                if existing is not None:
                    if (
                        bytes(existing["plan_hash"]) != plan_hash
                        or bytes(existing["payload_hash"]) != payload_hash
                    ):
                        raise StepAlreadyUsed
                    return ReservedNonce(int(existing["transaction_nonce"]), True)

                transaction_nonce = max(pending_nonce, int(lane["next_nonce"]))
                await connection.execute(
                    "UPDATE signer.nonces SET next_nonce = $2, updated_at = $3 WHERE address = $1",
                    executor,
                    transaction_nonce + 1,
                    datetime.now(UTC),
                )
                await connection.execute(
                    "INSERT INTO signer.attestation_uses "
                    "(nonce, plan_hash, step_id, payload_hash, executor, transaction_nonce, first_signed_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    attestation_nonce,
                    plan_hash,
                    step_id,
                    payload_hash,
                    executor,
                    transaction_nonce,
                    datetime.now(UTC),
                )
                return ReservedNonce(transaction_nonce, False)
