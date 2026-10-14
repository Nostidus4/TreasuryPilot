"""Ticket data helpers. Each ticket is defined once here; markdown drafts, the backlog,
the dependency map, GitHub issues and the Excel tracker are all generated from it."""
TICKETS = []

def T(id, title, phase, prio, size, feats, refs, deps, objective, scope, oos, notes, ac, tests,
      split_plan=None, context=None):
    """scope / ac / tests: ';'-separated strings. deps: space-separated ticket ids."""
    TICKETS.append(dict(
        id=id, title=title, phase=phase, prio=prio, size=size, feats=feats, refs=refs,
        deps=deps.split(), objective=objective,
        scope=[s.strip() for s in scope.split(';') if s.strip()],
        oos=oos, notes=notes,
        ac=[s.strip() for s in ac.split(';') if s.strip()],
        tests=[s.strip() for s in tests.split(';') if s.strip()],
        split_plan=split_plan, context=context,
    ))

MODULES = {
 "DEV": ("devex", "DEVEX", "M19", "Developer Experience & Quality"),
 "SC":  ("contracts", "CONTRACTS", "M04", "Smart Contracts"),
 "ENG": ("financial-engine", "ENGINE", "M07", "Financial Engine (py-core)"),
 "POL": ("policy-engine", "POLICY", "M08", "Policy Engine & Attestation"),
 "IDN": ("identity", "IDENTITY", "M01", "Identity & Access"),
 "TRS": ("treasury", "TREASURY", "M02", "Treasury & Chain Configuration"),
 "MDT": ("mandate", "MANDATE", "M03", "Mandate, Payees, Exceptions & Pause"),
 "INV": ("invoices", "INVOICES", "M05", "Invoices & Payment Requests"),
 "CHR": ("chain-reader", "CHAIN", "M06", "Chain Reader & Tx Tracking"),
 "AGT": ("agent", "AGENT", "M09", "AI Agent"),
 "EXE": ("execution", "EXECUTION", "M10", "Orchestration & Execution"),
 "REC": ("reconciliation", "RECON", "M11", "Verification & Reconciliation"),
 "RCV": ("recovery", "RECOVERY", "M12", "Recovery & Exceptions"),
 "NTF": ("notifications", "NOTIFY", "M13", "Notifications"),
 "CMP": ("compliance", "COMPLIANCE", "M14", "Compliance"),
 "AUD": ("audit", "AUDIT", "M15", "Audit & Evidence"),
 "WEB": ("web", "WEB", "M16", "Web Application"),
 "OBS": ("observability", "OBSERVABILITY", "M17", "Observability & Analytics"),
 "ADM": ("admin", "ADMIN", "M18", "Platform Admin & Billing"),
 "DOM": ("domain-evidence", "DOMAIN", "M20", "Domain & Evidence (non-code)"),
}
