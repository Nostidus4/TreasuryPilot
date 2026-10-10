# Contributing

## Workflow

1. Pick an issue in status **Ready for Assignment** that is assigned to you. Nobody self-assigns: the project lead assigns work.
2. Create a branch from `main`: `feat/<module>-<issue#>-<slug>`, `fix/…`, `docs/…`, `chore/…`, `test/…`.
3. Open a draft PR early. Link the issue (`Closes #123`).
4. Keep PRs small. One ticket = one PR whenever possible.
5. CI must be green and at least one review approved before merging (squash merge).

## Branch strategy

Trunk-based. `main` is always releasable and protected. There are no long-lived feature branches. Tags: `m1-rc<N>`, `m1-submission`.

## Commit convention

[Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<module>): <summary> (#issue)
```

- Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`, `perf`, `build`.
- Modules: `identity`, `treasury`, `mandate`, `contracts`, `invoices`, `chain-reader`, `engine`, `policy`, `agent`, `execution`, `reconciliation`, `recovery`, `notifications`, `compliance`, `audit`, `web`, `observability`, `admin`, `devex`.

Example: `feat(contracts): enforce payee cooling period in pay() (#42)`

## Issue status flow

`Draft → Needs Discussion → Ready for Review → Accepted → Ready for Assignment → Assigned → In Progress → Review → Done`

An issue becomes **Accepted** only after team review (gate G3).

## Definition of Done (every ticket)

- [ ] Acceptance criteria met
- [ ] Tests added and passing (unit; integration/contract/E2E as the ticket requires)
- [ ] No business-critical rule relies on an LLM or prompt alone
- [ ] Money handled as integers in base units
- [ ] Docs/ADR updated if behaviour or design changed
- [ ] Audit log and error codes wired for any money- or authority-affecting action
- [ ] Reviewed and merged with green CI

## Code style

| Area | Tools |
|---|---|
| Python | ruff (lint + format), mypy (strict on `py-core`), pytest |
| TypeScript | eslint, prettier, tsc `--noEmit` |
| Solidity | forge fmt, Slither, NatSpec on external functions |

## Security rules for contributors

- Never log secrets, raw signatures, session tokens or full invoice contents.
- Never add a tool to the AI agent that has side effects.
- Never add a generic `execute` path to the contract or the signer.
- Report vulnerabilities privately.
