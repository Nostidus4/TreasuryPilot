"""Alignment of tickets with the spec completion pass (M01, M02, M09–M19), 2026-10-11. Applied last."""
from ._base import TICKETS

def _rev(tid, **kw):
    t = next(x for x in TICKETS if x["id"] == tid)
    for k, v in kw.items():
        if k in ("scope", "ac", "tests") and isinstance(v, str): v = [s.strip() for s in v.split(";") if s.strip()]
        if k == "deps": v = v.split()
        t[k] = v

_rev("WEB-004", scope="Wizard: chain (Sepolia) and asset (tUSDC or Circle USDC) with TEST labels;wallet addresses with Safe verification feedback;module governance tx created and signed through the governance inbox;coverage result;Guardian Safe setup step (MDT-010)", deps="WEB-003 TRS-007 WEB-025")
_rev("WEB-005", scope="Form for all mandate fields with bigint display/base unit conversion;human-readable summary;diff against the active version with looser/stricter markers and confirm for looser changes;create the governance tx and hand off to the governance inbox;status PendingActivation → Active / Discrepancy")
_rev("WEB-006", scope="Vendors and payees list with status, screening result and cooling countdown;propose form (Operator/OrgAdmin/Owner) under a vendor;Owner out-of-band verification form (method + note);registration and deactivation governance txs;address-change flow that explains the new cooling period", deps="WEB-004 MDT-005 WEB-025")
_rev("WEB-012", scope="SSE subscription with Last-Event-ID;per-step status using the wording table in docs/modules/web §5 (Submitted, Pending, Confirmed-verifying, Paid, Dropped/replaced, Unknown 'checking the chain');explorer links;verification result;partial completion view")
_rev("WEB-013", scope="Review queue by type, routed role and SLA (incl. FEE_APPROVAL, UNEXPECTED_OUTFLOW, UNCERTAIN_TX);detail with reason codes and completed steps;exception request view with AI draft and engine numbers, Owner creates the grantException governance tx (no EIP-712);allowed actions per routing table (docs/modules/recovery §8.3);stale-item handling", deps="WEB-011 RCV-004 MDT-006 WEB-025")
_rev("WEB-014", scope="Table of requests, transactions, fees, classification and status;filters;mark matched (requires finalized + evidence) and discrepancy notes;export buttons;evidence bundle download;EAS receipt link")
_rev("WEB-019", scope="Pause button for Owner and Guardian with reason (sentinel on-chain pause, or Guardian-Safe tx from the wallet when no sentinel);Owner resume via governance tx;banners for pause requested, paused on-chain, protected mode off, expired mandate, unexpected outflow;pending transactions list")
_rev("RCV-004", scope="review_items schema with types POLICY_BLOCK, NEEDS_AUTHORITY, FEE_APPROVAL, UNCERTAIN_TX, DISCREPANCY, AI_REJECTED, INFRA, UNEXPECTED_OUTFLOW;creation rules per outcome;routing table and SLAs per docs/modules/recovery §8.3;list and action endpoints with optimistic version;overdue escalation to Owner")
_rev("RCV-002", scope="Resolution order per docs/modules/recovery §8.1: receipt (primary + secondary), executor nonce, module stepUsed/requestPaid;outcomes Confirmed, Reverted, Abandoned (never broadcast), still Pending;escalate to UNCERTAIN_TX after 30 min with the treasury blocked")
_rev("RCV-006", scope="Rules per docs/modules/recovery §8.4 (≥3 rejections in 10 min, AI plan out of mandate, coverage drop, DISCREPANCY → PAUSE; unexpected outflow → ALERT or PAUSE above 20 % of balance);PAUSE = backend pause + sentinel + notify;circuit_rules and circuit_events;30-min cool-down;rules can be tightened, PAUSE rules not disabled")
_rev("NTF-001", scope="domain_events outbox written in the same transaction;publisher with SKIP LOCKED;routing table per docs/modules/notifications §5 (incl. GovernanceSignatureNeeded, FeeAcceptanceNeeded, UnexpectedOutflow, CircuitBreakerTripped);notifications schema;dedup by (user, event)")
_rev("REC-001", scope="Expected effects per step type (docs/modules/reconciliation §8.1);observed = state at block B minus B−1 via Multicall3, concurrent token movements subtracted;verification PASSED / DISCREPANCY / UNKNOWN (after 3 read failures);DISCREPANCY → review item + circuit-breaker signal;called by EXE-008 before the next step")
_rev("REC-003", scope="GET list with filters;POST match (requires finalized PAY block and complete evidence), discrepancy, resolve (Finance note + Owner ack);auto-match per docs/modules/reconciliation §8.3 when the org setting is on")
_rev("AGT-001", scope="Adapter interface (complete with schema, tool loop);Anthropic SDK implementation with structured outputs and tool use;config/ai.yaml: model per task (docs/modules/agent §9), timeouts, max tool calls, token budgets;per-org monthly AI budget with degrade-to-fallback;typed errors (AiTimeout, AiUnavailable, AiSchemaError, AiBudgetExceeded)")
