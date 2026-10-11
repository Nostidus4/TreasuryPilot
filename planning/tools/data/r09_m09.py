"""Review of M09 defaults with the project lead, 2026-10-11."""
from ._base import TICKETS

def _rev(tid, **kw):
    t = next(x for x in TICKETS if x["id"] == tid)
    for k, v in kw.items():
        if k in ("scope", "ac", "tests") and isinstance(v, str): v = [s.strip() for s in v.split(";") if s.strip()]
        t[k] = v

t = next(x for x in TICKETS if x["id"] == "AGT-008")
t["scope"] = t["scope"] + ["trigger rule (M09-D6): full proposal only when ≥ 2 eligible requests or terms/deferrals matter", "EXPLAIN task for single plain requests: short rationale of the deterministic plan on the cheap model (Haiku), numbers post-checked, shown in the Why panel"]
t["ac"] = t["ac"] + ["A single plain request gets an EXPLAIN text and no proposal call", "EXPLAIN text containing a number not in the plan is discarded"]
t["refs"] = t["refs"] + ", M09-D6"
