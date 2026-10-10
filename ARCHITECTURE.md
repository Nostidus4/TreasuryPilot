# Architecture (entry point)

The full document is [`docs/SYSTEM_ARCHITECTURE.md`](docs/SYSTEM_ARCHITECTURE.md). This page is the two-minute version.

## Six principles

1. **The contract is the final authority over money.**
2. **AI proposes; deterministic code decides; humans authorize.**
3. **Keys live in exactly one place.** Owner keys stay in users' wallets. The executor key is in `signer`. The attestation key is in `worker` (core). LLM calls run in `worker-ai`, which has no signing secrets.
4. **Write before you act; never guess outcomes.** Postgres outbox; Unknown ≠ failed.
5. **Modular monolith off-chain.**
6. **Evidence by construction.**

## Shape

```text
Browser (React + wagmi) ──HTTPS──> api (FastAPI) ──> PostgreSQL (truth, outbox, audit)
        │ wallet signatures                │ enqueue
        ▼                                  ▼
   Safe T (Owner governance)        Redis ─> worker (core)  ──> signer ──> TreasuryPilotModule ──> Safes T/O1/O2
                                         └─> worker-ai ──> Claude API
```

## Where to look

| Topic | Document |
|---|---|
| Containers, trust boundaries, flows | `docs/SYSTEM_ARCHITECTURE.md` |
| Why each technology | `docs/TECH_STACK.md`, `docs/adr/` |
| AI boundaries | `docs/AI_AGENT_ARCHITECTURE.md` |
| Modules | `docs/modules/` |
| Data, API | `docs/DATA_MODEL.md`, `docs/API_SPEC.md` |
| Rules enforced on-chain | `docs/BUSINESS_RULES.md` (column "Enforced" = C) |
