# M09 · AI Agent (`worker-ai` + read-only tools)

**Status:** Detailed and reviewed with the project lead (2026-10-11) · **Path:** `docs/modules/agent/` · **Code:** `services/worker/src/treasurypilot_worker/agent/` (runs only in the `worker-ai` container), `packages/py-core/.../ai_schemas` · **Epic:** `[EPIC] M09 · AI Agent`
**ADRs:** ADR-005 (Claude, advisory only) · **See also:** `docs/AI_AGENT_ARCHITECTURE.md` · **Decisions:** M09-D1 … M09-D14 (§14)

---

## 1. Purpose and boundaries

The AI makes TreasuryPilot **faster and smarter, never more powerful**. It reads invoices, finds terms and suspicious text, proposes a payment ordering with a rationale, drafts exception requests and answers questions — always in strict schemas, through read-only tools, with every number coming from or checked against deterministic code.

| The AI may | The AI may never |
|---|---|
| Extract fields and terms (drafts for humans to confirm) | Approve, change payee/amount, add payees, raise limits, edit policy (BR-002) |
| Flag instruction-like text | Write to the database or call the chain |
| Propose an ordering/deferral among engine-valid options | Supply amounts used for execution |
| Explain decisions and draft exception text | Be a permission condition via confidence (BR-058) |
| Answer what-if questions with cited tool results | Receive secrets (BR-092) |

## 2. Features, requirements and rules

| Feature | FR | BR |
|---|---|---|
| F-031 Extraction (AI part) | FR-303–305 | BR-070, BR-072, BR-075 |
| F-035 Terms extraction | FR-310 | BR-075 |
| F-036 Instruction-text detection | FR-312 | BR-070 |
| F-053 Plan proposer + selection | FR-406–408 | BR-052, BR-056 |
| F-054 Rule-based fallback | FR-409 | BR-055 |
| F-057 Exception drafter | FR-414 | BR-043 |
| F-090 Copilot | FR-801, FR-802 | BR-002, BR-057 |
| F-091 Prompt-injection defense | FR-803, FR-804 | BR-070 |
| F-092 Evals (extraction, benchmark, red-team, Copilot) | FR-805 | |
| F-093 AI decision log | FR-806, FR-807 | BR-097 |
| F-094 Provider adapter | FR-808 | NFR-REL-05 |

## 3. Concepts

| Term | Definition |
|---|---|
| **Task** | One AI purpose with its own prompt version, schema, model, timeout and budget: EXTRACT, TERMS, ANOMALY, PLAN, EXCEPTION_DRAFT, COPILOT, EVAL. |
| **Untrusted block** | External text wrapped as `<untrusted source="invoice:…">…</untrusted>` with a length cap; the system prompt states that content inside is data. |
| **Tool** | Read-only function with typed I/O, org-scoped, running in a read-only DB transaction. |
| **Proposal** | `PlanProposal` — ordering and deferrals by **request id**, no amounts. Turned into a concrete plan by the engine. |
| **Numeric post-check** | Every number in AI prose must appear in the tool/engine outputs given to it (± 0), else the text is discarded. |

## 4. Data model

| Table | Columns | Notes |
|---|---|---|
| `ai_calls` | id, org_id, purpose, model, prompt_version, input_refs jsonb, tool_calls jsonb, output jsonb, validation_result enum(OK, SCHEMA_ERROR, POSTCHECK_FAILED, REJECTED), latency_ms, input_tokens, output_tokens, cost_usd_micros, error | append-only; write failure ⇒ result discarded (fail closed) |
| `extractions` | id, document_id, ai_call_id, fields jsonb (value, page, span, confidence_note), terms jsonb, suspicious_instructions jsonb, confirmed_by/at | |
| `copilot_threads` / `copilot_messages` | id, org_id, user_id / thread_id, role, content, citations jsonb, ai_call_id | |
| `ai_budgets` | org_id, month, tokens_used, cost_usd_micros, limit_usd_micros | per-org monthly cap |

## 5. State

Stateless per call; extraction status on the request (`Extracting → Extracted | ManualEntry`); Copilot threads are append-only.

## 6. Interfaces

### 6.1 Schemas (strict JSON, validated with Pydantic, extra fields forbidden)

```python
InvoiceExtraction { vendor_name, invoice_no, issue_date, due_date, amount_text, currency, payee_address_as_found,
                    fields[*]: {value, page, span}, invoice_count_in_document, suspicious_instructions[{quote, page}] }
TermsExtraction   { discount_bps?, discount_days?, net_days?, late_fee?{kind, amount_text?, rate_bps?, period_days?, cap_text?},
                    priority_note?, uncertain: bool, uncertain_reason? }
PlanProposal      { request_order[request_id], deferrals[{request_id, until_day, reason_code}],
                    exception_requests[request_id], rationale[{claim, evidence_ids[]}] }
ExceptionDraft    { summary, reasons[{text, evidence_ids[]}], alternatives[] }
CopilotAnswer     { answer, citations[{tool_call_id, path}] }
```

### 6.2 Tools (allowlist)

| Tool | Input → Output |
|---|---|
| `get_snapshot(treasury_id)` | balances, buffers, today's budgets, payee statuses (no keys, no PII) |
| `list_requests(treasury_id, status?)` | ids, vendor display name, amount, due, terms (confirmed), flags codes |
| `get_policy_summary(treasury_id)` | mandate limits and rules in words + numbers |
| `simulate_schedule(treasury_id, order?, deferrals?)` | engine schedule + objective + binding constraints (M07) |
| `get_evidence(id)` | snapshot/validation/plan excerpt by id |
| `explain_decision(validation_id)` | reason codes and checks (M08) |

Budget per task: PLAN ≤ 8 tool calls, COPILOT ≤ 6; payload ≤ 50 KB per tool result.

### 6.3 Internal API

`extract(document_id)`, `propose_plan(treasury_id, request_ids)`, `draft_exception(request_id)`, `copilot.ask(thread_id, text)` (API_SPEC §7, SSE streaming).

## 7. Flows

- **Extraction:** upload → ai queue → model reads PDF/image → schema validate → deterministic checks (dates, currency, address compare) → `extractions` + draft prefill + AI flags → Operator confirms (M05). Timeout 60 s → ManualEntry, nothing guessed.
- **Planning:** M10 asks for a full proposal only when it can matter (≥ 2 eligible requests, or terms/deferrals in play). For a single plain request the deterministic plan is used and the AI writes only a short **explanation** (task EXPLAIN, cheap model) shown in the Why panel (M09-D6). Full proposal path → tool loop → `PlanProposal` → reference integrity → engine builds concrete plan → `score` vs deterministic → choose better (tie → deterministic) → M08 validates. Out-of-mandate proposal → AI_PLAN_REJECTED review + circuit breaker (BR-056/065).
- **Exception draft:** engine numbers injected → draft → numeric post-check → attach; failure → template text.
- **Copilot:** question → tool loop → answer + citations → numeric post-check → stream; requests to execute are refused with a pointer to the approval flow.

## 8. Algorithms

### 8.1 Injection defense (layers)

1. `wrap_untrusted` (tags, source, 20 k-char cap, strip scripts/links).
2. Fixed system prompt section; lint test forbids interpolating untrusted text outside the wrapper.
3. Output schemas (no free-form actions); tools read-only; no amounts accepted.
4. `suspicious_instructions` → HIGH flag; deterministic keyword fallback (`pay to`, `instead`, `pre-approved`, `ignore previous`, `urgent change of bank`, 0x-address not in registry).
5. Red-team suite: 20 cases, 0 field/policy changes (AGT-015).

**Implementation (AGT-003).** Code in `agent/untrusted.py`, `agent/secret_scan.py` and `agent/prompts/`.

- `wrap_untrusted(source, text)` returns an `UntrustedBlock`. `source` is an `UntrustedSource(kind, ref)`: `kind` is one of `invoice`, `document`, `vendor`, `terms`, `email`, and `ref` must match `[A-Za-z0-9_.:-]{1,64}`, so the label cannot add attributes. The text is sanitised in this order: invisible characters (Unicode `Cc` except `\n`/`\t`, and `Cf`: zero-width, bidi, tag characters) are removed; `<script>`/`<style>` blocks and HTML comments are removed (an opener with no closer is removed alone, so the rest of the text is kept); Markdown images are removed and Markdown links keep their text; URLs (`http(s)`, `ftp`, `www.`, `javascript:`, `vbscript:`, `data:` URIs) become `[link removed]`; other HTML tags (a name, then only `name=value` attributes, so `a<b and c>d` stays text) are removed with their text kept. Any `<untrusted…>`/`</untrusted>` tag in the text becomes `[tag removed]`, checked again after the other steps because removals can join fragments into a tag. `0x…` addresses, emails and plain text are kept, with no Unicode normalisation, so quotes stay exact. Raw text is first cut to 4× the cap, and every pattern runs in linear time, so crafted input cannot stall a worker. The 20,000-character cap applies after sanitising; a block cut at either step renders with `truncated="true"`. The block is then secret-scanned.
- **Secret scanner (FR-804).** Inputs are rejected, never redacted, with `AiInputRejected(pattern, source)`, an `AiError` that never carries the matched value. Patterns: runs of 64+ hex digits (EVM private keys, signatures, long calldata; an invoice that quotes a tx hash is therefore rejected to manual entry), BIP39 seed phrases (numbered or comma-separated too) where the first or last 12, 15, 18, 21 or 24 words of a run of wordlist words carry a valid checksum, BIP32 extended private keys, keystore JSON, PEM/OpenSSH/PGP private keys; Anthropic/OpenAI `sk-` keys, AWS access key ids, GCP service-account JSON, Google API keys, GitHub, GitLab, Slack (tokens and webhooks), Stripe, SendGrid, npm, PyPI and Telegram bot tokens, JWTs; credentials in URLs, RPC URLs with keys (Alchemy, Infura, QuickNode), `Authorization: Bearer|Basic` headers, and assignments: a name containing secret/password/passwd/private/credential/mnemonic/seed/api_key/access_key with any 8+ character value, or a name containing only key/token with a generated-looking value (16+ characters, letters and digits, not a `0x` address). The values of this process's environment variables whose names contain KEY, SECRET, TOKEN or PASSWORD but not PUBLIC (16+ characters) are also matched verbatim. The adapter scans its system prompt, messages, tool calls and tool results with `allow_bytes32`, which accepts a `0x` + 64-hex value (request, step and plan ids, fingerprints, tx hashes); untrusted blocks are scanned without it in `wrap_untrusted`. Tool descriptions and output schemas are code and are not scanned. Entropy checks, 32-hex strings, WIF keys, IBANs and card numbers are not flagged: they produce false positives on invoices, and IBANs are legitimate invoice content.
- **Templates.** `PromptTemplate(version, system, instructions, slots)` takes keyword arguments; `system` and `instructions` are string literals. The rendered system prompt is the fixed `UNTRUSTED_DATA_POLICY` (versioned by `POLICY_VERSION`) followed by the template's `system`, with nothing interpolated. The user message lists the slots in order, then the fixed instructions (data first, instructions last). `Slot.untrusted` takes only an `UntrustedBlock`. `Slot.trusted` takes bool, int, Decimal, date, a StrEnum or a Pydantic model, rendered as `<data name="…">…</data>`, and refuses a plain `str`. A model is rendered as JSON with `<` and `>` escaped as `\u003c`/`\u003e`, so a string field cannot close the element; it should still not carry vendor-supplied text. `render(**values)` returns a `RenderedPrompt`, with `prompt_version` set to `<version>+policy.<POLICY_VERSION>` for the AI call log. A wrong template or a missing, extra or wrongly typed slot value raises `PromptTemplateError`, a `ValueError` and not an `AiError`, so a bug is not hidden by a fallback.
- **Lint test** (`tests/agent/test_prompt_lint.py`) over the whole worker package. `RenderedPrompt` is built only in `prompts/template.py`, `UntrustedBlock` only in `untrusted.py`, and `Message`/`TextBlock` only in `prompts/` and the adapter. `PromptTemplate` takes literal keyword arguments. Template modules build no strings (f-strings, `%`, `+`, `.format`, `.join`, `string.Template`). `dataclasses.replace` and `object.__setattr__` are banned. Import aliases and attribute access count as the original name.
- Out of scope, for later tickets: Copilot questions (AGT-012: user instructions, not wrapped, but secret-scanned by the adapter).

**Implementation (AGT-004, invoice extraction).** Task `treasurypilot.invoices.extract_document(request_id, document_id)` on the `ai` queue (`tasks.py`), body in `invoices/extraction.py`, prompt `agent/prompts/extract.py` (`extract.v2`), migration `20261015_0041`.

- The upload (INV-004) creates the request with `extraction_status = Extracting`. The worker reads the stored file from private storage (read-only `S3_*` settings on `worker-ai`) and sends it as one `DocumentBlock` (PDF as a `document` block, PNG/JPEG as an `image` block, base64) through a `Slot.document` of the template. The whole file is untrusted under the same policy. File bytes are not secret-scanned (the scanner reads text only).
- `InvoiceExtraction` has `vendor_name`, `invoice_no`, `issue_date`, `due_date`, `amount_text`, `currency` and `payee_address_as_found`, each `null` or `{value, page, span}`, plus `invoice_count_in_document` and `suspicious_instructions[{quote, page}]` (AGT-006, stored in `extractions.fields`, no separate column). Terms (AGT-005) are not part of it yet.
- Success: one `extractions` row (`document_id` unique, `ai_call_id`, the validated answer in `fields`) and `extraction_status = Extracted`, in one transaction. The draft is prefilled with `invoice_no`, `issue_date`, `due_at` and `amount`, each only if it is still empty and passes a deterministic check: its page exists in the document; dates are ISO and `due >= issue`; `amount` is parsed by `BaseUnits.parse` only when `currency` equals the treasury asset's symbol (no conversion, no thousands separators). Several invoices in the file prefill nothing. Vendor and payee are never set; `payee_address_as_found` is stored for the M05 comparison and never applied, and the payee registry is never written.
- Any `AiError` (timeout, budget, unavailable, schema, rejected input) sets `ManualEntry` and writes nothing else: no guessed values. The `ai_calls` row is written by the adapter either way. An `AiCallLogError` is not caught (fail closed), so the request stays `Extracting` until the task is retried. Storage or database outages raise `RetryableTaskError`.
- Redeliveries are harmless: only a request that is still `Extracting` and unconfirmed is processed.
- Not done here: exposing `extraction_status` through the API and UI, a retry for `ManualEntry`, and least-privilege grants for the `worker-ai` database role (it needs UPDATE on `payment_requests` and INSERT on `extractions`).

**Implementation (AGT-006, keyword fallback).** Code in `agent/instruction_detector.py`.

- `detect_instructions(pages, known_addresses=…)` takes document pages (numbered from 1) and the payee registry's addresses, and returns `InstructionScan(matches, detector="keyword_fallback", reduced_coverage=True)`. It is used when the LLM is down, so every scan notes reduced coverage. Each page goes through `sanitize()` first, so zero-width or bidi characters cannot split a keyword.
- Matching is English only, case-insensitive, with any whitespace between words and word boundaries. **Strong** signals are flagged on their own: `keyword.ignore_previous` (`ignore previous`, `ignore all previous`) and `keyword.urgent_change_of_bank`. **Weak** signals are flagged only when at least two different kinds are found together: `keyword.pay_to`, `keyword.instead`, `keyword.pre_approved` (`pre-approved`, `pre approved`, `preapproved`) and `address.unknown`. "Together" means each signal starts at most `INSTRUCTION_MATCH_WINDOW` (150) characters after the previous one ends, on the same page. Each weak signal alone is ordinary invoice text ("Pay to: Acme Ltd").
- `address.unknown` is a `0x` + 40-hex address not in `known_addresses` (case ignored). On its own it is not flagged here; a payee differing from the registry is the deterministic M05 rule.
- Each group of signals is one `InstructionMatch(rules, quote, page, start, end)`, with `quote == sanitised_page[start:end]`. The quote is the full lines holding the signals, or just the signal span, cut to 300 characters, when those lines are longer. `INSTRUCTION_REASON_CODE` (`INSTRUCTION_TEXT`) and `INSTRUCTION_SEVERITY` (`HIGH`) are for the flag writer.
- **Flag (in `invoices/extraction.py`).** A non-empty `suspicious_instructions` (first 10, quotes cut to 300 characters) creates one `INSTRUCTION_TEXT` HIGH flag with `source = AI` on the request's current revision, in the same transaction as the `extractions` row. Evidence: `{detector: "llm", reducedCoverage: false, matches: [{quote, page}]}`. When the LLM fails (`AiError`, request goes to manual entry), the keyword fallback scans the PDF text layer (`pypdf`; the registry addresses of the treasury's payees are `known_addresses`) and a match creates the same flag with `source = DETERMINISTIC` and evidence `{detector: "keyword_fallback", reducedCoverage: true, matches: [{quote, page, rules}]}`. Images and scanned PDFs have no text layer and are not scanned (needs OCR). Detection never changes a field, payee or state; the flag only adds to the HIGH flags an approver must acknowledge.
- Revision bumps (confirm, edit, terms confirm, renew) never supersede `INSTRUCTION_TEXT`: it is re-created as a fresh Open flag on the new revision, so an acknowledged one needs acknowledging again. `worker-ai` also needs INSERT on `flags` and SELECT on `payees` (grants are still open, see AGT-004). The window and keyword list are tuned with the red-team suite (AGT-015).

### 8.2 Selection (AGT-009)

`score_ai = score(plan_from(proposal))`, `score_det = score(deterministic_plan)` (lexicographic, M07). Choose AI only if valid and `score_ai < score_det`; equal → deterministic (cheaper to explain). Record `planner_source` and `chosen_reason` ("AI captured 2 % discount on INV-7 by deferring INV-9 one day, value +20").

### 8.3 Numeric post-check

Extract all numbers from text (`\d[\d,._]*`), normalize, check each against the set of numbers in tool outputs/engine inputs (exact, same units). Any miss → discard text → template.

### 8.4 Fallback (BR-055)

Template plan used only when: AI unavailable/timeout **and** snapshot complete **and** template matches (pay direct / refill-then-pay / swap-then-pay P2) **and** no Unknown **and** no safety alert. Recorded RULE_BASED.

**Implementation (AGT-010).** Code in `agent/fallback.py`. `plan_fallback(ctx, error)` takes the validator's `ValidationContext` and the `AiError` that ended the AI path, and returns a `FallbackPlan(template, plan)` with `planner_source="RULE_BASED"`, or `FallbackRefused(reason)`, which the caller sends to NeedsReview. Order of checks: the error must be an outage (`AiTimeout`, `AiUnavailable`, `AiBudgetExceeded`, `AiSchemaError`, `AiToolLimitExceeded`; an `AiInputRejected` or a `PlanProposalRejected` is not) → `NOT_AN_OUTAGE`; `unknown_operations > 0` → `UNKNOWN_OPERATION` (AD-03); `pause_requested`, `circuit_open`, `screening_hit` or any HIGH flag → `SAFETY_ALERT`; coverage other than `COMPLETE`, or a missing request, approval, mandate, policy state, screening result or paying-wallet balance/buffer/target → `DATA_INCOMPLETE`. Templates, tried in order, each accepted only if `validate_plan` returns ALLOW: `PAY_DIRECT` (the wallet already holds amount + buffer); `REFILL_THEN_PAY` (BR-032: top up to the target bounded by BR-036, else just the shortage). The PAY amount is the early amount inside the early window. No template passing → `NO_TEMPLATE`. Swap-then-pay is not built: it is P2 and the validator has no SWAP rule or module code yet. Wiring into the plan pipeline waits for the planner (AGT-008/009).

**Implementation (AGT-008, plan proposer and EXPLAIN).** Code in `agent/plan_proposer.py` and `agent/prompts/plan.py` (`plan.v1`, `explain.v1`). API: `propose_plan(adapter, org_id, treasury_id, eligible_request_ids, tools)` runs the PLAN task and returns `AiResult[PlanProposal]`; `explain_plan(adapter, org_id, facts)` runs EXPLAIN on the cheap model and returns the text or `None`; `needs_full_proposal(eligible_requests, terms_or_deferrals_matter)` is the M09-D6 trigger (2 or more eligible requests, or terms/deferrals matter); `check_references(proposal, eligible_request_ids, known_evidence_ids)` raises `PlanProposalRejected`. The schema is strict (`extra="forbid"`), so an `amount` field is a schema error (one retry, then `AiSchemaError`). `check_references` rejects: ids outside the eligible list, an id repeated within or across `request_order` / `deferrals` / `exception_requests`, and evidence ids the run did not read. Evidence is org-scoped by construction: an id is citable only if a successful `get_evidence` call (org-bound tool) took it as input or a successful `get_snapshot` returned it as `snapshot_id`; the caller supplies no callback. Rationale `claim` has min length 1. Whether the proposal covers every eligible request is not checked here; that is AGT-009. Evidence ids are per rationale item (spec section 5), not a top-level `evidenceIds` list as the issue text says. `PlanProposalRejected` is not an outage: `plan_fallback` returns `NOT_AN_OUTAGE` and the request goes to review with `AI_PLAN_REJECTED` (M09-D12). EXPLAIN is checked strictly: every number in the text (commas removed) must appear in a `PlanFact`, i.e. its `amount` (a display string such as `3,000`, as the reviewer sees it, not base units) or its `pay_day` (ISO date parts); request ids never count. Otherwise `explain_plan` returns `None` and the caller uses the template text. The planner is not wired yet: nothing calls these functions until AGT-009.


## 9. Configuration and defaults (`config/ai.yaml`)

| Task | Model | Timeout | Max tokens out |
|---|---|---|---|
| EXTRACT, TERMS, ANOMALY | `claude-sonnet-5-5` | 60 s | 2,000 |
| PLAN | `claude-opus-5-5` | 20 s | 1,500 |
| EXCEPTION_DRAFT | `claude-sonnet-5-5` | 20 s | 800 |
| EXPLAIN (single request, plan already fixed) | `claude-haiku-5-5` | 10 s | 300 |
| COPILOT | `claude-sonnet-5-5` | 30 s | 1,200 |
| EVAL | `claude-sonnet-5-5` | 60 s | 2,000 |

Per-org monthly AI budget 20 USD in M1 (over budget → AI tasks degrade to fallbacks, notice shown). Secondary provider (AGT-017): Claude on Amazon Bedrock through the same `AnthropicProvider` (Bedrock Mantle client, `anthropic.` model prefix), wrapped with the primary in a `FailoverProvider`; order and prefixes live in `config/ai.yaml` `providers`. A provider-side failure (5xx, 429, connection error, 401/403, or a timeout of the primary, which gets half the remaining deadline) moves the same turn to the next provider within the task deadline, and the failed provider is skipped for 30 s; request errors (400, an unusable billed response) are not resent, and billed tokens are still charged. Bedrock is skipped when `AWS_BEARER_TOKEN_BEDROCK` is unset; a missing `ANTHROPIC_API_KEY` fails startup, and the config rejects duplicate providers and a Bedrock entry without `model_prefix`. A same-family secondary keeps structured outputs, strict tools and prompt caching identical, so no second prompt or schema path is needed. Zero-retention API setting where available; it is configured at the organization level in the Anthropic Console, not in code.

The file also holds tool-call limits (PLAN 8, COPILOT 6), the tool-result cap (50 KB) and per-model prices in USD micros per million tokens, with a long-prompt tier for Haiku. Its path is `config/ai.yaml` relative to the working directory (`/app` in the worker image), overridable with `TP_AI_CONFIG_PATH`; a task or a model price missing from the file fails startup.

**Adapter (AGT-001).** `AiAdapter.run(task, org_id, prompt, output, tools)` is the only way to call a model. `prompt` is a `RenderedPrompt` from a `PromptTemplate` (§8.1), and its version is returned as `AiResult.prompt_version`. Before each provider call the adapter secret-scans the system prompt and every message not yet scanned, including tool calls and tool results, and raises `AiInputRejected` on a match. It picks the model from config, enforces the timeout as a wall-clock deadline for the whole call (tool turns, provider retries and the schema retry included), retries retryable provider errors up to twice inside that deadline, runs the read-only tool loop, and validates the output against the Pydantic schema, retrying once with the validation error (M09-D9). It raises `AiTimeout`, `AiUnavailable`, `AiSchemaError`, `AiBudgetExceeded`, `AiToolLimitExceeded` or `AiInputRejected`; callers map them to fallbacks. Budget is checked before the call (blocked once spend ≥ limit, so one call may overshoot) and every provider response is recorded through a `BudgetLedger`. The ledger is in memory until the `ai_budgets` table exists.

**Tools (AGT-007).** Code in `agent/tools/`. `build_tools(backend, org_id, simulation=, decisions=, only=)` returns the allowlisted `Tool`s for `AiAdapter.run(tools=...)`: `get_snapshot` (latest COMPLETE snapshot; Safe owners and modules left out), `list_requests`, `get_policy_summary` (active mandate limits, buffers, refill paths; payees as label and short address), `simulate_schedule` (defer ids or move the day; runs `schedule_edf` and `binding_constraints`, stores nothing), `get_evidence` (snapshot or validation excerpt by id) and `explain_decision` (validator codes, checks and the rule of each). Inputs and outputs are strict Pydantic models; amounts are base-unit strings. The organisation is bound when the tools are built and is never a model input: a treasury, snapshot or validation of another organisation is refused with `ToolError` (`REFUSED: ... not found in this organisation`, the same words as for a missing id, so nothing leaks), and the adapter returns a `ToolError` to the model as an error result. Vendor names, invoice numbers, payee labels and the terms' `priority_note` are wrapped with `wrap_untrusted` inside tool results. The registry offers only the six names; `only=` with any other name raises `UnknownToolError`, and a model call to an unknown name gets an error result. `simulate_schedule` and `explain_decision` are offered only when the planner passes their source (`SimulationSource`, `DecisionSource`), because plans, validations and the chain-snapshot to engine mapping are not persisted yet (M08/M10). Tools read through the `ToolBackend` protocol, which has no write method; `PostgresToolBackend` opens every read in a `READ ONLY` transaction (one connection per call), and `tests/test_agent_tools_integration.py` enumerates the tools and asserts `transaction_read_only = on` for each, and that a write through the backend is rejected. Call and payload budgets are the adapter's (PLAN 8, COPILOT 6, 50 KB per result).

**Decision log (AGT-002).** Code in `agent/call_log.py`; table `ai_calls` (migration `20261013_0006`). Every `AiAdapter.run` that gets past argument checks writes exactly one row through an `AiCallLog`, on success and on every `AiError`: purpose, model, prompt version, `input_refs` (the sources of the prompt's untrusted blocks, e.g. `invoice:INV-7`, never their text), tool calls (200-character previews of the JSON input and of the result, their lengths and flags), the validated output, `validation_result` (`OK`, `SCHEMA_ERROR`, or NULL for every other failure, including non-`AiError` exceptions, which carry a 200-character `error` preview instead), latency, tokens (billed tokens of a failed call included) and cost. The row id (UUIDv7, `treasurypilot_core.ids.uuid7`) is returned as `AiResult.ai_call_id`. The connection and the insert each time out after 5 s. If the write fails the adapter raises `AiCallLogError`, which is not an `AiError`, so the result is discarded and the task fails instead of falling back. A trigger rejects UPDATE, DELETE and TRUNCATE on `ai_calls`, and the org foreign key is RESTRICT. `worker-ai` refuses to build an adapter without `DATABASE_URL`. `POSTCHECK_FAILED` and `REJECTED` are reserved for the numeric post-check (AGT-011/012) and plan rejection (AGT-009).

## 10. Security

| Threat | Control | Test |
|---|---|---|
| Prompt injection changes payee/amount | data-only wrapping, schemas, no write tools, extracted address only compared | AGT-015 (20 cases), AD-01 |
| Secret leakage | worker-ai has only the LLM key; secret scanner on every model input, which is rejected on a match (§8.1) | AGT-003 |
| Cross-tenant data | tools org-scoped; Copilot threads per user/org | AGT-007 |
| Hallucinated numbers | post-check; amounts from engine | AGT-011, AGT-016 |
| AI outage | fallbacks; secondary provider | AD-02, AGT-017 |
| Unlogged decisions | ai_calls write failure discards the result | AGT-002 |

## 11. Failure scenarios

LLM timeout → manual entry / deterministic plan / template text; schema error → retry once with the error message, then fallback; budget exhausted → fallbacks + notice; provider outage → secondary provider (P1) else fallbacks.

## 12. Test plan

Contract tests on schemas; injection lint; tool read-only test; recorded-response tests for each task; evals: extraction accuracy (30 invoices), planner benchmark B1 vs B2 (dev + held-out), red-team (20), Copilot fidelity (20).

## 13. Tickets

AGT-001 adapter → AGT-002 log → AGT-003 untrusted wrapping → AGT-004 extraction → AGT-005 terms → AGT-006 instruction detection → AGT-007 tools → AGT-008 proposer → AGT-009 selection → AGT-010 fallback → AGT-011 exception drafts → AGT-012 Copilot → evals AGT-013/014/015/016 → AGT-017 secondary provider.

## 14. Decisions

| ID | Decision |
|---|---|
| M09-D1 | No agent framework; Anthropic SDK with structured outputs and tool use (ADR-005). |
| M09-D2 | Model per task in config (§9): PLAN on Opus, extraction/terms/Copilot/drafts on Sonnet, EXPLAIN on Haiku. (reviewed) |
| M09-D3 | All AI runs in `worker-ai` with only the LLM key. |
| M09-D4 | Proposals contain ids and orderings only; amounts always from the engine. |
| M09-D5 | AI plan chosen only if strictly better; ties → deterministic. (reviewed) |
| M09-D6 | Full AI proposal only when ≥ 2 eligible requests or terms/deferrals matter; otherwise an AI explanation of the deterministic plan (EXPLAIN task). (reviewed) |
| M09-D7 | Numeric post-check on every prose output. |
| M09-D8 | Extraction timeout 60 s → ManualEntry; never guess. |
| M09-D9 | Schema error: one retry with the validation error, then fallback. (reviewed) |
| M09-D10 | Per-org monthly AI budget 20 USD in M1, configurable. (reviewed) |
| M09-D11 | Tool-call budgets: PLAN 8, COPILOT 6. |
| M09-D12 | Out-of-mandate proposal → AI_PLAN_REJECTED + circuit breaker PAUSE. |
| M09-D13 | Multi-invoice documents reported via `invoice_count_in_document` → M05 rejects. |
| M09-D14 | Ground truth of eval scenarios never enters prompts. |

## 15. v0.3 changes (ADR-019)

EXPLAIN covers liquidity actions ("Supplied 3,000 because Safe holds 6,000 and the reserve needs 3,000"). A new explanation for borrow proposals (numbers only from M07). AI never proposes SUPPLY/BORROW amounts. Benchmark (AGT-014) adds **B0** (manual/EDF, cash idle) before B1 and B2, measuring on-time rate, reserve breaches, mandate violations, net benefit (incl. supply interest), processing time and interventions.
