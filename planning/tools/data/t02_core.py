from ._base import T

# ───────────── ENG · Financial Engine (py-core) ─────────────
T("ENG-001","Create py-core money types and domain models","M1","P0","M","F-013, F-051","ADR-014, BR-083, FR-109","DEV-001",
  "A typed, float-free foundation for all money logic.",
  "BaseUnits type (non-negative int) with parse/format using decimals;Pydantic models: Asset, WalletState, MandatePolicy, ApprovedRequest, PaymentTerms, Snapshot;JSON serialization of amounts as decimal strings",
  "Any I/O.",
  "Reject floats at the type level. No implicit conversion.",
  "Constructing an amount from a float raises;Round trip string→BaseUnits→string is exact for 6 and 18 decimals;Models serialize amounts as strings",
  "Unit: type and serialization tests")
T("ENG-002","Implement the liquidity calculator","M1","P0","M","F-051","BR-032, BR-034, FR-403","ENG-001",
  "Deterministic shortage and refill numbers exactly as the domain spec defines.",
  "Functions for Available, FundingDeficit, Shortage, PreferredRefill, SourceCapacity, Cap;golden tests from source Domain §3.4 and UC-02 example",
  "Decision table (ENG-003).",
  "Formulas are in docs/BUSINESS_RULES.md BR-032.",
  "Domain §3.4 example: Shortage 250 and PreferredRefill 350;UC-02 example: both equal 90;All arithmetic is integer",
  "Unit: golden tests")
T("ENG-003","Implement the refill decision table","M1","P0","S","F-051","BR-031, BR-033, FR-404","ENG-002",
  "Turn calculator outputs into one of: no refill, refill preferred, refill shortage, stop.",
  "decide_refill returning a typed decision with reason code;no refill when Shortage is 0;stop when Cap < Shortage",
  "",
  "Reason codes must come from the POL-001 catalogue.",
  "The three Domain §3.4 scenarios (350 / 250 / stop) return the documented decisions;No refill is proposed only to reach target",
  "Unit: decision table tests")
T("ENG-004","Add property tests for buffer and limit safety","M1","P0","S","F-051","NFR-MAINT-03, BR-030","ENG-003",
  "Prove with random inputs that engine outputs never breach buffers or limits.",
  "hypothesis strategies for wallet states, policies and requests;properties: post-plan balances ≥ buffer, refill ≤ Cap, no negative amounts",
  "", "",
  "Properties pass with at least 1,000 examples each;A seeded failing example is reproduced deterministically",
  "Unit: property tests")
T("ENG-005","Model payment terms and their value function","M1","P0","S","F-035, F-052","BR-052, BR-075","ENG-001",
  "Compute what paying on a given date is worth in stablecoin.",
  "PaymentTerms: discount pct and deadline, net due date, late-fee schedule, priority note;value(pay_date) = discount captured − late fee incurred;validation of ranges and date order",
  "Extraction of terms from text (AGT-005).",
  "Percentages as basis points (integers).",
  "'2/10 net 30' on a 1,000 unit invoice yields 20 units if paid by day 10 and 0 after;A late fee of 1.5%/week accrues per started week;Invalid terms raise typed errors",
  "Unit: terms tests")
T("ENG-006","Implement the baseline scheduler B1 (earliest deadline first)","M1","P0","S","F-052, F-092","BR-052","ENG-003 ENG-005",
  "The rule-based reference schedule every AI plan is compared against.",
  "schedule_edf(requests, state, policy, today) producing an ordered feasible schedule;ties by approval order;infeasible items with reasons",
  "", "",
  "Requests are ordered by deadline then approval time;Items blocked by cooling payee, daily cap or source capacity are reported with a reason",
  "Unit: ordering and infeasibility tests")
T("ENG-007","Implement the terms-aware scheduler","M1","P0","L","F-052","BR-052, FR-405","ENG-006",
  "Find the feasible schedule that maximizes value under the BR-052 priority order.",
  "Exact search for N ≤ 12;greedy plus pairwise-exchange improvement for larger N;multi-day horizon honouring the daily cap per day;output per-item planned date and expected value",
  "AI proposals (AGT-008).",
  "Lexicographic objective: violations (must be 0), missed feasible deadlines, value, tx count. Split into two PRs if it exceeds 2 days.",
  "On hand-computed cases the result equals the known optimum;It never schedules an item that the validator would block;It is never worse than B1 on the objective",
  "Unit: optimum cases; property: never worse than EDF")
T("ENG-008","Expose plan scoring and binding-constraint reporting","M1","P0","S","F-052, F-053","FR-405, FR-407","ENG-007",
  "Score any candidate plan (AI or deterministic) with the same objective and explain what constrained it.",
  "score(plan) → objective tuple;binding_constraints(plan) → list (daily cap, buffer, source capacity, cooling, deadline);comparison helper",
  "", "",
  "Two plans can be compared deterministically;Binding constraints are listed with the numbers that bind",
  "Unit: scoring tests")
T("ENG-009","Implement invoice fingerprint normalization and hashing","M1","P0","S","F-037","BR-071, FR-314","ENG-001",
  "One canonical fingerprint for an invoice, identical to what the contract stores.",
  "normalize(vendor_id, invoice_no) (trim, case-fold, strip separators);keccak256 over the packed fields with amount and asset;test vectors shared with contracts",
  "", "",
  "'INV-001', 'inv 001' and 'INV001' produce the same fingerprint;The value matches the Solidity computation in a shared vector",
  "Unit: normalization and vector tests")
T("ENG-010","Build EIP-712 typed data for approvals, exceptions and attestations","M1","P0","M","F-038, F-025, F-056","ADR-003","SC-017 ENG-001",
  "Python produces and verifies the same digests as the contract.",
  "Builders for the three typed structs;verify_signature helpers including ERC-1271 call hook;tests against the golden vectors",
  "", "Use eth-account. Never sign JSON directly.",
  "All golden vectors pass;A one-field mutation changes the digest",
  "Unit: vector tests")
T("ENG-011","Implement the 7-day liquidity forecast","M1","P2","S","F-058","FR-415","ENG-003",
  "Project per-wallet balances against approved obligations and suggest early refills.",
  "forecast(state, requests, policy, days=7) → daily projected balances, buffer-hit dates, suggested refills within limits",
  "UI chart (WEB-021).", "",
  "Projection matches a hand-computed example;Suggested refills never exceed limits or the source buffer",
  "Unit: forecast tests")
T("ENG-L01","Plan refills from other operational wallets","Later","-","M","F-059","FR-416","ENG-007 SC-L06",
  "Use surplus in one operational wallet to fund another.", "Extend source selection;protect the source wallet's own obligations", "", "",
  "Source wallet obligations remain funded (property test)", "Unit + property")
T("ENG-L02","Add FX conversion and depeg checks for fiat invoices","Later","-","M","F-041","FR-322","ENG-005",
  "Parent ticket for the fiat FX safety work; keep unscheduled until ENG-015 and ENG-016 are estimated and complete.", "Track the two child tickets: ENG-015 models immutable fiat approvals, rational FX rates, quotes and source/depeg policy (S, ≤0.5 day); ENG-016 implements fail-closed quote validation, exact conversion and the approved maximum guard with boundary/property tests (S, ≤0.5 day)", "Invoice storage, approval signing and payment orchestration (INV-L04)", "Split before scheduling: deliver the pure models first, then the pure conversion/check function. Child work totals S + S (≤1 day); preserve this accepted parent as the traceability link for FR-322.",
  "Never proposes more than the approved maximum stablecoin amount;Stale, mismatched, out-of-tolerance or depegged quotes are blocked", "Unit + property")
T("ENG-015","Model fiat FX approvals, rates and quote policy","Later","-","S","F-041","FR-322","ENG-001 ENG-005",
  "Represent approved fiat amounts and observed FX inputs using validated integer models.", "FiatApproval binds fiat minor units, reference rate, tolerance and maximum token base units;FxRate stores an exact rational token-base-units/fiat-minor-unit pair;FxQuote and FxPolicy carry source, observation time, USD peg price and freshness/depeg thresholds", "Conversion and payment orchestration", "Keep values integer-only and immutable; USD peg policy is scoped to the supported USD-pegged asset.",
  "Invalid or non-positive amounts/rates and out-of-range bps are rejected;Amounts serialize without precision loss", "Unit")
T("ENG-016","Guard fiat conversion against FX drift, depeg and approved caps","Later","-","S","F-041","FR-322","ENG-015 ENG-005",
  "Return a deterministic token amount only when a fresh quote satisfies the approval and safety policy.", "Validate source/pair/freshness;compare rational rates by integer cross multiplication;check USD peg threshold;round conversion up to token base units;block instead of clipping if the rounded amount exceeds the approved maximum", "Fetching quotes, persisting invoices, signing approval and executing PAY", "Typed review-block reasons; recheck immediately before PAY and bind the returned amount to the approval.",
  "Every returned amount is at most the approved maximum;Boundary, malformed input, stale quote, depeg and randomized valid-rate cases are covered", "Unit + property")
T("ENG-L03","Extend the scheduler to multiple assets","Later","-","M","F-015","FR-111","ENG-007",
  "Schedule across more than one stablecoin.", "Per-asset budgets and balances in the objective", "", "",
  "Per-asset limits respected in all schedules", "Unit + property")

# ───────────── POL · Policy Engine & Attestation ─────────────
T("POL-001","Define the reason-code catalogue and decision model","M1","P0","S","F-055","BR-057, API_SPEC §9","ENG-001",
  "One list of reason codes shared by the validator, API errors, UI and contract errors.",
  "Enum of reason codes with severity and default decision (ALLOW / NEEDS_APPROVAL / BLOCK);Decision model {decision, reasonCodes, checks};docs table generated from the enum",
  "", "Names must match contract custom errors where one exists.",
  "Every code in API_SPEC §9 exists in the enum;A test fails if a contract error has no matching code",
  "Unit: catalogue consistency test")
T("POL-002","Validate approval, mandate and payee conditions","M1","P0","M","F-055","BR-001, BR-010, BR-013, BR-015, FR-410","POL-001 ENG-010",
  "Deterministic checks that a step is authorized before it is attested.",
  "Checks: approval valid for the current revision and approver set, not expired;mandate active, not paused, not expired, version matches;payee active and cooling over;action and path allowed",
  "Limits and liquidity (POL-003).", "",
  "Each failed condition returns its specific reason code;Multiple failures return all codes with the most restrictive decision",
  "Unit: one test per code")
T("POL-003","Validate limits, buffers, deadlines, coverage and unknown operations","M1","P0","M","F-055","BR-022, BR-030, BR-040, BR-051, BR-060, FR-411","POL-002",
  "Complete the validator so it mirrors every contract check plus the off-chain safety gates.",
  "Per-request and daily limit checks using snapshot counters;buffer after each step;deadline feasibility;snapshot freshness and coverage;block if any operation is Unknown;over-cap only → NEEDS_APPROVAL unless a granted exception exists",
  "", "An exception never masks another failure.",
  "Missing or stale data never yields ALLOW;Over per-request cap alone yields NEEDS_APPROVAL;Over cap plus over daily yields BLOCK",
  "Unit: decision matrix from Autonomy §4")
T("POL-004","Add differential tests between validator and contract","M1","P0","M","F-055, F-163","NFR-SEC-01","POL-003 SC-013",
  "Catch any drift between off-chain validation and on-chain enforcement.",
  "Test harness that runs the same cases through the Python validator and the contract on Anvil;cases: all AT-05 variants, limits boundaries, cooling, pause, expiry",
  "", "Runs in CI integration stage.",
  "For every case the validator's ALLOW/not-ALLOW equals contract success/revert;A report lists the cases",
  "Integration: differential suite")
T("POL-005","Define canonical plan encoding and planHash","M1","P1","S","F-056","BR-059, FR-412","ENG-010",
  "A plan has exactly one hash regardless of language or field order.",
  "Canonical ABI-style encoding of ordered steps (action, wallets, payee, amount, request id, step id);planHash function;step id derivation (deterministic from request id, action, sequence)",
  "", "Do not hash JSON.",
  "The same plan built twice has the same hash;Changing any money-relevant field changes the hash",
  "Unit: hash stability tests")
T("POL-006","Sign and verify plan attestations","M1","P1","S","F-056","BR-059, FR-412–413, ADR-006","POL-005",
  "Only validator-approved plans can reach the signer.",
  "attest(plan, decision) using the policy key (loaded only in the core worker);verify_attestation helper for the signer service;nonce and validUntil handling",
  "On-chain verification (SC-L04).", "The policy key is distinct from the executor key.",
  "An attestation over a modified plan fails verification;Expired attestations fail;Nonce reuse is rejected",
  "Unit: attestation tests")

# ───────────── IDN · Identity & Access ─────────────
T("IDN-001","Create identity database schema and migrations","M1","P0","S","F-001–F-005","DATA_MODEL §2.1","DEV-002",
  "Tables for users, sessions, magic links, wallet links, nonces, organizations, memberships and invites.",
  "Alembic migration;SQLAlchemy models;partial unique index on wallet_links.address;citext email",
  "", "",
  "Migration applies on an empty database and downgrades cleanly;Constraints from DATA_MODEL §2.1 exist",
  "Integration: migration up/down test")
T("IDN-002","Implement magic-link login, sessions and CSRF","M1","P0","M","F-001","FR-001, FR-003, ADR-009","IDN-001",
  "Users can sign in by email and hold a secure session.",
  "POST /auth/magic-link, /auth/magic-link/verify, /auth/logout, GET /me;single-use 15-minute token stored hashed;httpOnly Secure SameSite=Lax cookie with server-side session;CSRF double-submit on mutations;email via Resend, console in local",
  "Rate limiting (IDN-003).", "",
  "A valid token creates a session and cannot be reused;Expired tokens return TOKEN_EXPIRED;Mutations without the CSRF token are rejected;Sessions expire on idle and absolute timeouts",
  "Unit + integration: auth flow tests")
T("IDN-003","Rate-limit authentication endpoints","M1","P0","S","F-001","FR-002, NFR-SEC-09","IDN-002",
  "Stop brute force and email flooding.",
  "Per-IP and per-email limits on magic-link and verify using Redis;429 with RATE_LIMITED and Retry-After",
  "", "",
  "Exceeding the limit returns 429;Limits reset after the window",
  "Integration: limit test")
T("IDN-004","Implement SIWE wallet linking","M1","P0","M","F-002","FR-004–006, BR-006","IDN-002",
  "Signer roles can prove control of their address.",
  "GET /auth/siwe/nonce;POST /me/wallets verifying the SIWE message (domain, chain id, nonce, expiry);ERC-1271 path for contract wallets;DELETE /me/wallets/{address};audit entries",
  "", "Use the `siwe` library. Nonces are single use.",
  "A valid signature links the address;Replayed nonce is rejected;An address linked to another user returns ADDRESS_LINKED_ELSEWHERE;Contract-wallet signatures verify through ERC-1271",
  "Unit + integration with a test key")
T("IDN-005","Implement organization creation and onboarding checklist","M1","P0","S","F-003","FR-007, FR-009","IDN-002",
  "A user can create a tenant and see what to set up next.",
  "POST /orgs (creator becomes OrgAdmin);GET /orgs/{id} with checklist computed from existing data;PATCH settings",
  "", "",
  "Creator has the OrgAdmin role;Checklist reflects real state (e.g. treasury exists)",
  "Integration")
T("IDN-006","Implement RBAC dependencies and tenant isolation","M1","P0","M","F-004","FR-008, FR-011, BR-093, NFR-PRIV-05","IDN-005",
  "Every endpoint enforces membership and role, and no data crosses organizations.",
  "FastAPI dependencies require_member and require_role;repository base class that always filters by org_id;generic cross-tenant test that hits every org-scoped route as a non-member",
  "", "Non-members get 404, not 403.",
  "A non-member receives 404 on all org routes;A member without the role receives 403;The cross-tenant test enumerates routes automatically",
  "Security: cross-tenant test suite")
T("IDN-007","Implement invites and membership management","M1","P1","M","F-004","FR-010, FR-012–013","IDN-006",
  "OrgAdmins can add people and assign the eight roles.",
  "Invite create/accept endpoints with expiring hashed tokens;role change and member removal;last-admin and last-owner guards;signer roles inactive until a wallet is linked",
  "Invite emails beyond a simple link.", "",
  "Accepted invite creates a membership with the roles;Removing the last OrgAdmin or Owner is refused;A signer role without a linked wallet cannot sign",
  "Integration")
T("IDN-008","Implement the maker-checker service and solo mode","M1","P0","S","F-005","BR-005, FR-014–015","IDN-006",
  "The creator or last editor of a request cannot approve it.",
  "assert_maker_checker(request, user) used by the approval endpoints;org solo_mode flag settable only by the Owner;solo approvals marked on the record and in audit",
  "", "",
  "Creator approving returns MAKER_CHECKER;With solo mode on, the approval succeeds and is flagged;Only the Owner can toggle solo mode",
  "Unit + integration")
T("IDN-L01","Add MFA and step-up authentication","Later","-","L","F-006","FR-016","IDN-002",
  "Protect signer accounts with a second factor.", "TOTP and WebAuthn enrolment;step-up for approve, exception, mandate edits;recovery codes", "", "",
  "Sensitive endpoints reject sessions without a fresh second factor", "Integration + security")
T("IDN-L02","Add OIDC single sign-on","Later","-","L","F-007","FR-017","IDN-006",
  "Enterprise login through the company identity provider.", "OIDC login;group-to-role mapping;just-in-time provisioning", "", "",
  "Login works with one OIDC provider;Deprovisioning revokes sessions within 5 minutes", "Integration")
T("IDN-L03","Add SAML and SCIM provisioning","Later","-","L","F-007","FR-017","IDN-L02",
  "Support SAML identity providers and automated provisioning.", "SAML SP;SCIM users and groups", "", "",
  "SCIM deprovision removes access", "Integration")

# ───────────── TRS · Treasury & Chain Configuration ─────────────
T("TRS-001","Create treasury and chain schema","M1","P0","S","F-010, F-013","DATA_MODEL §2.2","IDN-001",
  "Tables for chains, assets, deployments, treasuries, wallets and Safe snapshots.",
  "Alembic migration and models;unique constraints from DATA_MODEL §2.2",
  "", "", "Migration applies and downgrades cleanly", "Integration: migration test")
T("TRS-002","Load and validate platform chain configuration","M1","P0","S","F-151","FR-925","TRS-001",
  "Chains, RPC endpoints, confirmations and deployments come from a validated config, not from code.",
  "Pydantic settings reading config and deployments/<chainId>.json;sync into chains/deployments tables at startup;fail fast on invalid chain id, missing RPC or missing module code hash",
  "Admin UI (Later).", "",
  "Startup fails with a clear message on invalid config;At least two RPC URLs per enabled chain are required",
  "Unit: config validation tests")
T("TRS-003","Implement the asset registry with on-chain decimals check","M1","P0","S","F-013","BR-083, FR-108","TRS-002 CHR-001",
  "Assets are identified by chain and address, with verified decimals.",
  "Seed assets from config;verify decimals() on-chain when adding;is_test flag;GET /chains",
  "", "",
  "A decimals mismatch refuses the asset;Test assets are returned with isTest true",
  "Integration on Anvil")
T("TRS-004","Implement treasury creation with Safe verification","M1","P0","M","F-010, F-011","FR-101–103","TRS-003 IDN-006",
  "An Owner can register a treasury made of real Safes.",
  "POST /orgs/{o}/treasuries;verify each address is a Safe proxy on that chain (code hash / singleton);reject duplicates, wrong chain and EOAs;GET treasury with wallets",
  "Coverage (TRS-007).", "Use safe-eth-py for Safe detection.",
  "An EOA is rejected with NOT_A_SAFE;Duplicate wallet addresses are rejected;A valid set of three Safes creates the treasury",
  "Integration on Anvil")
T("TRS-005","Read and snapshot Safe configuration","M1","P0","S","F-011","FR-103, FR-105","TRS-004",
  "Know each Safe's owners, threshold, modules and guard at a block.",
  "Reader for owners, threshold, enabled modules (paginated), guard;store safe_config_snapshots;periodic refresh task;diff detection emits an event",
  "", "",
  "Snapshot matches on-chain values;A changed owner set produces a change event within one polling interval",
  "Integration on Anvil")
T("TRS-006","Build the module deploy-and-enable Safe transaction","M1","P0","M","F-012","FR-204","TRS-004 SC-016",
  "The Owner can deploy the treasury's module and enable it on all three Safes from the UI.",
  "Endpoint returning Safe transaction payload(s) for module deployment and enableModule on T, O1, O2;record the module address after confirmation",
  "", "For a 1-of-1 Safe the UI signs and executes directly.",
  "After the Owner executes the transactions the module is enabled on all three Safes;The treasury record stores the module address",
  "Integration on Anvil")
T("TRS-007","Compute coverage and handle acknowledgment","M1","P0","M","F-012","BR-018, FR-106–107","TRS-005 TRS-006",
  "Autonomous execution is allowed only when the Safes have exactly the expected module set.",
  "Coverage = COMPLETE if enabled modules equal {TreasuryPilotModule with the expected code hash} and no unexpected guard;PARTIAL otherwise;UNKNOWN on read failure;acknowledge endpoint (Owner);coverage exposed to the execution gate",
  "", "",
  "An extra module makes coverage PARTIAL and blocks the trigger;RPC failure yields UNKNOWN, never COMPLETE;Owner acknowledgment is audited and shows a banner state",
  "Integration: AT35-style test")
T("TRS-008","Build a Safe deployment transaction from the UI","M1","P2","S","F-011","FR-104","TRS-004",
  "Create a new Safe without leaving the app.",
  "Endpoint returning the Safe factory transaction for the Owner to sign;record the new address",
  "", "", "A Safe deployed through the flow is usable in treasury creation", "Integration on Anvil")
T("TRS-L01","Support multiple treasuries with a consolidated view","Later","-","L","F-014","FR-110","TRS-004",
  "Operate treasuries on several chains from one org.", "TRS-L01A (M): per-chain treasury registry;TRS-L01B (M): isolate controls and counters per treasury;TRS-L01C (S): consolidated view without cross-asset sums", "", "",
  "Counters and mandates are isolated per treasury", "Integration")
T("TRS-L02","Support multiple stablecoins per treasury","Later","-","M","F-015","FR-111","TRS-L01 SC-L05",
  "Hold and pay in more than one stablecoin.", "Asset list per treasury;per-asset limits in the mandate UI and API", "", "",
  "A request in a second asset is validated against that asset's limits", "Integration")

# ───────────── MDT · Mandate, Payees, Exceptions & Pause ─────────────
T("MDT-001","Create mandate, payee and exception schema","M1","P0","S","F-020–F-026","DATA_MODEL §2.3","TRS-001",
  "Tables for mandate versions and events, vendors, payees, screenings and exceptions.",
  "Alembic migration and models;immutability trigger on mandate_versions rows;constraints from DATA_MODEL §2.3",
  "", "", "Migration applies and downgrades;Updating a mandate_versions config row is rejected by the database", "Integration: migration test")
T("MDT-002","Validate mandate drafts and generate summary and diff","M1","P0","M","F-020","BR-014, FR-201–203","MDT-001 ENG-001",
  "Owners see exactly what they are about to authorize.",
  "POST /mandates creating a draft;completeness and consistency validation;human-readable summary in display units and base units;diff against the active version",
  "Activation (MDT-003).", "Only the Owner role may call it.",
  "Incomplete drafts return MANDATE_INCOMPLETE with the missing fields;target < buffer returns TARGET_BELOW_BUFFER;Summary amounts equal the config in base units",
  "Unit + integration")
T("MDT-003","Implement mandate activation and read-back","M1","P0","M","F-021","BR-015, FR-204–205","MDT-002 TRS-006 CHR-003",
  "A mandate becomes Active only when the chain says so.",
  "activation-tx endpoint building the configureMandate Safe transaction;activation endpoint recording the tx hash;tracker task waits for confirmations, reads the on-chain mandate and compares with the draft hash;status events",
  "", "",
  "Status moves Draft → PendingActivation → Active only after matching on-chain state;A mismatch sets Discrepancy and does not activate;Version history is immutable",
  "Integration on Anvil")
T("MDT-004","Implement vendor and payee proposals with screening","M1","P0","M","F-022","FR-211, BR-085","MDT-001 CMP-001",
  "Operators can propose payees; nothing becomes payable without screening and the Owner.",
  "Vendor CRUD (minimal);POST /payees creating a payee in Screening and running the screening adapter;result stored;hit → blocked",
  "On-chain registration (MDT-005).", "",
  "A screening hit returns SCREENING_HIT and the payee cannot proceed;Provider error blocks registration;Duplicate address is rejected",
  "Integration with the fixture provider")
T("MDT-005","Build payee registration and deactivation transactions and sync status","M1","P0","M","F-022","BR-013, BR-017, FR-208–210","MDT-004 CHR-005",
  "Payee status in the app always reflects the on-chain allowlist and cooling period.",
  "registration-tx and deactivation-tx endpoints;status sync from PayeeAdded/PayeeDeactivated events;activeFrom stored;address change creates a new payee and deactivates the old one",
  "", "Cooling seconds come from org settings (24h default, 5 min demo).",
  "After the Owner's transaction the payee shows Cooling with the correct activeFrom, then Active;Changing an address restarts cooling",
  "Integration on Anvil with time travel")
T("MDT-006","Implement one-time exception records and signatures","M1","P1","M","F-025","BR-040–BR-043, FR-216","MDT-003 ENG-010 INV-010",
  "Owners can grant an exception for one over-cap request, with full context.",
  "GET exception (numbers from the engine, AI draft if present, typed data);POST signature verification against Safe T owners;reject endpoint;status lifecycle;pre-check that the daily limit would still hold",
  "AI draft text (AGT-011); on-chain consumption (SC-011).", "",
  "A valid Owner signature sets Granted;A request that is not over-cap returns NOT_OVER_CAP;If the daily limit would be exceeded the grant is refused",
  "Integration")
T("MDT-007","Implement pause and resume (backend and transactions)","M1","P0","M","F-026","BR-062–BR-064, FR-218, FR-221","MDT-003",
  "Pausing takes effect in the backend immediately and on-chain after confirmation.",
  "POST /pause sets the backend pause flag at once and returns the pause Safe transaction (or guardian call);resume-tx for the Owner;status sync from Paused/Resumed events;list of pending transactions at pause time",
  "", "The trigger and executor check the flag before every action.",
  "After POST /pause no new operation is created;Guardian can pause but resume-tx is refused for them;UI data distinguishes requested from effective",
  "Integration: AT-08")
T("MDT-008","Sync mandate expiry and status","M1","P1","S","F-021","FR-207","MDT-003",
  "Expired mandates stop planning before the contract has to reject.",
  "Periodic task marking mandates Expired at expiresAt;notification to the Owner 48h and 1h before expiry",
  "", "", "A mandate past expiry is Expired and the trigger skips the treasury;Warnings are emitted before expiry", "Integration")
T("MDT-L01","Configure threshold-based approval policies","Later","-","M","F-029","FR-224","MDT-002 SC-L02",
  "Let owners define k-of-n approvals by amount band.", "Policy model and UI/API;collection of multiple approver signatures", "", "",
  "A request in a band needing two approvals is not Approved after one", "Integration")
