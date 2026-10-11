"""Revisions from the M06 (chain reader) grilling round, 2026-10-11. Applied after r05_m03."""
from ._base import TICKETS, T

def _rev(tid, **kw):
    t = next(x for x in TICKETS if x["id"] == tid)
    for k, v in kw.items():
        if k in ("scope", "ac", "tests") and isinstance(v, str): v = [s.strip() for s in v.split(";") if s.strip()]
        if k == "deps": v = v.split()
        t[k] = v

D = "docs/modules/chain-reader"
_rev("CHR-001", refs="NFR-REL-04, PH-8, M06-D1",
  scope="web3.py wrapper with ordered providers (Alchemy primary, public Sepolia secondary), 4 s timeout, 2 retries each, failover;crosscheck_receipt on the secondary;provider health tracking in rpc_health;typed errors (RpcUnavailable);fee_history helper for EXE-012;safe_config reader",
  ac="With the first provider down, calls succeed through the second;With all down, RpcUnavailable is raised and nothing returns a default value;crosscheck_receipt returns Mismatch when the fake secondary returns a different block hash")
_rev("CHR-002",
  scope=f"Multicall3 aggregate3 pinned to one block with the read set of {D} §8.1;snapshot record with purpose, block number, hash, timestamp, provider, coverage and missing fields;freshness helper (≤ 30 s and ≤ 2 blocks);dashboard snapshot every 60 s with 7-day pruning",
  ac="All values in a snapshot come from the same block;A failed sub-call is listed in missing and the snapshot is stored;is_fresh rejects a snapshot 3 blocks behind head")
_rev("CHR-003", refs="BR-053, BR-060, FR-601, PH-5, M06-D1, M06-D5",
  scope=f"Celery task every 6 s;status per {D} §5 (Submitted, Pending, Confirmed, Reverted, Dropped, Unknown);Confirmed at 3 confirmations and secondary cross-check Match;Unknown after 10 min without receipt and not in mempool;replacement linking by (from, nonce);revert selector decoded via POL-001;day attribution by mined block timestamp",
  ac="A transaction is Confirmed only after 3 confirmations and a matching cross-check;A cross-check mismatch never yields Confirmed;A timeout sets Unknown, never Failed;A replacement with the same nonce marks the original Dropped and links it")
_rev("CHR-004",
  scope="Store block hash per confirmation and per event;re-scan the last 64 blocks every cycle;demote Confirmed/Reverted to Pending when the block hash changes;mark observed events removed and call handlers' removed callback")
_rev("CHR-005", refs="FR-510, PH-6, M06-D6, M06-D9",
  scope=f"Cursor-based eth_getLogs reader per stream (MODULE, SAFE_CONFIG, SAFE_EXEC) per {D} §8.3 with 64-block re-scan and ≤ 2,000-block chunks;exact address filters;observed_events and index_cursors;subscriber registry used by M03/M05/M11 handlers;Safe config events trigger coverage recompute",
  ac="Re-reading the same range creates no duplicates;PayeeAdded, Paused, ExceptionGranted, RequestCancelled and ExecutionSuccess events update application state;Logs from an unrelated contract emitting the same topics are ignored;A ChangedGuard event recomputes coverage")
T("CHR-006","Index treasury token movements and alert on unexpected outflows","M1","P0","S","F-050","BR-069, FR-419, M06-D2","CHR-005 EXE-001",
  "Know at once when money leaves a treasury wallet outside the agent.",
  f"TOKEN stream: asset Transfer logs with from or to in {{T, O1, O2}};token_movements with classification AGENT / INTERNAL_REFILL / INFLOW / UNEXPECTED_OUTFLOW (match by operation tx hash);alert Owner and Finance;request immediate PRE_STEP re-validation for an in-progress plan;signal to the circuit breaker;acknowledge endpoint",
  "Circuit-breaker rule evaluation (RCV-006).", "",
  "A Safe transaction moving 50 out of O1 is classified UNEXPECTED_OUTFLOW within two indexer cycles;The example in docs/modules/chain-reader §8.4 blocks the pending PAY;A refill by the agent is classified INTERNAL_REFILL, not an outflow",
  "Integration on Anvil")
_rev("RCV-006", deps="REC-001 MDT-007 EXE-013 CHR-006")
