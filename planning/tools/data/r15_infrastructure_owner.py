"""Record the infrastructure handoff requested by Phuc on 2026-10-14."""

from ._base import TICKETS

ticket = next(item for item in TICKETS if item["id"] == "DOM-001")
ticket.update(
    title="Verify Ethereum Sepolia infrastructure (owner: Nostidus4)",
    notes="Decision taken 2026-10-11 (PH-1): Ethereum Sepolia. This ticket now records the verification. Ownership transferred on 2026-10-14 from longhuynh55 (Phuc) to Nostidus4 (Tan), the repository owner responsible for the project's infrastructure access. Nostidus4 owns RPC/API/service configuration, infrastructure verification and recording the Safe transaction evidence; longhuynh55 supports contract integration. The acceptance criteria and deployment dependencies remain unchanged.",
)
