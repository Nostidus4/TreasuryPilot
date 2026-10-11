"""Revisions from the M04 (contracts) grilling round, 2026-10-11. Applied after the base ticket files."""
from ._base import TICKETS, T

def _rev(tid, **kw):
    t = next(x for x in TICKETS if x["id"] == tid)
    for k, v in kw.items():
        if k in ("scope", "ac", "tests"): v = [s.strip() for s in v.split(";") if s.strip()]
        if k == "deps": v = v.split()
        t[k] = v

_rev("SC-002",
  scope="ITreasuryPilotModule interface per docs/modules/contracts §6;storage layout per §4 (mandate, buffers/targets, approvers, payees, counters, replay maps, exceptions, duplicate allowances);EIP-712 domain and the single PaymentApproval type hash;custom errors exactly as listed in §6.2–6.4;events per §6.6",
  ac="Interface compiles and matches docs/modules/contracts §6;PaymentApproval type hash is unit-tested against a hand-computed value;Every error name in §6.4 exists and matches a reason code in POL-001;Each state change listed in §6.6 has an event",
  notes="M04-D3: only PaymentApproval is an EIP-712 struct; exceptions and duplicate overrides are governance calls.")
_rev("SC-003", deps="SC-021",
  scope="configureMandate with validation (expiry > validFrom, executor ≠ 0, cooling ≥ 1, perRequest ≤ daily);setApprovers (keep ≥ 1);setBuffer (wallet known, buffer ≤ target);version increment;validity-window modifier;views",
  ac="Calls from any address other than Safe T revert NotOwner;Each invalid mandate field reverts InvalidMandate with the field;Version increases by one per configureMandate and counters are untouched;Executor calls revert MandateExpired after expiresAt",
  tests="Unit: governance access and validation matrix; counters unchanged across versions")
_rev("SC-004",
  scope="addPayee(payee) with activeFrom = now + mandate.payeeCoolingSeconds;deactivatePayee;payeeStatus view;reject treasury wallets as payees;internal _requireActivePayee",
  ac="A payee is not payable before activeFrom and is payable after;Re-adding a deactivated payee restarts cooling;Treasury wallets cannot be added as payees;Only Safe T can add or deactivate",
  notes="M04-D5: cooling comes from the mandate, never from a per-call argument.")
_rev("SC-006",
  scope="pay(approval, sig, stepId) per docs/modules/contracts §6.4 checks 1–13;paying wallet must be operational (BR-019);request/step replay maps;token transfer via the paying Safe's execTransactionFromModuleReturnData with return-data check;exact payee balance-delta check (M04-D8);PaymentExecuted event;reentrancy guard",
  ac="A valid approved payment transfers exactly the amount to the payee;Paying from Safe T reverts NotOperationalWallet;A second call with the same request or step id reverts;A fee-on-transfer stub token reverts BalanceDeltaMismatch with no state change;A non-executor caller reverts NotExecutor")
_rev("SC-009",
  scope="refill(approval, sig, stepId, toWallet, amount) per §6.4 checks 1–13;toWallet must equal the approval's paying wallet;one refill per request per wallet;post-refill balance ≤ approval.amount + target(toWallet);refill limits and counter;source buffer;balance-delta check;RefillExecuted event",
  ac="A refill within all bounds succeeds;A second refill for the same request and wallet reverts AlreadyRefilledForRequest;A refill that would push the wallet above amount + target reverts RefillExceedsNeed;A refill to a wallet other than the approval's paying wallet reverts WrongRefillTarget;Safe T below its buffer after refill reverts SourceBufferBreach",
  tests="Unit: bound, replay and path tests; invariant I10 added in SC-014")
_rev("SC-011", title="Implement one-time exceptions via owner governance",
  scope="grantException(requestId, amount, payee, expiry) and revokeException callable only by Safe T;store the current mandate version;pay() accepts over-cap only with an unused, unexpired exception matching amount, payee and version;mark used atomically;ExceptionGranted/Revoked events",
  ac="An over-cap pay with a matching exception succeeds once;A second use, a different request, a different payee or amount, an expired exception, or one from an older mandate version all revert;The daily cap still blocks an exception payment that would exceed it",
  notes="M04-D3: no EIP-712 signature; the Owner signs a Safe transaction, so Safe thresholds apply automatically.")
_rev("SC-012", title="Add the duplicate-invoice fingerprint registry and owner override",
  scope="fingerprintPaid map set in pay();allowDuplicate(fingerprint, requestId) callable only by Safe T;override consumed by exactly that request;DuplicateAllowed event",
  ac="A second pay with the same fingerprint and a new request id reverts DuplicateFingerprint;After allowDuplicate for request R, R can pay once and any other request still reverts",
  notes="M04-D3: override is a governance call, not a flag inside the approval.")
_rev("SC-014",
  scope="Handler contract driving pay/refill/pause/configure/grantException with bounded random inputs;invariants I1–I10 from docs/modules/contracts §10 (I10 = refill bound);10k-run configuration",
  ac="Invariants I1–I10 pass at 10k runs;Each invariant is mapped to its BR in a comment;A deliberately broken check makes the matching invariant fail")
_rev("SC-016", deps="SC-010 SC-021",
  scope="forge script deploying TestUSDC (local), the module implementation and the factory;demo setup script that has Safe T call factory.create and enables the module on T, O1, O2 (MultiSend);write deployments/<chainId>.json with implementation, factory, token addresses and code hashes;verify on the explorer for testnet")
_rev("SC-018", notes="P2 only. M04-D10: no native-token transfers in M1, so swapForGas stays optional and the executor gas is topped up manually.")

T("SC-021","Implement the module factory with EIP-1167 clones","M1","P0","M","F-012, F-021","ADR-002, M04-D2, M04-D9","SC-002",
  "Every treasury gets its own module clone, created and initialized safely by its own Safe T.",
  "TreasuryPilotModuleFactory.create(asset, operational, mandate, approvers, buffers) callable by Safe T (msg.sender becomes safeT);EIP-1167 clone of a single implementation;initialize() once, disabled on the implementation;TreasuryModuleCreated event;implementation() view for coverage checks",
  "Enabling the module on the Safes (done by the Owner, TRS-006).",
  "Use OpenZeppelin Clones. Clones share the implementation's runtime code, so coverage (TRS-007) checks the clone's target.",
  "A clone created by Safe T has safeT = that Safe and the given config;Calling initialize again, or on the implementation, reverts;Two treasuries get two clones with independent storage;TreasuryModuleCreated is emitted",
  "Unit: factory, initialize protection, independence of clones")

for tid, kw in {
  "TRS-006": dict(deps="TRS-004 SC-016 SC-021",
    scope="Endpoint returning a Safe T transaction that calls factory.create with the treasury config;then enableModule on T, O1, O2 (MultiSend batch);record the module address from TreasuryModuleCreated after confirmation"),
  "TRS-007": dict(scope="Coverage = COMPLETE if each Safe's enabled modules equal {one EIP-1167 clone whose target is the known implementation} and no unexpected guard;PARTIAL otherwise;UNKNOWN on read failure;acknowledge endpoint (Owner);coverage exposed to the execution gate"),
  "MDT-006": dict(title="Implement one-time exception requests and owner grant transactions",
    scope="GET exception request (numbers from the engine, AI draft if present);endpoint building the Safe T transaction grantException(requestId, amount, payee, expiry);track ExceptionGranted event → status Granted;reject endpoint;pre-check that the daily limit would still hold",
    ac="The built Safe transaction grants exactly the request's amount and payee;After the Owner executes it, status becomes Granted from the on-chain event;A request that is not over-cap returns NOT_OVER_CAP;If the daily limit would be exceeded the grant is refused before building the transaction",
    notes="M04-D3: no EIP-712 exception signature."),
  "EXE-010": dict(notes="M04-D10: M1 never moves native tokens from the treasury; the executor is topped up manually and alerts fire below the threshold."),
}.items():
    _rev(tid, **kw)
