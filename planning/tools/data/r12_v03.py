"""Spec v0.3 merge (ADR-019): Aave idle-cash management, two-option payment approvals, D1–D10, B0, config gate. 2026-10-11."""
from ._base import TICKETS, T

def _get(tid): return next(x for x in TICKETS if x["id"] == tid)
def _add(tid, scope=(), ac=(), refs="", deps=""):
    t = _get(tid)
    t["scope"] = list(t["scope"]) + list(scope)
    t["ac"] = list(t["ac"]) + list(ac)
    if refs: t["refs"] = t["refs"] + ", " + refs
    if deps: t["deps"] = list(t["deps"]) + deps.split()

C = "docs/modules/contracts §15"
_add("SC-002", [f"PaymentApproval with 13 fields (earlyAmount, earlyPayBy) per {C}", "Aave storage (aavePool, aToken) and supply Limits in the mandate", "new errors and events: Supplied, Withdrawn, SupplyFloorBreach, OverSupplyPerTx, OverSupplyDaily, InsufficientAToken, AllowanceNotCleared, WrongPaymentOption"], [], "ADR-019")
_add("SC-005", ["hash and verify the 13-field PaymentApproval"], [], "ADR-019")
_add("SC-006", ["pay exactly earlyAmount before earlyPayBy, otherwise exactly amount; reject earlyAmount > amount (WrongPaymentOption)"],
     ["Paying at earlyPayBy transfers earlyAmount; one second later transfers amount"], "ADR-019, BR-024")
_add("SC-014", ["invariants I12–I14 (supply floor, fixed Aave targets with zero allowance after, exact payment option)"], ["I12–I14 pass at 10k runs"], "ADR-019")
_add("SC-017", ["golden vectors for the 13-field PaymentApproval"], [], "ADR-019")
_add("SC-021", ["create() takes aavePool; initialize() stores aavePool and verifies aToken via getReserveData(asset)"], [], "ADR-019")
_add("ENG-001", ["Snapshot fields safe_usdc, a_usdc, pool_available, supply_rate_bps, borrow_rate_bps, health_factor, debt"], [], "ADR-019")
_add("ENG-005", ["value uses the exact saving amount − pay_amount from the approval options instead of a bps estimate; lost supply interest for early payment"], [], "ADR-019")
_add("ENG-007", ["objective adds supply interest kept and lost interest from early payment (integer bps terms)", "WITHDRAW steps placed before REFILL when the reserve would break"], [], "ADR-019")
_add("ENG-010", ["builder for the 13-field PaymentApproval"], [], "ADR-019")
_add("POL-001", ["reason codes SUPPLY_FLOOR_BREACH, OVER_SUPPLY_PER_TX, OVER_SUPPLY_DAILY, RESERVE_BREACH, BELOW_MIN_SUPPLY (warning), INSUFFICIENT_POOL_LIQUIDITY, INSUFFICIENT_A_TOKEN, ALLOWANCE_NOT_CLEARED, WRONG_PAYMENT_OPTION, BORROW_NOT_AUTHORIZED, HEALTH_FACTOR_TOO_LOW"], [], "ADR-019")
_add("POL-003", ["SUPPLY/WITHDRAW step checks and PaymentReserve intact after SUPPLY (docs/modules/policy-engine §15)", "PAY amount must equal the early or standard option for the expected execution time"],
     ["A SUPPLY that would cut into PaymentReserve is BLOCKed with RESERVE_BREACH"], "ADR-019")
_add("POL-005", ["liquidity plans (requestId = 0x0, one SUPPLY or WITHDRAW step) hashed and attested like request plans"], [], "ADR-019")
_add("EXE-004", ["liquidity action from decide_liquidity when no request plan is executing (EXE-014)"], [], "ADR-019")
_add("EXE-005", ["signer payload allowlist adds module.supply and module.withdraw"], [], "ADR-019")
_add("EXE-008", ["step types WITHDRAW and SUPPLY; a leading WITHDRAW in request plans"], [], "ADR-019")
_add("CHR-002", ["Aave reads at the snapshot block: aToken balance, pool available liquidity, getReserveData rates, getUserAccountData"], [], "ADR-019")
_add("CHR-005", ["index Supplied, Withdrawn (and BorrowExecuted, Repaid) events"], [], "ADR-019")
_add("CHR-006", ["classify Safe T ↔ aToken transfers as LENDING, not unexpected outflow"], [], "ADR-019")
_add("INV-008", ["derive earlyAmount and earlyPayBy from confirmed discount terms"], [], "ADR-019")
_add("INV-010", ["typed data with earlyAmount/earlyPayBy (13 fields)"], ["An approval with both options verifies and stores both"], "ADR-019")
_add("WEB-009", ["show early vs standard options and sign the 13-field typed data"], [], "ADR-019")
_add("WEB-010", ["link to the position card (WEB-026)"], [], "ADR-019")
_add("MDT-002", ["mandate supply limits; Safe floor = buffer of Safe T; treasury settings min_supply and reserve horizon"], [], "ADR-019")
_add("MDT-003", ["read back supply limits and the Aave pool/aToken"], [], "ADR-019")
_add("REC-001", ["post-conditions for SUPPLY and WITHDRAW"], [], "ADR-019")
_add("REC-002", ["LENDING_TRANSFER lines for SUPPLY/WITHDRAW"], [], "ADR-019")
_add("REC-004", ["export supply interest earned for the period"], [], "ADR-019")
_add("AGT-014", ["baseline B0 (manual/EDF, cash idle) before B1 and B2; metrics add reserve breaches and net benefit incl. supply interest"], ["The report has three arms B0, B1, B2"], "ADR-019")
_add("DEV-007", ["scenario files D1–D10 per ADR-019 with must-show assertions"], ["All ten scenarios run on Anvil (Aave via mock or fork)"], "ADR-019")
_add("DEV-008", ["runbook scenes follow D1–D10"], [], "ADR-019")
_add("DEV-010", ["Sepolia profile uses Aave test USDC and the Aave Pool from the manifest"], [], "ADR-019")
_add("DOM-002", ["collect Aave Sepolia test USDC from the Aave faucet for the treasury; Circle run stays PAY-only"], [], "ADR-019")
_add("DOM-005", ["families idle-cash-supply and new-obligation-withdraw; B0 expectations"], [], "ADR-019")

T("SC-023","Add two-option payment approvals (early / standard)","M1","P0","S","F-038","BR-024, FR-524, ADR-019","SC-006 SC-005",
  "The approved discount is actually captured on-chain: the module pays exactly the early amount before its date, otherwise the standard amount.",
  "PaymentApproval fields earlyAmount and earlyPayBy;payAmount selection in pay();counters, buffer and daily checks on payAmount;WrongPaymentOption;PaymentExecuted(early flag)",
  "Off-chain derivation of the early amount (INV-008).", "",
  "Before earlyPayBy the payee receives exactly earlyAmount;After it, exactly amount;earlyAmount > amount reverts;earlyAmount = 0 behaves like a single-option approval",
  "Unit + fuzz on the time boundary")
T("SC-024","Implement Aave V3 supply and withdraw through Safe T","M1","P0","M","F-068","BR-037, BR-038, FR-520, ADR-019","SC-021 SC-007 SC-008",
  "Idle USDC earns in Aave without ever breaking the Safe floor.",
  "supply(stepId, amount) and withdraw(stepId, amount) per docs/modules/contracts §15;exact approve then pool.supply, allowance reset check;floor = bufferOf[safeT];supply caps and counters;balance-delta checks;Supplied/Withdrawn events;MockAavePool for unit tests",
  "Borrow/repay (SC-026).", "Fixed targets only: asset, aavePool, Safe T.",
  "A supply leaving Safe T below its floor reverts SupplyFloorBreach;Allowance is 0 after supply;Withdraw returns exactly the amount to Safe T;Non-executor calls revert",
  "Unit with MockAavePool")
T("SC-025","Add Aave integration tests on a pinned Sepolia fork","M1","P0","S","F-068, F-163","ADR-019, V3-11","SC-024 SC-016",
  "Prove supply and withdraw against the real Aave V3 contracts deterministically.",
  "Anvil fork of Sepolia at a pinned block in CI;deploy module + Safes on the fork;supply, withdraw, account data and aToken accrual;D2 and D3 as fork tests",
  "", "", "D2 and D3 pass on the fork;Results are identical across runs (pinned block)", "Integration (fork)")
T("SC-026","Implement owner-authorized borrow and repay","M1","P2","M","F-079","BR-044, FR-523, ADR-019","SC-024",
  "Borrowing only ever happens with an exact one-time owner authorization.",
  "Governance authorizeBorrow/authorizeRepay stored per planId;executor borrow(planId)/repay(planId);health factor check before and after;one use;events",
  "", "P2 (D7).", "Borrow without authorization reverts;Health factor below the minimum reverts;An authorization is usable once", "Unit + fork")
T("ENG-013","Implement reserve formulas and the liquidity decision","M1","P0","S","F-068","BR-037, BR-038, FR-519, ADR-019","ENG-002 ENG-005",
  "One deterministic answer to 'supply, withdraw or do nothing' each cycle.",
  "PaymentReserve, RequiredSafeReserve, AvailableForSupply, AccessibleLiquidity per docs/modules/financial-engine §15;decide_liquidity with min_supply, 5 % withdraw margin and caps;INSUFFICIENT_LIQUIDITY signal",
  "", "", "The D2 and D3 examples in §15 return SUPPLY 3,000 and WITHDRAW 2,625;Nothing is supplied below min_supply;A shortfall beyond Aave liquidity returns INSUFFICIENT_LIQUIDITY", "Unit + property")
T("ENG-014","Build the borrow proposal","M1","P1","S","F-069","BR-044, FR-522, ADR-019","ENG-013",
  "Show when borrowing would beat withdrawing, without ever executing it.",
  "propose_borrow: amount, cost to repayment, withdraw cost, health factor before/after, reason;excluded from executable plans",
  "", "", "A proposal is produced when pool liquidity is insufficient;No plan ever contains BORROW without an authorization", "Unit")
T("EXE-014","Run the liquidity cycle (supply / withdraw)","M1","P0","S","F-068","FR-519, ADR-019","EXE-008 ENG-013 SC-024",
  "The agent keeps idle cash supplied and withdraws when obligations grow.",
  "After request plans, at most one liquidity plan per cycle from decide_liquidity;validate, attest, execute like a request plan;leading WITHDRAW inside request plans when the reserve would break",
  "", "", "D2: surplus is supplied with the reserve intact;D3: a new approved invoice triggers a withdraw before payment", "Integration on the fork")
T("WEB-026","Build the treasury position card","M1","P0","S","F-068, F-130","FR-915, ADR-019","WEB-010",
  "Show where the money is and why it is (not) supplied.",
  "Safe USDC, aUSDC, pool liquidity, RequiredSafeReserve breakdown, AvailableForSupply, supply APY (testnet label), last liquidity action with explanation",
  "", "", "Numbers equal the engine output for the snapshot;Testnet APY is labelled", "E2E")
T("WEB-027","Build the borrow proposal view","M1","P1","S","F-069","FR-522, ADR-019","WEB-026 ENG-014",
  "Let the Owner compare withdraw vs borrow (D6).",
  "Proposal card: amount, cost to repayment, withdraw cost, health factor before/after, reason;clear 'no transaction without owner authorization'",
  "", "", "A proposal is displayed with engine numbers and no sign button in M1 (P2 adds signing)", "E2E")
T("DEV-012","Add the deployment config gate to CI","M1","P0","S","F-151","ADR-019, V3-14","SC-016 DEV-003",
  "Never deploy or demo against the wrong chain, token or Aave market.",
  "make config-check comparing deployments/<chainId>.json with on-chain chain id, token decimals, Aave Pool → aToken mapping;run in CI and before the demo",
  "", "", "A wrong decimals value or aToken mapping fails CI;The check passes for the Sepolia manifest", "CI")
T("MDT-011","Add owner borrow/repay authorizations (governance)","M1","P2","S","F-079","BR-044, ADR-019","MDT-009 SC-026",
  "The Owner authorizes one exact borrow or repay through Safe T.",
  "Governance txs authorizeBorrow/authorizeRepay built from a borrow proposal;tracking;UI hook in WEB-027",
  "", "P2.", "An authorization built from a proposal carries exactly its amount, expiry and minimum health factor", "Integration")
