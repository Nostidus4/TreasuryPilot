"""Revisions from the M05 (invoices & approvals) grilling round, 2026-10-11. Applied after r03_m08."""
from ._base import TICKETS, T

def _rev(tid, **kw):
    t = next(x for x in TICKETS if x["id"] == tid)
    for k, v in kw.items():
        if k in ("scope", "ac", "tests"): v = [s.strip() for s in v.split(";") if s.strip()]
        if k == "deps": v = v.split()
        t[k] = v

D = "docs/modules/invoices"
_rev("INV-001",
  scope=f"Alembic migration and models per {D} §4 (payment_requests with issue_date, invoice_hash, onchain_request_id, source, cancel_onchain; request_revisions; documents; flags with revision and status; approvals with acknowledged_flag_ids and solo_mode; csv_imports; request_status_events);partial unique index (treasury_id, fingerprint) excluding Rejected/Cancelled/Expired;optimistic-lock version column;append-only triggers on approvals (except status) and status events",
  ac="Migration applies and downgrades;The duplicate-fingerprint index rejects a second active request but allows one after the first is Cancelled;UPDATE of approval fields other than status is refused by the DB")
_rev("INV-002",
  scope=f"Transition table as data per {D} §5 (incl. withdraw, request-changes, renew, Expired, SYSTEM-only transitions);transition(request, to, actor) with role and guard checks;request_status_events and audit writes;refuse Cancelled while a PAY operation is NotSubmitted/Submitted/Pending/Unknown",
  ac="Every legal transition in §5 is allowed and every other pair is rejected;SYSTEM transitions are refused for user actors;Each transition writes a status event and an audit record;Paid, Rejected and Cancelled are terminal")
_rev("INV-003",
  scope="POST /requests and PATCH with If-Match;validation: vendor exists, payee belongs to the vendor and is not Deactivated, asset equals the treasury stablecoin, amount positive with ≤ asset decimals, dates valid;bound vs free fields (M05-D6): bound edit → new revision, approvals Invalidated, flags recomputed, status Draft;free-field edits without revision;onchain_request_id = keccak('TP_REQ_V1', orgId, uuid);invoice_hash per §3;creator and last editor recorded;Idempotency-Key",
  ac="Wrong asset returns ASSET_NOT_PAYMENT_STABLECOIN;A payee of another vendor returns PAYEE_NOT_OF_VENDOR;Editing the amount of an Approved request invalidates the approval and returns it to Draft;Editing the note does not;A stale If-Match returns 412")
_rev("INV-004",
  scope="POST /requests/upload (PDF, PNG, JPG ≤ 10 MB, ≤ 20 pages, type checked by magic bytes);store in the private bucket with sha256;documents record;signed URL for viewing;enqueue extraction on the ai queue;POST extraction/confirm storing final fields and extraction_confirmed_by;MULTI_INVOICE_DOCUMENT when M09 reports more than one invoice",
  ac="Unsupported type returns 415 and oversize returns 413;A renamed executable with a .pdf name is refused;Files are not publicly readable;Submit is refused with EXTRACTION_UNCONFIRMED until the form is confirmed")
_rev("INV-005",
  scope=f"CSV template per {D} §7.2;UTF-8 (BOM allowed) and exact header validation;row-by-row validation (vendor by normalized_ref, payee must belong to vendor, amount precision, ISO dates);fingerprint check against DB and earlier rows;flags per row;dryRun mode;csv_imports record;downloadable error report with formula neutralization;max 1,000 rows",
  ac="500 valid rows import in under 10 seconds;Invalid rows are reported with row number, field and code;Two rows with the same fingerprint: the second is rejected;Cells starting with = + - @ are neutralized in the error report;dryRun writes nothing")
_rev("INV-006",
  scope="Normalization per §8.1 (NFKC, casefold, strip separators) shared with ENG-009;fingerprint on create, edit and submit;duplicate check among active requests of the treasury;DUPLICATE_FINGERPRINT blocks submit with existingRequestId;submit allowed for the one request named in an on-chain allowDuplicate")
_rev("INV-007", refs="FR-312, BR-072, BR-066, OQ-10",
  scope=f"Flag rules per {D} §8.4–8.5: ADDRESS_CHANGED, ADDRESS_NOT_REGISTERED, FIRST_PAYMENT_TO_PAYEE, NO_BASELINE, AMOUNT_OUTLIER (median ± 3·max(1.4826·MAD, 2 % median), n ≥ 5, integer median), CURRENCY_MISMATCH, CHAIN_MISMATCH, DUE_DATE_PAST, DUE_DATE_FAR, DUE_BEFORE_ISSUE, AI_UNAVAILABLE;flags stored per revision, old ones Superseded;severity, evidence and code per flag",
  ac="A changed address raises ADDRESS_CHANGED HIGH;A new vendor shows NO_BASELINE rather than clean;The §8.4 example flags 1,100 and not 1,050;Identical recurring amounts with one cent difference do not flag;Flags never change fields or state",
  tests="Unit: one test per rule; property: flags are a pure function of the revision and history")
_rev("INV-009",
  scope="POST /submit (Draft → AwaitingApproval) with the §5 guards;POST /withdraw and /request-changes;POST /flags/{id}/ack by an Approver with a note ≥ 10 characters, only for Open flags of the current revision, maker-checker applies",
  ac="Submit is refused with unconfirmed extracted terms or fields;Acknowledging a Superseded flag returns FLAG_SUPERSEDED;High flags must be acknowledged before the typed-data endpoint will serve;The creator cannot acknowledge flags")
_rev("INV-010", refs="BR-003–BR-007, FR-316–318, M05-D1",
  scope=f"GET approval-typed-data built server-side from the current revision (11 fields, expiry = min(deadline + 14 d, now + approvalMaxAge));POST approve with {{signature, revision}} running {D} §8.6 steps 1–8 (revision, linked wallet, maker-checker/solo mode, HIGH flags acked, rebuild, ECDSA or ERC-1271, on-chain approver set, store with acknowledged_flag_ids);transition to Approved;Idempotency-Key",
  ac="A signature over a client-modified message is rejected;A stale revision returns REVISION_CHANGED;Creator approving returns MAKER_CHECKER unless solo mode, which is recorded;A signer not in the on-chain approver set returns NOT_IN_APPROVER_SET;An ERC-1271 mock wallet can approve")
_rev("INV-011", refs="BR-003, BR-077, FR-317, FR-320, FR-324", deps="INV-010 SC-022",
  scope="Reject (terminal) endpoint;cancel endpoint with PAYMENT_IN_FLIGHT guard and cancel_onchain = Pending when an approval was ever Valid;GET cancel-tx building cancelRequest(requestId) for an approver wallet or a Safe tx for the Owner;RequestCancelled event sync → Confirmed;periodic task (5 min) expiring approvals and requests;renew endpoint (Expired → Draft, new revision)",
  ac="An edited approved request is no longer payable;Cancel is refused while a payment is in flight;A cancelled, previously approved request shows Cancel on-chain until RequestCancelled is observed;Expired approvals are marked and require renew plus re-approval")
_rev("MDT-004", refs="FR-211, BR-085, M05-D2",
  scope="Vendor CRUD with normalized_ref (unique per org) and optional tax_id;POST /payees under a vendor creating a payee in Screening and running the screening adapter;result stored;hit → blocked",
  ac="A screening hit returns SCREENING_HIT and the payee cannot proceed;Provider error blocks registration;Duplicate address is rejected;A second vendor with the same normalized_ref returns VENDOR_REF_EXISTS")
next(x for x in TICKETS if x["id"] == "POL-002")["scope"].append("REQUEST_CANCELLED when the request is Cancelled off-chain or requestCancelled on-chain")
_rev("WEB-007",
  scope="Filterable list by status and due date;vendor picker with payees of that vendor;create and edit form with field errors (bound vs free fields, warning that a bound edit invalidates the approval);revision history;duplicate warning with link;cancel with reason and Cancel on-chain banner")
_rev("WEB-009",
  scope="Inbox list;detail with document, fields, history diff vs vendor, flags with evidence (incl. POSSIBLE_DUPLICATE side-by-side), confirmed terms;acknowledge high flags with a note;display the server typed data and sign with the wallet;reject or request changes with reason;maker-checker message;Cancel on-chain button sending cancelRequest from the approver wallet")

T("INV-012","Detect near-duplicate requests","M1","P0","S","F-036, F-037","BR-076, FR-323, M05-D5","INV-006",
  "Catch invoices re-submitted with a slightly altered number, without bothering recurring payments.",
  f"Candidate query: same vendor, same amount, issue dates within 45 days, status not Rejected/Cancelled, different fingerprint;Damerau-Levenshtein distance on normalized invoice numbers;POSSIBLE_DUPLICATE HIGH when d ≤ 2, LOW otherwise, evidence with the other request id;index (vendor_id, amount, issue_date)",
  "Exact duplicates (INV-006).",
  "Pure-Python distance function (no new dependency).",
  f"INV-2026-0412 vs INV-2026-0421 raises HIGH;RENT-SEP vs RENT-OCT raises LOW;Different amounts raise nothing;Runs in < 50 ms with 10,000 requests per vendor",
  "Unit: examples in docs/modules/invoices §8.3; performance test")
T("SC-022","Add on-chain request cancellation","M1","P0","S","F-039","BR-077, FR-324, M05-D4","SC-006 SC-009",
  "A cancelled request can never be paid, even by a compromised backend.",
  "requestCancelled mapping;cancelRequest(requestId) callable by safeT or any current approver, idempotent, works while Paused;reverts NotOwnerOrApprover and AlreadyPaid;pay and refill revert RequestCancelled;RequestCancelled(requestId, by) event;invariant I11 in SC-014",
  "Undo of a cancellation (cancellation is permanent).",
  "An approver key compromise can only cancel (denial of service), never pay; documented in known-risks.",
  "An approver and Safe T can cancel, a stranger cannot;Pay and refill for a cancelled id revert RequestCancelled;Cancelling a paid request reverts AlreadyPaid;Cancel works while Paused",
  "Unit + invariant I11")

_rev("SC-014", deps="SC-013 SC-022",
  scope="Handler contract driving pay/refill/pause/configure/grantException/cancelRequest with bounded random inputs;invariants I1–I11 from docs/modules/contracts §10 (I10 = refill bound, I11 = cancelled never pays);10k-run configuration",
  ac="Invariants I1–I11 pass at 10k runs;Each invariant is mapped to its BR in a comment;A deliberately broken check makes the matching invariant fail")
