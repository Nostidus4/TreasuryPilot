"""Persist the current borrow proposal of a treasury (ENG-014, F-069, TRS-009).

When a liquidity cycle ends in ``INSUFFICIENT_LIQUIDITY`` the engine estimates a borrow for the
shortfall (``propose_borrow``). The estimate is advisory and never a transaction (BR-044); it is
stored so the dashboard can link to it. At most one proposal per treasury is ``Proposed``: a
different shortfall supersedes it, and a cycle with no shortfall supersedes it too, since it no
longer describes the treasury.
"""

from __future__ import annotations

import uuid

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.domain import BorrowProposal, Snapshot
from treasurypilot_core.engine.liquidity import propose_borrow
from treasurypilot_core.ids import uuid7
from treasurypilot_core.money import BaseUnits

# The repayment horizon of the estimate; the dashboard compares 7 days of cost.
BORROW_HORIZON_DAYS = 7


def estimate_borrow(snapshot: Snapshot, shortfall: BaseUnits) -> tuple[BorrowProposal, int]:
    """The engine's estimate for ``shortfall`` and the day the loan would be repaid."""

    due_day = snapshot.day + BORROW_HORIZON_DAYS
    return propose_borrow(snapshot, shortfall, due_day), due_day


async def record_borrow_proposal(
    connection: asyncpg.Connection,
    org_id: uuid.UUID,
    treasury_id: uuid.UUID,
    snapshot: Snapshot,
    shortfall: BaseUnits,
    *,
    snapshot_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Store the estimate for ``shortfall`` as the treasury's open proposal and return its id.

    The same shortfall refreshes the open proposal in place (its id stays stable for a reader
    that has it open); a different one supersedes it with a new proposal.
    """

    proposal, due_day = estimate_borrow(snapshot, shortfall)
    values = (
        int(proposal.amount),
        int(proposal.cost_to_repayment),
        int(proposal.withdraw_cost),
        proposal.health_factor_before,
        proposal.health_factor_after,
        proposal.reason,
        due_day,
        snapshot_id,
    )
    async with connection.transaction():
        refreshed: uuid.UUID | None = await connection.fetchval(
            "UPDATE borrow_proposals SET amount = $3, cost_to_repayment = $4, withdraw_cost = $5, "
            "health_factor_before = $6, health_factor_after = $7, reason = $8, due_day = $9, "
            "snapshot_id = $10, updated_at = now() "
            "WHERE treasury_id = $1 AND status = 'Proposed' AND shortfall = $2 RETURNING id",
            treasury_id,
            int(shortfall),
            *values,
        )
        if refreshed is not None:
            return refreshed
        await connection.execute(
            "UPDATE borrow_proposals SET status = 'Superseded', updated_at = now() "
            "WHERE treasury_id = $1 AND status = 'Proposed'",
            treasury_id,
        )
        proposal_id = uuid7()
        await connection.execute(
            "INSERT INTO borrow_proposals (id, org_id, treasury_id, shortfall, amount, "
            "cost_to_repayment, withdraw_cost, health_factor_before, health_factor_after, "
            "reason, due_day, snapshot_id) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, "
            "$12)",
            proposal_id,
            org_id,
            treasury_id,
            int(shortfall),
            *values,
        )
        return proposal_id


async def clear_borrow_proposal(connection: asyncpg.Connection, treasury_id: uuid.UUID) -> None:
    """Supersede the open proposal: the cycle found no shortfall to cover."""

    await connection.execute(
        "UPDATE borrow_proposals SET status = 'Superseded', updated_at = now() "
        "WHERE treasury_id = $1 AND status = 'Proposed'",
        treasury_id,
    )
