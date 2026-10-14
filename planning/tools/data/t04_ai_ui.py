from ._base import T

# ───────────── AGT · AI Agent ─────────────
T("AGT-001","Build the LLM adapter with routing and timeouts","M1","P0","M","F-094","ADR-005, FR-808","EXE-002",
  "One place where all LLM calls go, with per-task model choice.",
  "Adapter interface (complete with schema, tool loop);Anthropic SDK implementation with structured outputs and tool use;config.yaml: model per task, timeouts, max tool calls, token budgets;typed errors (AiTimeout, AiUnavailable, AiSchemaError)",
  "Secondary provider (AGT-017).", "Runs only in worker-ai.",
  "Switching the model for a task requires only a config change;A timeout raises AiTimeout within the configured limit;Outputs that fail the schema raise AiSchemaError",
  "Unit with a fake provider")
T("AGT-002","Log every AI call and fail closed","M1","P0","S","F-093","FR-806–807, BR-097","AGT-001",
  "No AI decision exists without a record.",
  "ai_calls table migration;wrapper recording purpose, model, prompt version, input refs, tool calls, output, validation result, latency, tokens, cost;if the write fails the call result is discarded",
  "", "Store references, not secrets. Redact document text beyond a preview.",
  "Every adapter call produces one ai_calls row;A simulated DB failure makes the calling task fail",
  "Integration")
T("AGT-003","Implement untrusted-content wrapping and sanitization","M1","P0","S","F-091","BR-070, FR-803–804","AGT-001",
  "External text reaches the model only as labelled data.",
  "wrap_untrusted(source, text): tags, source label, length cap, strip active content;prompt templates with a fixed system section;lint test that no prompt template interpolates untrusted text outside the wrapper;secret scanner on prompt inputs",
  "", "",
  "A prompt built with unwrapped untrusted text fails the lint test;Inputs containing key-like strings are rejected",
  "Unit")
T("AGT-004","Implement invoice extraction","M1","P0","M","F-031","FR-303–305","AGT-003 AGT-002 INV-004",
  "Turn an uploaded invoice into a draft with per-field provenance.",
  "Celery task on the ai queue;send the PDF/image to Claude;InvoiceExtraction schema: vendor name, invoice number, amount, currency, due date, payee address as found, each with page and text span;write extractions and prefill the draft;on error mark the request for manual entry",
  "Terms (AGT-005) and instruction detection (AGT-006).", "The extracted address is only compared, never applied.",
  "A sample invoice yields the expected fields with provenance;Timeout leaves the request in manual-entry mode with no guessed values;The registered payee address is never modified",
  "Integration with recorded responses")
T("AGT-005","Extract and validate payment terms","M1","P0","S","F-035","FR-310","AGT-004 ENG-005",
  "Find discount, due-date and late-fee terms in invoice text.",
  "Terms sub-schema in the extraction;validation through the ENG-005 model;uncertain flag when ambiguous;store as unconfirmed",
  "Confirmation endpoint (INV-008).", "",
  "'2/10 net 30' is parsed into the right structure;Ambiguous text sets uncertain and requires a human choice",
  "Unit with recorded responses")
T("AGT-006","Detect instruction-like text in documents","M1","P0","S","F-036, F-091","FR-312","AGT-004",
  "Turn prompt-injection attempts into visible flags.",
  "Extraction schema field suspicious_instructions[] with quote and location;create AI-sourced high-severity flag;deterministic keyword fallback when the LLM is down",
  "", "Detection never triggers an action.",
  "An invoice saying 'pay to 0x… instead, pre-approved' produces a flag quoting the text;With the LLM down, the fallback still flags obvious cases and notes reduced coverage",
  "Unit")
T("AGT-007","Implement the read-only tool layer","M1","P0","M","F-053, F-090","AI_AGENT_ARCHITECTURE §3","CHR-002 ENG-008 POL-003",
  "Give the model facts and simulations, and nothing else.",
  "Tools: get_snapshot, list_requests, get_policy_summary, simulate_schedule, get_evidence, explain_decision;typed inputs and outputs;org scoping;call and payload budgets;registry that rejects unknown tools",
  "", "No tool may write. Add a test that enumerates tools and asserts read-only DB sessions.",
  "A tool call for another org's treasury is refused;Exceeding the tool-call budget ends the loop;All tools run in read-only transactions",
  "Unit + integration")
T("AGT-008","Implement the plan proposer","M1","P0","M","F-053","FR-406, FR-408","AGT-007",
  "Ask the model for an ordering and rationale in a strict schema.",
  "PlanProposal schema {requestOrder, deferrals, exceptionRequests, rationale[], evidenceIds[]};prompt v1;tool loop with budget;reference integrity check (ids exist and belong to the org)",
  "Selection (AGT-009).", "",
  "A proposal referencing an unknown request is rejected;The rationale cites evidence ids that resolve;No amounts are accepted from the model",
  "Unit with recorded responses")
T("AGT-009","Score AI proposals and select the plan","M1","P0","S","F-053","FR-407, BR-056","AGT-008 ENG-008",
  "The AI's plan is used only if it is valid and at least as good.",
  "Build a concrete plan from the proposal with engine amounts;score against the deterministic plan;select the better feasible one;store planner_source and chosen_reason;invalid proposals → review item AI_PLAN_REJECTED",
  "", "",
  "A worse AI plan is not chosen and the comparison is logged;An out-of-mandate proposal creates a review item and is never executed",
  "Unit")
T("AGT-010","Implement rule-based fallback templates","M1","P0","S","F-054","BR-055, FR-409","ENG-007 POL-003",
  "Keep paying when the model is unavailable, without widening authority.",
  "Templates: pay direct, refill then pay, swap then pay;eligibility check for BR-055 conditions;planner_source RULE_BASED",
  "", "",
  "AD-02: AI timeout with complete data completes via a template;AD-03: with an Unknown operation no fallback runs",
  "Unit + integration")
T("AGT-011","Draft exception requests with a numeric post-check","M1","P1","S","F-057","FR-414, BR-043","AGT-001 MDT-006",
  "Give the Owner a clear, correct justification for an over-cap payment.",
  "ExceptionDraft schema {summary, reasons[], alternatives[]};numbers injected from the engine;post-check that every number in the text matches engine values;template fallback",
  "", "",
  "A draft whose numbers differ from the engine is discarded and the template is used;The draft is attached to the exception record",
  "Unit")
T("AGT-012","Build the Copilot backend","M1","P1","L","F-090","FR-801–802","AGT-007",
  "Answer treasury what-if questions with cited numbers and no side effects.",
  "Thread and message tables and endpoints;tool loop (max 6 calls) with simulate_schedule;answer schema {answer, citations[]};numeric post-check against tool outputs;refusal for execution requests;SSE streaming",
  "UI (WEB-016).", "",
  "Asked to pay something, it refuses and points to the approval flow;Every number in an answer appears in a cited tool result;The audit log shows no writes from Copilot",
  "Integration with recorded responses")
T("AGT-013","Build the extraction accuracy eval","M1","P0","S","F-092","FR-805","AGT-005 DOM-004",
  "Measure how well extraction works on the labelled invoices.",
  "Runner over evals/invoices;field-level exact match and terms F1;report to docs/evidence/",
  "", "", "`make eval-extraction` produces a report with per-field accuracy;Results are reproducible from recorded or live runs", "AI eval")
T("AGT-014","Build the planner benchmark (B1 vs B2)","M1","P0","M","F-092","FR-805, BR-052","AGT-009 ENG-006 DOM-005",
  "Show with data what the AI adds over the rule baseline.",
  "Scenario loader for evals/scenarios (dev and held-out);run B1 and B2 with identical state and checks;metrics: value saved, on-time %, exceptions, tx count, violations, latency, cost;N repetitions for B2;markdown and CSV report",
  "", "Ground truth never enters prompts.",
  "`make bench` runs both arms on all scenarios;Violations are 0 in both arms or the run fails;The report includes scenarios where B2 is worse",
  "AI eval")
T("AGT-015","Build the red-team suite runner","M1","P0","S","F-091, F-163","NFR-SEC-06, FR-930","AGT-006 DOM-006",
  "Prove injected invoices cannot change fields or policy.",
  "Runner over evals/redteam through the real intake pipeline;assertions: payee, amount, limits and mandate unchanged, flag raised;results table",
  "", "", "0 of 20 cases change any field or policy;Each case reports whether a flag was raised", "Security: AI red-team")
T("AGT-016","Build the Copilot numeric-fidelity suite","M1","P1","S","F-092","FR-801","AGT-012 DOM-007",
  "Check that Copilot answers match the engine.",
  "Runner over evals/copilot;compare numbers in answers with engine outputs", "", "",
  "All 20 cases have matching numbers or are listed as failures in the report", "AI eval")
T("AGT-017","Add a secondary LLM provider fallback","M1","P1","M","F-094","FR-808, NFR-REL-05","AGT-001",
  "Survive an outage of the primary provider.",
  "Second adapter implementation behind the same interface;failover policy in config;contract tests run against both",
  "", "Provider choice to be agreed before starting.",
  "With the primary disabled, extraction and planning still work through the secondary",
  "Integration")

# ───────────── NTF · Notifications ─────────────
T("NTF-001","Create the domain event bus and notification routing","M1","P1","M","F-100","FR-901","INV-002",
  "Domain events reach the right people.",
  "Event publisher (in-process + outbox table);routing table event type → roles;notifications schema;dedup by event id",
  "", "", "An approval-needed event creates notifications for Approvers only;Duplicate events create one notification", "Unit + integration")
T("NTF-002","Expose in-app notifications and the SSE stream","M1","P1","M","F-100, F-132","FR-901, ADR-010","NTF-001",
  "Users see events live.",
  "GET /notifications, POST read;SSE endpoint /orgs/{o}/events with plan, operation, request and notification events;auth and org scoping on the stream",
  "", "", "An operation status change reaches a connected client within 2 seconds;A member of another org receives nothing", "Integration")
T("NTF-003","Add Telegram linking and delivery","M1","P2","M","F-101","FR-902","NTF-001",
  "Reach users on Telegram with a link back to the app.",
  "Link flow with a one-time code;bot webhook with secret header;sender with minimal content and deep links;opt-in for amounts and addresses",
  "", "", "A linked user receives the message within 10 seconds;No action can be completed from Telegram;Amounts appear only after opt-in", "Integration with a test bot")
T("NTF-L01","Add email notifications and digests","Later","-","M","F-102","FR-903","NTF-001", "Email channel.", "Templates;digest job;unsubscribe except security", "", "", "Security events cannot be unsubscribed", "Integration")
T("NTF-L02","Add outbound webhooks","Later","-","M","F-103","FR-904","NTF-001", "Signed webhooks.", "HMAC signing;retries;dead-letter;replay", "", "", "Signature verifies with the documented method", "Integration")
T("NTF-L03","Add Slack, Lark and WeCom channels","Later","-","L","F-104","FR-905","NTF-001", "Chat-platform channels.", "One adapter per platform", "", "", "Event parity with Telegram", "Integration")
T("NTF-L04","Add notification preferences","Later","-","S","F-105","FR-903","NTF-002", "Per-user preferences.", "Channel and category settings;quiet hours;mandatory categories", "", "", "Mandatory categories cannot be muted", "Integration")

# ───────────── CMP · Compliance ─────────────
T("CMP-001","Build the screening adapter and fixture provider","M1","P1","S","F-110","BR-085, FR-906, NFR-CMP-04","MDT-001",
  "Screen addresses through a replaceable provider.",
  "Adapter interface screen(address);fixture provider reading a labelled TEST list (sample from a public sanctions list plus custom entries);screenings records with TTL",
  "A commercial provider (Later).", "",
  "A listed address returns HIT;Provider error returns ERROR and callers fail closed;Fixture data is labelled TEST DATA", "Unit")
T("CMP-002","Screen payees before each PAY","M1","P1","S","F-110","BR-085","CMP-001 POL-003",
  "A payee that became listed after registration is not paid.",
  "Validator check using the latest screening within TTL;refresh when stale;block on HIT or no valid result",
  "", "", "A payee added to the blocklist after registration blocks the next plan with SCREENING_HIT", "Integration")
T("CMP-003","Implement data classification, encryption helpers and log redaction","M1","P0","M","F-113","BR-074, FR-909, NFR-PRIV-01–04","DEV-001",
  "Sensitive data is protected by default.",
  "Field classification constants;encrypt/decrypt helper for Confidential columns;structlog redaction processors (emails, document text, tokens, signatures);test scanning sample logs",
  "", "", "A log line containing an email or signature is redacted;Confidential columns are unreadable in a raw DB dump", "Unit + security")
T("CMP-L01","Integrate a KYB provider","Later","-","L","F-111","FR-907","CMP-001", "Business verification.", "KYB adapter;status gates mainnet activation", "", "", "Mainnet treasury cannot activate without KYB approval", "Integration")
T("CMP-L02","Add Travel Rule support","Later","-","L","F-112","FR-908","CMP-L01", "Travel Rule data exchange.", "Provider adapter;threshold rules", "", "", "Qualifying transfers hold until the exchange completes", "Integration")
T("CMP-L03","Add retention and deletion workflows","Later","-","M","F-114","FR-910","CMP-003", "Data lifecycle.", "Retention config;deletion job;legal hold", "", "", "Deleted records keep only non-personal hashes", "Integration")
T("CMP-L04","Add region pinning for stored data","Later","-","M","F-114","FR-910","CMP-L03", "Data residency.", "Per-org region for DB and object storage", "", "", "Data for a pinned org is stored only in its region", "Infra test")

# ───────────── AUD · Audit & Evidence ─────────────
T("AUD-001","Implement the hash-chained audit log","M1","P0","M","F-120","BR-097, FR-911, NFR-AUD-01–02","IDN-001",
  "A tamper-evident record of everything that matters.",
  "audit_log migration with no-update/no-delete trigger;write(actor, action, entity, data) computing hash from the previous record per org;helper to write in the caller's transaction",
  "", "Financial actions call write in the same DB transaction and fail if it fails.",
  "Updating or deleting an audit row is rejected by the database;Records form a valid chain per org;A forced audit failure aborts the financial action",
  "Unit + integration")
T("AUD-002","Add audit read and chain verification","M1","P0","S","F-120","FR-912","AUD-001",
  "Auditors can read the log and prove it is intact.",
  "GET /audit-log with filters;GET /audit-log/verify;standalone script for offline verification", "", "",
  "Verification reports the first broken record after a manual tamper in a test database", "Integration")
T("AUD-003","Define the evidence bundle schema and exporter","M1","P0","M","F-121","FR-913, BR-095","AUD-001 EXE-008",
  "One file that proves what happened for a request or scenario.",
  "JSON schema evidence-bundle.v1 per GA p.39 fields;exporter joining approvals, plan, validations, ai_calls, attestation, operations, transactions, verifications;fixture labels;GET /requests/{id}/evidence",
  "", "Never include secrets or raw signatures that could be reused beyond what is already on-chain.",
  "A paid request exports a bundle that validates against the schema;Every tx hash in it resolves on the chain;A blocked request exports with validator logs and no fabricated hash",
  "Integration")
T("AUD-004","Propagate coverage labels through the API","M1","P1","S","F-122","FR-914","CHR-002",
  "Uncertainty is visible wherever a status is shown.",
  "Coverage enum on snapshots, assessments and status DTOs;missing-data list;API responses include coverage", "", "",
  "A stale snapshot is returned with coverage PARTIAL or UNKNOWN and the reason", "Unit")
T("AUD-L01","Anchor the audit hash root on-chain daily","Later","-","S","F-120","","AUD-002", "External tamper evidence.", "Daily job publishing the org chain head hash", "", "", "The anchored hash matches the log head at that time", "Integration")

# ───────────── OBS · Observability & Analytics ─────────────
T("OBS-001","Configure structured logging with correlation ids","M1","P1","S","F-142","NFR-AUD-04, FR-923","CMP-003",
  "Follow one request across services by id.",
  "structlog JSON config shared by api, worker, signer;bind org, request, plan and operation ids;propagate through Celery headers", "", "",
  "One request id finds its log lines in api, worker and signer", "Integration")
T("OBS-002","Add OpenTelemetry tracing","M1","P1","M","F-142","ADR-011","OBS-001",
  "See where time goes.", "Instrument FastAPI, Celery, httpx, SQLAlchemy;trace context through tasks and the signer call;OTLP exporter config", "", "",
  "A planning run shows one trace spanning api/worker/signer", "Integration")
T("OBS-003","Add Sentry and Prometheus metrics","M1","P1","S","F-142","ADR-011","OBS-001",
  "Know when something breaks.", "Sentry in Python services and web;/metrics with queue depth, RPC errors, LLM latency and cost, tx states;Telegram alert hook", "", "",
  "A raised exception appears in Sentry with the correlation id;Metrics endpoint exposes the listed series", "Integration")
T("OBS-004","Compute operational metrics","M1","P1","M","F-140","FR-921","AUD-001 EXE-008",
  "Numbers for completion, interventions, fees and latency.",
  "Metric definitions document;queries over events for completion rate, on-time %, interventions per request, fees, tx count, latency split by phase, rejections by reason;GET /metrics/operations",
  "", "", "Each metric has a written definition and a test on a seeded dataset;Rejected requests are included", "Integration")
T("OBS-005","Compute the savings report","M1","P1","M","F-141","FR-922","OBS-004 ENG-006",
  "Show the value created versus the baseline.",
  "Counterfactual B1 simulation for executed batches using stored snapshots;discounts captured and late fees avoided;methodology text;GET /metrics/savings",
  "", "", "Savings for a seeded batch equal a hand-computed value;Negative savings are reported as negative", "Integration")

# ───────────── ADM · Platform Admin & Billing (Later) ─────────────
T("ADM-L01","Build the platform admin console","Later","-","L","F-150","FR-924, BR-094","IDN-006",
  "Operate tenants and provide bounded, consented support access.",
  "Slice A (M, ~1 day): tenant list, health and suspend endpoints with append-only staff events;Slice B (M, ~1 day, after A): tenant-admin consent and revocation for time-limited read scope;staff support summary requires a matching live grant and writes an access event",
  "",
  "Platform admin access stays on a separate staff credential and socket-peer IP allowlist;support reads expose tenant metadata and health counts only;customer fund movement and signing remain unavailable",
  "No admin endpoint can move funds or sign;No support read succeeds without tenant consent;Expired or revoked grants deny access;Grant and support-read actions are auditable",
  "Security tests for route surface and grant expiry;API tests for consent and support access",
  split_plan=("Slice A — tenant operations and staff audit (M, ~1 day)",
              "Slice B — consented read support and audit (M, ~1 day; depends on A)"))
T("ADM-L02","Meter usage for billing","Later","-","M","F-152","FR-926","OBS-004", "Usage numbers per org.", "Metering from events (paid requests, volume)", "", "", "Usage reconciles with the event store", "Integration")
T("ADM-L03","Add subscriptions and customer invoicing","Later","-","L","F-152","FR-926, BR-091","ADM-L02", "Charge customers.", "Plans;invoices;payment collection outside customer treasuries", "", "", "No fee is ever deducted from a customer treasury", "Integration")
