"""Review of M11 defaults with the project lead, 2026-10-11."""
from ._base import TICKETS
t = next(x for x in TICKETS if x["id"] == "REC-005")
t["scope"] = ["Task that attests as soon as the request is Paid and the PAY block is finalized (M11-D8, does not wait for matching)"] + t["scope"][1:]
t["refs"] = t["refs"] + ", M11-D8"
