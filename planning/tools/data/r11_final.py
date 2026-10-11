"""Final alignment of tickets with the finalized specs of M01, M02, M13–M17, M19 (2026-10-11). Closed tickets are not touched."""
from ._base import TICKETS

def _get(tid): return next(x for x in TICKETS if x["id"] == tid)
def _add(tid, scope=(), ac=(), refs=""):
    t = _get(tid)
    t["scope"] = list(t["scope"]) + list(scope)
    t["ac"] = list(t["ac"]) + list(ac)
    if refs: t["refs"] = t["refs"] + ", " + refs

_add("IDN-002", ["session idle timeout 30 min and absolute 12 h (M01-D2)", "same response for known and unknown emails (M01-D10)"],
     ["A session idle for 31 minutes is rejected", "Requesting a link for an unknown email returns the same response as for a known one"], "M01-D2, M01-D10")
_add("IDN-004", ["SIWE chainId = treasury chain (11155111), nonce 10 min, clock skew ± 2 min (M01-D6)", "Owner capability check: linked address must be an owner of Safe T, at link time and hourly; mismatch shows 'not an on-chain owner' and blocks governance actions (M01-D5)", "refuse unlinking the last signer wallet while signer items are pending (M01-D11)"],
     ["A user with the Owner role whose wallet is not a Safe T owner cannot create governance transactions"], "M01-D5, M01-D6, M01-D11")
_add("TRS-004", ["Safe version check: masterCopy in the allowlisted v1.4.1 singletons and VERSION() == 1.4.1 (M02-D2)", "warning (not error) when T/O1/O2 owner sets or thresholds differ (M02-D6)"],
     ["A Safe of another version is rejected with SAFE_VERSION_UNSUPPORTED"], "M02-D2, M02-D6")
_add("TRS-007", ["coverage also requires the canonical fallback handler; recompute every 10 min and on Safe config events (M02-D3, M02-D7)"], [], "M02-D3, M02-D7")
_add("NTF-002", ["SSE resume with Last-Event-ID, heartbeat every 15 s, clients fall back to 10 s polling when pub/sub is down (M13-D3, M13-D8)", "payloads carry ids only (M13-D4)"],
     ["A reconnecting client with Last-Event-ID receives the missed events"], "M13-D3, M13-D4, M13-D8")
_add("NTF-003", ["at most one Telegram message per user per 10 s, bursts merged (M13-D7)"], [], "M13-D7")
_add("CMP-001", ["screening TTL 24 h; ERROR always fails closed (M14-D2, M14-D3)"], [], "M14-D2, M14-D3")
_add("CMP-002", ["synchronous refresh before PAY with a 5 s timeout when the last result is older than 24 h (M14-D7)"], [], "M14-D7")
_add("AUD-001", ["per-org audit_heads row locked FOR UPDATE to append; canonical JSON (sorted keys, amounts as strings, ISO-8601 UTC) (M15-D1)"], [], "M15-D1")
_add("AUD-003", ["bundle fields per docs/modules/audit §8; signatures stored as hashes only; Confidential data excluded except vendor display name; bundles with an unresolvable tx hash are marked INVALID and not delivered (M15-D5, D6, D9)"],
     ["A bundle never contains a raw signature or a contact field"], "M15-D5, M15-D6, M15-D9")
_add("DEV-006", ["seed uses tUSDC (label TEST), a Guardian Safe with the sentinel, and an accepted fee policy so the demo runs end to end"], [], "PH-2, ADR-017")
_add("DEV-007", ["extra scenarios unexpected-outflow and fee-spike (M19-D5)"], ["unexpected-outflow and fee-spike scenarios run on Anvil"], "M19-D5")
_add("OBS-004", ["metric definitions exactly as docs/modules/observability §3 (M17-D2)"], [], "M17-D2")
_add("OBS-005", ["early-payment gas counted against savings (FEE-2, M17-D4); negative savings reported"], [], "M17-D4, FEE-2")
