"""Revisions from the M08 (policy engine) grilling round, 2026-10-11. Applied after r02_m07."""
from ._base import TICKETS, T

def _rev(tid, **kw):
    t = next(x for x in TICKETS if x["id"] == tid)
    for k, v in kw.items():
        if k in ("scope", "ac", "tests"): v = [s.strip() for s in v.split(";") if s.strip()]
        if k == "deps": v = v.split()
        t[k] = v

_rev("POL-001",
  scope="ReasonCode enum per docs/modules/policy-engine §6.4 (group, precedence, default decision, contract error, BR);warning codes DEADLINE_MISSED, DISCOUNT_MISSED, TARGET_NOT_REACHED;Decision and Check models per §4.1 (decision, primary, codes, warnings, checks, stage, step_seq, policy_version, snapshot_block);decode_revert(selector) → code;docs table generated from the enum",
  ac="Every code in API_SPEC §9 exists in the enum;A test fails if a module custom error (M04 §6.4) has no matching code;decode_revert maps every module error selector;Precedence order matches §6.4 group order")
_rev("POL-002", refs="BR-001–005, BR-010, BR-013, BR-015, BR-066, FR-313, FR-410",
  scope="ValidationContext model (§4.1);gates: pause requested, circuit open, unknown operations, coverage, snapshot freshness (≤ 30 s and ≤ 5 blocks), data missing, chain/asset match;request and approval checks: present, typed fields equal current request (APPROVAL_STALE), signature/ERC-1271, current approver set, expiry, maker-checker with solo mode;HIGH flags acknowledged in the approval and none raised after it (FLAG_UNACKNOWLEDGED);screening;mandate lifecycle, executor;payee active and cooling over;plan shape checks (PLAN_MALFORMED)",
  oos="Limits, liquidity and aggregation (POL-003).",
  ac="Each failed condition returns its specific reason code;A failed gate skips step checks and marks them skipped;An unacknowledged HIGH flag, or one raised after approval, yields FLAG_UNACKNOWLEDGED;Rows 7, 8 and 11 of docs/modules/policy-engine §8.5 give the documented result")
_rev("POL-003", refs="BR-022, BR-030, BR-036, BR-040–042, BR-051, BR-060, FR-411",
  scope="REFILL checks mirroring M04 refill 1–9 and PAY checks mirroring pay 1–9;PLAN stage projects state after earlier steps;exception matching read from chain state (M08-D12);aggregation per §8.2 (BLOCK > NEEDS_APPROVAL > ALLOW, primary by precedence);warnings DEADLINE_MISSED / DISCOUNT_MISSED;validate_plan and validate_step entry points",
  ac="Rows 1–6, 9 and 10 of docs/modules/policy-engine §8.5 give the documented decision and primary code;Missing or stale data never yields ALLOW;An exception removes only OVER_PER_REQUEST_LIMIT;A late payment that passes all checks is ALLOW with DEADLINE_MISSED",
  tests="Unit: decision matrix §8.5; property: dropping or staling any input never yields ALLOW, exception never masks a hard failure")
_rev("POL-004",
  scope="Harness running the same cases through validate_step and the module on Anvil;cases: all AT-05 variants, limit boundaries (exactly at cap, cap + 1), cooling edges, pause, expiry, refill bound, exceptions, duplicate allowance;compare ALLOW vs success and decoded revert vs primary code",
  ac="For every case the validator's ALLOW/not-ALLOW equals contract success/revert;For every revert the decoded code equals the validator's primary code;A report lists the cases")
_rev("POL-005", refs="BR-059, BR-061, FR-412, M08-D10",
  scope="EIP-712 Step struct hash;planHash = keccak(PLAN_TYPEHASH, requestId, treasury, chainId, keccak(stepHashes)) per docs/modules/policy-engine §8.3;stepId = keccak('TP_STEP_V1', requestId, action, wallet) per §8.4;golden vectors shared with TypeScript",
  ac="The same plan built twice has the same hash;Changing any money-relevant field changes the hash;A re-plan of the remaining steps keeps the same stepIds;Python and TypeScript agree on all vectors")
_rev("POL-006", title="Sign and verify EIP-712 plan attestations with the policy key", refs="BR-059, FR-412–413, ADR-006, ADR-016",
  scope="PlanAttestation typed data per docs/modules/policy-engine §6.3 (domain 'TreasuryPilot Policy');attest(plan, decision) only for ALLOW at stage PLAN, validUntil = now + 15 min, random 128-bit nonce, evidence digest;policy key from an encrypted keystore loaded only in the core worker;attestations table row persisted before use;verify_attestation(typed, sig, trusted_signers, now) for the signer;key rotation with two trusted addresses",
  ac="An attestation over a modified plan fails verification;Expired attestations fail;A nonce reused for a different planHash is rejected;An approval signature never verifies as an attestation (different domain);worker-ai has no access to the policy key",
  notes="M08-D3. The policy key is distinct from the executor key and from any approver key.")
_rev("EXE-005", deps="POL-006 POL-007 SC-016",
  scope="FastAPI service with POST /sign-and-send and GET /health;verify attestation per docs/modules/policy-engine §6.3 (trusted signer, validUntil, chain/module, recomputed planHash, payload equals step seq, nonce/step use);own `signer` schema with attestation_uses (only the signer DB role can write);same payload may be re-signed for gas replacement;simulate (eth_call) then sign and broadcast;shared-secret auth on the internal network",
  notes="M08-D9: writes only to its own schema. No other endpoints.",
  ac="A payload that differs from the attested step is refused with PAYLOAD_MISMATCH;A nonce reused with another planHash is refused NONCE_REUSED;A reverted simulation is not broadcast;Re-signing the same step payload for a replacement is allowed;A non-allowlisted chain id is refused")
_rev("EXE-008", deps="EXE-007 CHR-003 POL-003 POL-007",
  scope="After confirmation take a new snapshot;run validate_step (PRE_STEP) then simulate (SIMULATION) for the next step;request a new plan validation + attestation if the attestation expired;stop and mark PartiallyCompleted on any non-ALLOW, open a review item with the primary code;mark request Paying then Paid after PAY confirmation")

T("POL-007","Simulate each step with eth_call before signing","M1","P0","S","F-055, F-061","BR-067, FR-505, ADR-016, M08-D5","POL-003 POL-001 CHR-002 SC-016",
  "Catch any validator/contract drift on fresh state before a transaction is signed.",
  "simulate(step, ctx): build the exact module.refill/pay calldata the signer will send;eth_call from the executor address at block latest;decode a revert into a reason code via decode_revert;RPC failure → SIMULATION_UNAVAILABLE;store a validations row with stage SIMULATION",
  "Signer-side simulation (EXE-005 keeps its own).",
  "Any revert or RPC error is BLOCK. Never retried into ALLOW within the same cycle.",
  "A step that the contract would reject is BLOCKed with SIMULATION_REVERTED and the decoded code;An unreachable RPC yields SIMULATION_UNAVAILABLE and BLOCK;Example 12 of docs/modules/policy-engine §8.5 behaves as documented",
  "Integration on Anvil: one case per module error")
