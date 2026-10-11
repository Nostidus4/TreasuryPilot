"""Review of M10 defaults with the project lead, 2026-10-11. Applied after r07_specs."""
from ._base import TICKETS

def _rev(tid, **kw):
    t = next(x for x in TICKETS if x["id"] == tid)
    for k, v in kw.items():
        if k in ("scope", "ac", "tests") and isinstance(v, str): v = [s.strip() for s in v.split(";") if s.strip()]
        if k == "deps": v = v.split()
        t[k] = v

_rev("EXE-003", refs="FR-501–503, M10-D1",
  scope="Scheduling cycle every 15 min and on events;execution cycle every 60 s as a safety net;event hooks (approval, exception granted, resume, inflow, payee Active, fee accepted) enqueue an execution cycle immediately;eligibility per docs/modules/execution §8.1 (today's schedule + window open);gates: backend pause flag, mandate active, coverage COMPLETE (or acknowledged), no Unknown operation, no Executing plan;non-blocking per-treasury advisory lock",
  ac="An eligible request starts executing within 5 s of its approval with no user action;Two events at once run one cycle (lock);A paused treasury or one with an Unknown operation is skipped with a logged reason")
_rev("EXE-005", notes="M08-D9: writes only to its own schema. M10-D7: executor keys are resolved by treasury_id (M1 maps every treasury to one shared executor). No other endpoints.")
_rev("EXE-006", scope="Encrypted JSON keystores mounted read-only, mapped by treasury_id in signer config (M1: one shared executor);password from a Docker secret;health endpoint returns executor addresses and gas balances only",
  ac="The service refuses to start without the keystore or with a wrong password;A treasury without a configured key is refused with NOT_CONFIGURED;The private key never appears in logs or the health response")
