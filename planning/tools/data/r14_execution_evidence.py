"""Separate the published competition requirement from optional clarification."""

from ._base import TICKETS

ticket = next(item for item in TICKETS if item["id"] == "DOM-003")
ticket.update(
    title="Document execution evidence requirements and the Sepolia assumption",
    refs="OQ-01, Submission item 06, NFR-CMP-01, ADR-012, ADR-019",
    objective="Record the published on-chain execution-evidence requirement and distinguish it from the team's network choice.",
    context_override="This documentation ticket records the published execution-evidence wording and the team's network interpretation. Optional organizer clarification does not block implementation or submission.",
    scope=[
        "Cite PBCSF Appendix 2, page 3, submission checklist item 06 in OPEN_QUESTIONS.md",
        "Record that on-chain submissions require real on-chain transaction hashes, while the checklist does not specify testnet or mainnet",
        "Record Ethereum Sepolia as the team's working choice under ADR-012/019 and NFR-CMP-01, not as explicit organizer confirmation",
        "Keep organizer clarification optional and non-blocking; record an actual reply only if one is obtained",
    ],
    oos="Sending an organizer email, public deployment and collecting transaction hashes are not required to complete this documentation ticket. Actual deployment/evidence stays with DOM-001/002 and the relevant execution tickets.",
    notes="Checked 2026-10-14 against the published PBCSF rules. PH-3 records the team's interpretation, not an organizer reply. No mandatory email or 14/10 reply deadline; no automatic switch to mainnet. Source: [PBCSF Appendix 2, page 3](https://www.its.ac.id/international/wp-content/uploads/sites/66/2026/10/PBCSF-Appendix-2-Problem-Description-and-Competition-Rules-for-International-Track.pdf).",
    ac=[
        "OPEN_QUESTIONS.md cites the source, page and checklist item with the exact transaction-hash requirement",
        "The official requirement and the team's Sepolia assumption are explicitly distinguished",
        "No mandatory organizer email or reply blocks development or submission in this ticket",
        "Any future network restriction is handled through a reviewed decision instead of an undocumented mainnet switch",
    ],
)
