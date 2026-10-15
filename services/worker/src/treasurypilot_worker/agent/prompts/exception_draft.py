"""Exception-request drafting prompt (EXCEPTION_DRAFT), v1. Schema: `agent.exception_draft`."""

from treasurypilot_worker.agent.prompts.template import PromptTemplate, Slot

EXCEPTION_DRAFT_TEMPLATE = PromptTemplate(
    version="exception_draft.v1",
    system=(
        "You draft a short justification for the Owner, who decides whether to grant a "
        "one-time exception for a payment above the mandate's per-payment cap. Reply with a "
        "summary, reasons (each text with evidence_ids naming the facts it relies on, taken "
        "from the names of the fields in the facts) and alternatives (other ways to settle "
        "the payment within the mandate). Copy every number exactly as it appears in the "
        "facts and never compute or invent one: the engine already did."
    ),
    instructions="Draft the exception request for these facts.",
    slots=(Slot.trusted("facts"),),
)
