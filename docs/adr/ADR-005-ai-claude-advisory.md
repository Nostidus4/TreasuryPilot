# ADR-005: Claude via SDK; AI is advisory, never authoritative
**Status:** Accepted (G2, 2026-10-11) · **Decision:** Q27 · **Rules:** BR-002, BR-034, BR-055–058, BR-070

## Decision
- Use the Anthropic Python SDK directly, with tool use and structured outputs (JSON schema).
- A thin orchestrator in `services/worker/agent` handles: tool loop (max N calls), timeout, schema validation, logging (F-093), routing.
- Model routing is configured per task:
  - extraction, terms, anomaly text: a small, fast model;
  - planning rationale, exception drafts, Copilot: a stronger model.

  Model ids live in config only.
- Tools are read-only (snapshot, requests, policy summary, schedule simulation, evidence by id).
- Every AI output passes deterministic validation. Authority comes only from the validator, the human signatures and the contract.
- Rule-based fallback applies under BR-055.

## Alternatives
- LangChain/LangGraph: hides the trust boundary and adds dependencies.
- No AI: loses the Innovation criterion.
- Fine-tuned models: no data, no time.

## Consequences
- We maintain prompt versions, schemas and an eval harness (F-092) in the repo.
- Data minimization applies (F-113). No secrets go into prompts (BR-092).
