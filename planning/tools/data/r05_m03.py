"""Revisions from the M03 (mandate) grilling round and the chain round with anh Phúc, 2026-10-11. Applied after r04_m05."""
from ._base import TICKETS, T

def _rev(tid, **kw):
    t = next(x for x in TICKETS if x["id"] == tid)
    for k, v in kw.items():
        if k in ("scope", "ac", "tests") and isinstance(v, str): v = [s.strip() for s in v.split(";") if s.strip()]
        if k == "deps": v = v.split()
        t[k] = v

def _get(tid): return next(x for x in TICKETS if x["id"] == tid)
D = "docs/modules/mandate"

# ── chain round (anh Phúc) ──
_rev("DOM-001", title="Verify Ethereum Sepolia infrastructure (owner: Phúc)", refs="OQ-02, ADR-012, PH-1",
  objective="Confirm that everything the build assumes exists on Ethereum Sepolia and record it.",
  scope="Verify Safe v1.4.1 singleton, proxy factory, MultiSendCallOnly and fallback handler addresses;Safe Transaction Service endpoint;EAS and SchemaRegistry addresses;Alchemy + public RPC endpoints;Etherscan API key for verification;update ADR-012 and the deployments manifest template",
  notes="Decision taken 2026-10-11 (PH-1): Ethereum Sepolia. This ticket now records the verification.",
  ac="ADR-012 lists every address with a link;A test Safe transaction on Sepolia is recorded;Both RPC endpoints answer eth_chainId = 11155111")
_rev("DOM-002", title="Set up tUSDC and the Circle USDC evidence run (owner: Phúc)", refs="OQ-03, OQ-05, ADR-012, PH-2",
  objective="Have the tokens and funds ready for the demo and the real-token evidence run.",
  scope="tUSDC (6 decimals, label TEST) deployment parameters;Circle USDC Sepolia address verified;collect Circle faucet funds (developer console) for one run with limits ÷ 100;document the scaled mandate values",
  notes="Decision taken 2026-10-11 (PH-2).",
  ac="ADR-012 lists both token addresses;At least 120 Circle USDC are available on the demo treasury before the evidence run;The scaled mandate config is in the demo runbook")
_rev("DOM-003", prio="P1")  # PH-3 wording lives in the DOM-003 definition
_rev("SC-016", deps="SC-010 SC-021 DOM-001",
  scope="forge script deploying tUSDC (local and Sepolia), the module implementation and the factory with CREATE2 and a fixed salt (PH-10);demo setup script (Safe T calls factory.create, enable module on T/O1/O2 via MultiSend);write deployments/<chainId>.json with implementation, factory, token(s), EAS schema UID and code hashes;verify on Etherscan for Sepolia",
  ac="`make deploy-local` produces deployments/31337.json;Sepolia deployment produces the same implementation and factory addresses as a second dry run (CREATE2);Contracts are verified on Etherscan;The manifest contains token, module, factory and Safe addresses plus code hashes")
_rev("SC-019", prio="P1", refs="FR-608, ADR-018, PH-11", deps="DOM-001",
  scope="EAS schema 'TreasuryPilot Payment Receipt v1' (requestId, invoiceHash, approvalHash, planHash, payTxHash, payee, amount, policyVersion), non-revocable;script to register it on Sepolia;Python attest helper;schema UID in the manifest",
  notes="ADR-018. Only hashes and addresses — no personal data.",
  ac="Schema UID recorded in the deployments manifest;A sample attestation resolves on easscan (Sepolia);The helper refuses any field that is not in the schema")
_rev("REC-005", prio="P1", refs="FR-608, ADR-018, BR-074", deps="REC-002 SC-019",
  scope="Task that attests after the request is Paid and reconciled;dedicated receipt key in the core worker with low-gas alert;store attestation UID;retry with backoff without affecting payment status;easscan link in the request detail and evidence bundle",
  ac="The UID resolves on easscan;The attestation contains no personal data;An EAS failure leaves the payment Paid and is retried")

# ── M03 ──
_rev("MDT-001",
  scope=f"Alembic migration and models per {D} §4 (mandate_versions, mandate_status_events, payees with OOB fields, screenings, exceptions, governance_txs, governance_signatures, guardian_setups, treasury_fee_policies, fee_acceptances, backend_pause);immutability triggers;constraints",
  ac="Migration applies and downgrades;Updating a mandate_versions config row is rejected by the database;Two open governance txs with the same Safe nonce are rejected")
_rev("MDT-002",
  scope=f"POST /mandates creating a draft;validation per {D} §8.1;human summary in display and base units;diff against the active version with looser/stricter markers (§8.2);bundle preview (§8.3);clone and discard",
  ac="Incomplete drafts return MANDATE_INCOMPLETE with the missing fields;target < buffer returns TARGET_BELOW_BUFFER;Summary amounts equal the config in base units;A higher limit is marked looser and requires confirmation")
_rev("MDT-003", deps="MDT-002 MDT-009 TRS-006 CHR-003",
  scope=f"governance-tx endpoint building the bundle (configureMandate only when mandate fields change, setApprovers, setBuffer);tracking via MDT-009;read-back of mandate(), approvers and buffers and hash compare (§8.4);status events;Discrepancy review item",
  ac="Status moves Draft → PendingActivation → Active only after matching on-chain state;A buffer-only change does not call configureMandate;A mismatch sets Discrepancy and does not activate;Version history is immutable")
_rev("MDT-004",
  scope=_get("MDT-004")["scope"] + ["POST /payees/{id}/verify-oob recording method and note (Owner only), audited"],
  ac=";".join(_get("MDT-004")["ac"]) + ";Registration-tx is refused with OOB_NOT_VERIFIED until verify-oob is recorded")
_rev("MDT-005", deps="MDT-004 MDT-009 CHR-005",
  scope="registration-tx and deactivation-tx endpoints building governance txs (MDT-009);status sync from PayeeAdded/PayeeDeactivated events;activeFrom from the event;address change creates a new payee and deactivates the old one;screening must be CLEAR within 24 h",
  notes="Cooling seconds come from the mandate (M04-D5); changing cooling affects only payees added afterwards (M03-D8).")
_rev("MDT-006", deps="MDT-003 MDT-009 INV-010",
  scope=f"GET exception with numbers (amount, cap, daily used, remaining after, value if granted) and AI draft;grant-tx (default expiry 72 h, ≤ approval expiry) after the pre-check in {D} §8.5;revoke-tx;reject;allow-duplicate-tx;status from ExceptionGranted/ExceptionRevoked/PaymentExecuted(usedException) events;Invalidated on mandate version change")
_rev("MDT-007", deps="MDT-003 MDT-009 EXE-013",
  scope="POST /pause sets the backend pause flag at once and calls the sentinel (EXE-013) when configured, else returns a Guardian-Safe tx for the human guardian;resume-tx and revoke-tx (typed name confirmation) via MDT-009;status sync from Paused/Resumed/Revoked;re-plan all queued requests after Resumed;list of pending transactions at pause time",
  ac="After POST /pause no new operation is created;With a sentinel configured the module is Paused within 2 blocks on Anvil;Guardian can pause but resume-tx is refused for them;UI data distinguishes requested from effective")
_rev("MDT-008", scope="Periodic task marking mandates Expired at expiresAt;notifications to the Owner 7 d, 48 h and 1 h before expiry;renewal shortcut = clone with a new expiry")
_rev("TRS-006", deps="TRS-004 SC-016 SC-021 MDT-009")
_rev("INV-011", deps="INV-010 SC-022 MDT-009")
_rev("RCV-006", deps="REC-001 MDT-007 EXE-013",
  notes="Pause action uses the guardian sentinel (ADR-017) so the module is paused on-chain within about one block.")
_rev("EXE-004", deps="EXE-003 CHR-002 ENG-008 POL-006 AGT-009 EXE-012")
_rev("EXE-010", notes="M04-D10: M1 never moves native tokens from the treasury. Low-gas alerts cover the executor, the sentinel (ADR-017) and the EAS receipt key (ADR-018).")
_rev("ENG-005", scope=_get("ENG-005")["scope"] + ["early-payment value net of the estimated fee in asset units (FEE-2, M07-D10)"])
_rev("ENG-007", scope=_get("ENG-007")["scope"] + ["fee term: an early payment is preferred only if discount > fee in asset units;days held by the fee policy are infeasible for today"])
_rev("WEB-005", deps="WEB-004 MDT-003 WEB-025")

T("MDT-009","Build governance transactions and collect owner signatures in the app","M1","P0","L","F-020, F-021, F-022, F-025, F-026","FR-225, BR-008, ADR-017, M03-D1, M03-D5","MDT-001 TRS-005",
  "Every Owner change becomes one Safe transaction that owners sign in TreasuryPilot and one owner executes.",
  f"SafeTx builder (direct call or MultiSendCallOnly v1.4.1 bundle) with decoded calls and a human summary;Safe nonce allocation (one open tx per nonce, queue the rest);EIP-712 SafeTx typed data;POST signatures verified against the Safe's on-chain owners;packed signatures and the execTransaction call for the executing owner;submitted tx tracking via ExecutionSuccess/ExecutionFailure;Superseded detection;optional Safe Transaction Service proposal link",
  "Contract-specific payloads (MDT-003/005/006/007, TRS-006, INV-011 use this).",
  "Never store or ask for an owner key. Owners sign with their own wallets.",
  "On Anvil with a real Safe v1.4.1 2-of-3, two in-app signatures and one execTransaction apply a MultiSend bundle;A signature from a non-owner returns NOT_SAFE_OWNER;An externally used nonce marks the tx Superseded;Decoded calls equal the encoded calldata (round trip)",
  "Integration on Anvil with Safe v1.4.1")
T("MDT-010","Set up the Guardian Safe with the sentinel","M1","P0","S","F-026, F-027","BR-068, ADR-017, M03-D2, PH-4","MDT-009 EXE-013 TRS-006",
  "Each treasury gets a guardian that can stop the agent on-chain within about one block.",
  f"Setup step building the Guardian Safe deployment (threshold 1, owners = human guardian(s) + sentinel address from the signer);record guardian_setups;mandate guardian field defaults to this Safe;health check that the sentinel is an owner and has gas",
  "Circuit-breaker rules (RCV-006).", "",
  "The guardian in the active mandate equals the Guardian Safe;The sentinel can pause through it;A human guardian can also pause from their wallet;Removing the sentinel from the Guardian Safe disables automatic on-chain pause and shows a warning",
  "Integration on Anvil")
T("EXE-013","Add the pause-only sentinel to the signer","M1","P0","S","F-026, F-027","BR-068, ADR-017, AP-3","EXE-005 EXE-006",
  "The system can pause the module on-chain without any power to spend or govern.",
  "Separate encrypted sentinel keystore;GET /sentinel/address;POST /sentinel/pause {treasuryId} building only GuardianSafe.execTransaction(module, 0, pause()) for the configured treasury and broadcasting it;refuses any other target or calldata;idempotent when already paused;gas balance in health",
  "Deciding when to pause (MDT-007, RCV-006).", "Sentinel key ≠ executor key ≠ policy key.",
  "A pause request results in Paused within 2 blocks on Anvil;Any other calldata or target is refused;The key never appears in logs",
  "Unit + integration on Anvil")
T("EXE-012","Implement the fee policy, fee holds and fee acceptance","M1","P0","M","F-066","BR-084, FR-517, FR-518, FEE-1, FEE-2, FEE-3, PH-7","MDT-001 CHR-001 ENG-001",
  "The agent spends gas automatically only within limits the Owner accepted, and waits or asks otherwise.",
  f"Fee proposal from 7-day history and eth_feeHistory (presets ECONOMY/NORMAL/FAST, per-plan threshold, daily budget) per {D} §8.6;accept endpoint (Owner, no free-form numbers);plan fee estimate (estimateGas × maxFee over all steps);hold rules per §8.7: proceed, defer (FEE_ABOVE_THRESHOLD / FEE_BUDGET_EXHAUSTED) or AwaitingFeeAcceptance on the last safe day;fee accept/defer endpoints for Finance/Operator/Owner;daily spent-fee counter",
  "Sending transactions (EXE-007).", "Reference ETH price is a labelled treasury setting in M1; an oracle is Later.",
  "The §8.7 example behaves as documented;A held plan is deferred without a human while its deadline allows;On the last safe day a FEE_APPROVAL review item is created;An accepted fee cap is respected by the executor",
  "Unit + integration")
T("WEB-024","Build the fee policy and fee acceptance UI","M1","P1","S","F-066","FR-517, FR-518","WEB-010 EXE-012",
  "Owners accept the proposed fee limits; Finance accepts held plans.",
  "Fee policy card with the system proposal and basis (avg, p90, plans per day) and Accept / choose preset;held-plan banner with 'Pay now at X' / 'Defer';history of accepted fees",
  "", "", "The Owner can accept a proposal in two clicks;A held plan shows the estimated fee and the deadline", "E2E")
T("WEB-025","Build the governance signing inbox","M1","P0","M","F-020–F-026","FR-225, M03-D1","WEB-003 MDT-009",
  "Owners see, sign and execute pending Safe transactions inside TreasuryPilot.",
  "List of governance txs by status;detail with decoded calls, human summary and diff;sign with the connected wallet (EIP-712 SafeTx);progress n/threshold;Execute button for the last owner sending execTransaction;Superseded and failed states;optional open-in-Safe{Wallet} link",
  "", "The typed data shown must be the object passed to signTypedData.",
  "Two owners can sign and the second executes;A non-owner sees the item read-only;A Superseded tx cannot be signed",
  "E2E with mock wallets")
