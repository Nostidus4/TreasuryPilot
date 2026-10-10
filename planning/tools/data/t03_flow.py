from ._base import T

# ───────────── INV · Invoices & Payment Requests ─────────────
T("INV-001","Create invoice and request schema","M1","P0","S","F-030–F-039","DATA_MODEL §2.4","MDT-001",
  "Tables for requests, revisions, documents, extractions, flags, approvals and status events.",
  "Alembic migration and models;partial unique index (treasury_id, fingerprint);optimistic-lock version column",
  "", "", "Migration applies and downgrades;The duplicate-fingerprint index rejects a second active request", "Integration: migration test")
T("INV-002","Implement the request state machine","M1","P0","M","F-039","FR-319–320","INV-001",
  "Requests move only along legal transitions, and every move is recorded.",
  "Transition table as data;transition(request, to, actor) service with role checks;request_status_events writes;refuse Cancelled while a PAY is pending or unknown",
  "", "No generic Failed state.",
  "Every legal transition in FEATURES F-039 is allowed and every other is rejected;Each transition writes a status event and an audit record",
  "Unit: full transition matrix")
T("INV-003","Implement manual request creation and editing","M1","P0","M","F-030","FR-301–302, BR-073","INV-002 MDT-004",
  "Operators can enter and edit invoices with strict validation.",
  "POST /requests and PATCH with If-Match;validation: payee exists, asset equals the treasury stablecoin, amount precision;revisions on edit;creator and last editor recorded;Idempotency-Key",
  "Fingerprint and anomaly checks (INV-006, INV-007).", "",
  "Wrong asset returns ASSET_NOT_PAYMENT_STABLECOIN;Editing creates a new revision;A stale If-Match returns 412",
  "Integration")
T("INV-004","Implement document upload to private storage","M1","P0","S","F-031","FR-303, BR-074, NFR-PRIV-02","INV-003",
  "Invoice files are stored privately and linked to a draft.",
  "POST /requests/upload (PDF, PNG, JPG up to 10 MB);store in the private bucket with sha256;documents record;signed URL for viewing;enqueue extraction on the ai queue",
  "The extraction itself (AGT-004).", "",
  "Unsupported type returns 415 and oversize returns 413;Files are not publicly readable;The response contains a request id and an extraction job id",
  "Integration with MinIO")
T("INV-005","Implement CSV bulk import","M1","P1","M","F-032","FR-306–307","INV-003",
  "Import many invoices at once with per-row feedback.",
  "CSV template and header validation;row-by-row validation;drafts for valid rows;downloadable error report;neutralize cells starting with = + - @",
  "", "",
  "500 valid rows import in under 10 seconds;Invalid rows are reported with row number and reason;Formula-like cells are neutralized",
  "Integration + performance test")
T("INV-006","Compute fingerprints at intake and block duplicates","M1","P0","S","F-037","BR-071, FR-314","INV-003 ENG-009",
  "Duplicates are caught before approval.",
  "Fingerprint on create and edit;duplicate check within the treasury;DUPLICATE_FINGERPRINT blocks submit;link to the existing request in the error",
  "On-chain registry (SC-012).", "",
  "A second request with an equivalent invoice number cannot be submitted;The error identifies the original request",
  "Integration")
T("INV-007","Implement deterministic anomaly checks","M1","P0","M","F-036","FR-312, BR-072","INV-006",
  "Flag fraud signals without relying on the LLM.",
  "Flags: address differs from registry or vendor history (checksum compare), amount outlier (median ± 3·MAD, needs ≥ 5 history points), currency or chain mismatch, due-date anomaly, duplicate;severity, evidence and reason code per flag;'no baseline' state for new vendors",
  "Instruction-text detection (AGT-006).", "Flags never change fields or state.",
  "A changed address raises a high-severity flag;A new vendor shows NO_BASELINE rather than clean;Outlier detection matches a hand-computed example",
  "Unit")
T("INV-008","Implement payment-terms confirmation","M1","P0","S","F-035","FR-310–311, BR-075","INV-003 ENG-005",
  "Only human-confirmed terms reach the scheduler.",
  "POST /requests/{id}/terms/confirm validating with the ENG-005 model;store terms and terms_hash;mark confirmed_by",
  "", "",
  "Invalid terms return TERMS_INVALID;Unconfirmed terms are not visible to the scheduler query",
  "Integration")
T("INV-009","Implement submit-for-approval and flag acknowledgment","M1","P0","S","F-036, F-038","FR-313","INV-007 INV-008",
  "A draft becomes approvable only when it is clean or its flags are acknowledged.",
  "POST /submit (Draft → AwaitingApproval) with checks: no duplicate, terms confirmed or none, payee exists;POST /flags/{id}/ack by an Approver",
  "", "",
  "Submit is refused with unconfirmed extracted terms;High flags must be acknowledged before the typed-data endpoint will serve",
  "Integration")
T("INV-010","Implement approval typed data and signature verification","M1","P0","M","F-038","BR-003–BR-005, FR-316–317","INV-009 ENG-010 IDN-008",
  "Approvers sign exactly the fields the contract will check.",
  "GET approval-typed-data;POST approve verifying the signature, the approver's linked wallet, membership in the on-chain approver set and maker-checker;store approval;transition to Approved;Idempotency-Key",
  "", "",
  "A signature over different fields is rejected;Creator approving returns MAKER_CHECKER;A signer not in the on-chain approver set returns NOT_IN_APPROVER_SET",
  "Integration with test keys")
T("INV-011","Implement reject, cancel, invalidation and expiry","M1","P0","S","F-038, F-039","BR-003, FR-317, FR-320","INV-010",
  "Approvals stop being valid when they should.",
  "Reject and cancel endpoints;editing an approved request invalidates the approval and returns it to Draft;periodic task expiring approvals and requests past deadline",
  "", "",
  "An edited approved request is no longer payable;Cancel is refused while a payment is in flight;Expired approvals are marked and require re-approval",
  "Integration")
T("INV-L01","Add the email-forwarding invoice inbox","Later","-","L","F-033","FR-308","INV-004 AGT-004",
  "Create drafts from forwarded emails.", "Per-org inbound address;SPF/DKIM checks;attachment extraction into the upload pipeline", "", "",
  "A spoofed sender is flagged;No draft is auto-approved", "Integration")
T("INV-L02","Add the inbound invoice API with scoped keys","Later","-","M","F-034","FR-309","INV-003",
  "Let other systems create drafts.", "API keys with scopes;idempotent create and bulk endpoints", "", "",
  "A key without invoices:create is refused;Keys cannot approve", "Integration")
T("INV-L03","Add recurring payment schedules","Later","-","M","F-040","FR-321, BR-002","INV-003",
  "Generate periodic drafts.", "Schedule templates;draft generation job;skip a period", "", "",
  "Generated drafts require approval every period", "Integration")
T("INV-L04","Support fiat-denominated invoices","Later","-","L","F-041","FR-322","INV-003 ENG-L02",
  "Accept invoices in fiat with FX conversion.", "Fiat amount and currency on requests;approval binds max stablecoin amount;FX source adapter", "", "",
  "Payment never exceeds the approved maximum stablecoin amount", "Integration")

# ───────────── CHR · Chain Reader & Tx Tracking ─────────────
T("CHR-001","Build the RPC client with failover","M1","P0","M","F-050","NFR-REL-04","TRS-002",
  "Chain access that survives one provider failing.",
  "web3.py wrapper with ordered providers, timeouts, retry and failover;provider health tracking;typed errors (RpcUnavailable)",
  "", "",
  "With the first provider down, calls succeed through the second;With all down, RpcUnavailable is raised and nothing returns a default value",
  "Unit with mocked providers")
T("CHR-002","Implement block-consistent snapshots","M1","P0","M","F-050","BR-051, FR-401–402","CHR-001 TRS-004",
  "One consistent view of balances, counters, payees and mandate at a block.",
  "Batched reads at a single block (multicall or block-pinned calls);snapshot record with block number, hash, observed time, coverage and missing fields;freshness check helper",
  "", "",
  "All values in a snapshot come from the same block;A partial read yields coverage PARTIAL with the missing fields listed",
  "Integration on Anvil")
T("CHR-003","Implement the transaction tracker","M1","P0","M","F-070","BR-053, FR-601","CHR-001 EXE-001",
  "Know the true status of every submitted transaction.",
  "Celery task polling receipts;status Submitted → Pending → Confirmed after N confirmations or Reverted;timeout → Unknown;replacement transactions (same nonce) linked",
  "Reorgs (CHR-004).", "Never set a Failed status on timeout.",
  "A transaction is Confirmed only after the configured depth;A timeout sets Unknown;A replacement with the same nonce is linked to the same operation",
  "Integration on Anvil")
T("CHR-004","Detect reorgs and re-evaluate status","M1","P1","S","F-070","FR-602","CHR-003",
  "A reorg cannot leave a payment falsely marked Paid.",
  "Store block hash per confirmation;re-check on later blocks;demote to Pending when the block hash changes;mark observed events removed",
  "", "",
  "An Anvil reorg simulation moves the transaction back to Pending and the request out of Paid",
  "Integration: reorg simulation")
T("CHR-005","Index module and Safe events","M1","P1","M","F-050, F-120","FR-510","CHR-001 SC-016",
  "Off-chain state follows on-chain events for mandate, payees, payments and pause.",
  "Cursor-based log reader for module events and Safe module-enable events;observed_events table;handlers updating payee status, mandate status and pause state",
  "", "Idempotent by (chain, tx hash, log index).",
  "Re-reading the same range creates no duplicates;PayeeAdded and Paused events update application state",
  "Integration on Anvil")

# ───────────── EXE · Orchestration & Execution ─────────────
T("EXE-001","Create operations (outbox), transactions and gas ledger schema","M1","P0","S","F-061","ADR-004, DATA_MODEL §2.6","INV-001",
  "Durable records for every money-moving step.",
  "Alembic migration and models;unique step_id on operations;indexes by treasury and status",
  "", "", "Inserting two operations with the same step_id fails", "Integration: migration test")
T("EXE-002","Set up Celery with core and ai queues","M1","P0","M","F-060, F-061","ADR-007","DEV-002",
  "A safe job runtime where LLM tasks hold no signing secrets.",
  "Celery app with Redis broker;queues core and ai, two compose services (worker, worker-ai) and beat;base task: idempotency helper, correlation ids, acks_late, reject on worker lost;per-treasury pg_advisory_xact_lock helper",
  "Business tasks.", "worker-ai gets only the LLM key and limited DB credentials.",
  "Two tasks for the same treasury never run their critical section concurrently;A killed worker's task is redelivered;worker-ai has no access to the attestation key or signer secret",
  "Integration: lock contention test")
T("EXE-003","Implement the deadline trigger","M1","P0","M","F-060","FR-501–503","EXE-002 INV-010 MDT-007 TRS-007",
  "The agent starts work by itself when approved requests enter their window.",
  "Beat schedule per treasury;eligibility query (Approved, within lead time or discount window);gates: backend pause flag, mandate active, coverage COMPLETE (or acknowledged), no Unknown operation;enqueue planning",
  "", "Lead time is configurable (24h default, minutes in demo).",
  "An eligible request triggers planning with no user action;A paused treasury or one with an Unknown operation is skipped with a logged reason",
  "Integration")
T("EXE-004","Implement the planning pipeline task","M1","P0","L","F-052–F-056","FR-405–413","EXE-003 CHR-002 ENG-008 POL-006 AGT-009",
  "Turn eligible requests into a validated, attested plan.",
  "Take snapshot;run the engine;request the AI proposal on the ai queue with a timeout;score and select;validate;on ALLOW attest and persist plan and steps;on NEEDS_APPROVAL or BLOCK create review items;write audit records",
  "Execution of steps (EXE-007).", "Split into two PRs if needed: deterministic path first, then AI integration.",
  "With AI disabled the pipeline produces a valid deterministic plan;An AI timeout falls back per BR-055 and records RULE_BASED;NEEDS_APPROVAL creates exactly one review item",
  "Integration on Anvil")
T("EXE-005","Build the signer service","M1","P0","L","F-061","BR-092, ADR-006, FR-507","POL-006 SC-016",
  "The only component that can sign executor transactions, and only for attested steps.",
  "FastAPI service with POST /sign-and-send and GET /health;verify attestation, expiry, nonce;check payload (function, args) matches the attested step;chain id allowlist;simulate (eth_call) then sign and broadcast;shared-secret auth on the internal network",
  "KMS (EXE-L01).", "No database writes. No other endpoints.",
  "A payload that differs from the attested step is refused with PAYLOAD_MISMATCH;A reverted simulation is not broadcast;A non-allowlisted chain id is refused",
  "Unit + integration on Anvil")
T("EXE-006","Load the executor key from an encrypted keystore","M1","P0","S","F-061","NFR-SEC-03","EXE-005",
  "The executor key is never in plain text in the repo, image or environment listing.",
  "Encrypted JSON keystore mounted read-only;password from a Docker secret;health endpoint returns the executor address and gas balance only",
  "", "",
  "The service refuses to start without the keystore or with a wrong password;The private key never appears in logs or the health response",
  "Security: log scan test")
T("EXE-007","Implement the executor with outbox semantics","M1","P0","M","F-061–F-063","BR-060–061, FR-505–506","EXE-005 EXE-001",
  "Each step is recorded before it is signed and its transaction hash is saved before anything else happens.",
  "For each plan step: insert operation NotSubmitted in the same DB transaction as the step state;call the signer;persist tx hash and nonce;hand off to the tracker;idempotent re-entry",
  "Sequencing between steps (EXE-008).", "",
  "A crash between signer response and DB write is recoverable by step id lookup;Re-running the task for a Submitted operation does not call the signer again",
  "Integration with fault injection")
T("EXE-008","Sequence steps with re-read and re-validation","M1","P0","M","F-061","BR-050–051, BR-054","EXE-007 CHR-003 POL-003",
  "Each step runs only after the previous one is confirmed and the world still allows it.",
  "After confirmation take a new snapshot;re-run the validator for the next step;stop and mark partial on BLOCK;mark request Paying then Paid after PAY confirmation",
  "", "",
  "A balance change by the Owner between refill and pay is detected and handled;The next step is not sent while the previous one is Pending",
  "Integration: AT-07, AT-10")
T("EXE-009","Add the operator run-now endpoint","M1","P1","S","F-060","FR-504","EXE-003",
  "Operators can trigger planning immediately, with the same safety gates.",
  "POST /treasuries/{t}/run-now with Idempotency-Key;same gates and errors as the scheduler",
  "", "", "A paused treasury returns TREASURY_PAUSED;The call enqueues exactly one job", "Integration")
T("EXE-010","Track gas fees and alert on low executor gas","M1","P1","S","F-066","BR-025, BR-080, FR-514–515","EXE-007",
  "Fees are visible and the executor does not silently run dry.",
  "gas_ledger entry per transaction including reverts;fee-envelope check before signing;low-balance threshold alert;clear stop reason when gas is insufficient",
  "", "",
  "Every transaction has a fee record;Below the threshold an alert event is emitted;With no gas the operation stops with INSUFFICIENT_GAS and nothing is marked paid",
  "Integration")
T("EXE-011","Execute the swap-for-gas step on the test router","M1","P2","S","F-064","FR-511–512","EXE-008 SC-018",
  "Show a bounded swap inside a plan.",
  "Plan step type SWAP;quote from the configured test source;minOut computed by the engine;labelled TEST ROUTER in records",
  "", "", "A plan with a gas shortage includes a swap step and completes;Records and UI label the router as test", "Integration: AT-04")
T("EXE-L01","Add a KMS-backed signer","Later","-","M","F-061","ADR-006","EXE-005",
  "Move the executor key into a cloud KMS.", "Signer backend interface;AWS/GCP KMS implementation", "", "",
  "Signing works with no key material on disk", "Integration")
T("EXE-L02","Integrate the production swap adapter","Later","-","M","F-065","FR-513","EXE-011 SC-L03",
  "Execute real DEX swaps with verified quotes.", "Quote source adapter;plan step integration", "", "",
  "A stale or forged quote stops the plan", "Integration on a fork")
T("EXE-L03","Add cross-chain bridging","Later","-","L","F-067","FR-516","TRS-L01",
  "Move liquidity between treasuries on different chains.", "Bridge adapter;in-flight accounting;timeout handling", "", "",
  "No second bridge transfer is sent on timeout", "Integration")
T("EXE-L04","Partition workers by treasury for scale","Later","-","M","F-061","NFR-SCAL-03","EXE-002",
  "Scale execution horizontally while keeping per-treasury order.", "Queue routing by treasury hash;autoscaling notes", "", "",
  "Per-treasury sequencing holds under load", "Load test")

# ───────────── REC · Verification & Reconciliation ─────────────
T("REC-001","Verify post-conditions after each confirmed step","M1","P0","M","F-071","FR-603–604","EXE-008",
  "Confirm the chain state matches what the plan expected.",
  "Expected deltas per step type;read post-state;verification record PASSED, DISCREPANCY or UNKNOWN;discrepancy creates a review item and a circuit-breaker signal",
  "", "",
  "A normal pay verifies PASSED;An unexpected balance yields DISCREPANCY with expected and observed values",
  "Integration on Anvil")
T("REC-002","Build reconciliation records with classification","M1","P0","M","F-072","BR-096, FR-605","REC-001",
  "Every paid request has a complete, classified transaction set.",
  "Schema migration;on Paid create a reconciliation with lines: refill = INTERNAL_TRANSFER, swap = CONVERSION, pay = EXTERNAL_EXPENSE, gas = FEE;status Pending",
  "", "",
  "A request with refill and pay has two lines plus fee lines with correct classes;A refill without a successful pay shows no expense",
  "Integration")
T("REC-003","Implement match, discrepancy and auto-match","M1","P0","S","F-072","FR-606","REC-002",
  "Finance can close out a payment with evidence.",
  "GET list with filters;POST match and discrepancy;auto-match when the org setting is on and all evidence matches",
  "", "", "Match is refused when evidence is incomplete;Auto-match is off by default", "Integration")
T("REC-004","Export reconciliation CSV and journal lines","M1","P1","M","F-073","FR-607","REC-003",
  "Hand accounting a file they can use.",
  "CSV export for a period;journal format with a generic account mapping and per-org mapping table;formula neutralization;totals check",
  "", "",
  "Export totals equal on-chain totals for the period;Unmatched items are included with their status",
  "Integration")
T("REC-005","Publish on-chain payment attestations","M1","P2","S","F-074","FR-608","REC-003 SC-019",
  "A third party can verify a payment without access to the app.",
  "Task that attests after Matched (or Paid by setting);store UID;retry without affecting payment status",
  "", "", "The UID resolves on the explorer;The attestation contains no personal data", "Integration on testnet")
T("REC-L01","Build the ERP integration framework with Xero","Later","-","L","F-075","FR-609","REC-004",
  "Sync bills and payments with an accounting system.", "Connector interface;OAuth;bills in as drafts;payments out with tx reference;Xero adapter", "", "",
  "A synced bill is never approved by the sync", "Integration with sandbox")
T("REC-L02","Add the QuickBooks connector","Later","-","M","F-075","FR-609","REC-L01", "QuickBooks sync.", "Adapter on the connector interface", "", "", "Same contract tests as Xero pass", "Integration")
T("REC-L03","Add the NetSuite connector","Later","-","M","F-075","FR-609","REC-L01", "NetSuite sync.", "Adapter on the connector interface", "", "", "Same contract tests as Xero pass", "Integration")

# ───────────── RCV · Recovery & Exceptions ─────────────
T("RCV-001","Scan in-flight operations at startup","M1","P0","S","F-080","BR-060, FR-701–702","EXE-007",
  "Nothing new happens until old work is understood.",
  "On worker start and periodically: load operations in NotSubmitted, Submitted, Pending, Unknown;enqueue resolution;flag treasuries as blocked while any remain",
  "", "", "A treasury with an Unknown operation is skipped by the trigger;The scan runs on every worker start", "Integration")
T("RCV-002","Resolve unknown operations from chain evidence","M1","P0","M","F-080","BR-060–061","RCV-001 CHR-003",
  "Decide the true outcome of an uncertain operation without guessing.",
  "Resolution order: receipt by tx hash, then account nonce, then module used(stepId)/used(requestId);outcomes: Confirmed, Reverted, still Pending, or safe to submit with the same ids;escalate to review after a threshold",
  "", "No AI involvement.",
  "If the chain shows the step used, the operation becomes Confirmed without resubmission;A never-broadcast operation is resubmitted with the same step id",
  "Integration with fault injection")
T("RCV-003","Handle partial completion and resume","M1","P0","S","F-081","BR-054, FR-703","EXE-008",
  "A blocked later step never undoes or repeats an earlier one.",
  "Plan status PartiallyCompleted;resume runs only unfinished steps after re-validation;cancel leaves funds where they are and reports it",
  "", "", "After refill succeeded and pay was blocked, a retry sends only the pay;No second refill occurs", "Integration: AT-07")
T("RCV-004","Implement the review queue and routing","M1","P0","M","F-082","FR-704–705","INV-002",
  "Every stop becomes one actionable item for the right role.",
  "review_items schema;creation rules per outcome type;routing table (over-cap → Owner, payee/budget → Owner policy edit, amount/payee → re-approval, infra → Operator);list and action endpoints;SLA due time",
  "UI (WEB-013).", "",
  "Each non-ALLOW outcome creates exactly one open item;Acting on a stale item returns STALE_ITEM;Only the routed role can act",
  "Integration")
T("RCV-005","Implement retry policy and error classification","M1","P0","S","F-083","BR-061, FR-706","EXE-007",
  "Transient errors are retried safely; everything else stops.",
  "Classifier: retryable (RPC, timeout before broadcast, nonce too low, underpriced) vs terminal;exponential backoff with max attempts;ids never regenerated",
  "", "", "A 503 from the RPC is retried and succeeds;After max attempts a review item is created;Ids are identical across attempts", "Unit + integration")
T("RCV-006","Implement circuit-breaker rules and auto-pause","M1","P2","M","F-027","BR-065, FR-222","REC-001 MDT-007",
  "Stop automatically when something looks wrong.",
  "Rule evaluation on events: ≥3 contract rejections in 10 minutes, AI plan out of mandate, coverage drop, post-condition discrepancy;action alert or pause;circuit_events;cool-down",
  "", "", "Three injected rejections pause the treasury within one evaluation cycle;Only the Owner can resume", "Integration")
T("RCV-007","Automate the crash-recovery test","M1","P0","S","F-080","NFR-REL-02","RCV-002",
  "Prove there is never a double payment when the executor dies mid-flight.",
  "Test harness that kills the worker at randomized points around signer call and DB write, restarts it and asserts exactly one PAY on-chain;20 iterations",
  "", "This is demo scene 6 and key evidence.",
  "20 of 20 iterations end with exactly one payment and a Paid request",
  "Integration: crash suite")
