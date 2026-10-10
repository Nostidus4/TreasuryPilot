# M09 · AI Agent

**Status:** Draft for gate G2 · **Path:** `docs/modules/agent/`

## Purpose
Every LLM use: adapter/routing, invoice extraction, terms, anomaly text, plan proposal and rationale, exception drafts, Copilot, prompt-injection defenses, AI decision log, eval harness.

## Features
F-031 (AI part), F-035, F-036 (AI part), F-053, F-054, F-057, F-090, F-091, F-092, F-093, F-094

## Inputs
Untrusted documents and text, read-only tool results, engine outputs.

## Outputs
Schema-validated proposals, drafts and answers; ai_calls records; eval reports.

## APIs
Internal; Copilot via `/copilot/*` (API_SPEC §7).

## Data model
ai_calls, extractions, copilot_threads, copilot_messages

## Dependencies
M07, M08 (scoring/validation), M06 (snapshots), M15, Claude API.

## Security concerns
See AI_AGENT_ARCHITECTURE §4. No secrets in prompts; tool allowlist; output schemas; budgets.

## Failure scenarios
LLM timeout/outage → fallbacks per task; logging failure → fail closed.

## Open questions
Exact model ids (config) and the per-org token budget.
