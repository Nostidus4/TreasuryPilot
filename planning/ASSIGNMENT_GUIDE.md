# Assignment Guide

**Status:** Ready for assignment (2026-10-11). Specs for all 20 modules are final (`docs/modules/*/README.md`). This guide **suggests** work tracks; the project lead assigns people in the GitHub Project **Owner** field. Nobody is assigned automatically.

Already done (PR #254): DEV-001, DEV-002, DEV-003, DEV-005, DEV-011, SC-001, WEB-001.

## 1. Suggested tracks

| Track | Modules (ticket prefixes) | Open M1 tickets / dev-days | of which Tier A |
|---|---|---|---|
| **A · Chain & execution core** (developer 1) | M04 contracts incl. Aave supply/withdraw (SC), M06 chain reader (CHR), M07 engine (ENG), M08 policy (POL), M10 execution (EXE), M11 verification (REC), M12 recovery (RCV) | 78 / 61 | 61 / 49 |
| **B · Product, API, UI & AI** (developer 2) | M01 identity (IDN), M02 treasury (TRS), M03 mandate (MDT), M05 invoices (INV), M09 AI (AGT), M13 notifications (NTF), M14 compliance (CMP), M15 audit (AUD), M16 web (WEB), M17 observability (OBS), M19 devex (DEV) | 104 / 85.5 | 63 / 52.5 |
| **C · Domain & evidence** (3 advisors + anh Phúc) | M20 (DOM) — split per docs/modules/domain-evidence §2 | 17 / 14 | 11 / 10 |

Why this split: track A is the money path that must be correct first (contract → validator → signer → executor) and is mostly Python/Solidity with few UI concerns; track B owns everything a user touches. They meet at clear contracts already written in the specs: the ABI and EIP-712 vectors (SC-017), the snapshot and decision models (CHR-002, POL-001), and the OpenAPI client (DEV-005). Track B is larger; if track A finishes early, it takes AGT (AI) tickets first.

## 2. Ready to start now (all blockers done)

### Track A
| Issue | ID | Ticket | Prio | Size | Cut |
|---|---|---|---|---|---|
| #42 | ENG-001 | Create py-core money types and domain models | P0 | M | A |
| #131 | EXE-002 | Set up Celery with core and ai queues | P0 | M | A |
| #28 | SC-002 | Define module storage, structs, EIP-712 domain, errors and events | P0 | M | A |

### Track B
| Issue | ID | Ticket | Prio | Size | Cut |
|---|---|---|---|---|---|
| #32 | IDN-001 | Create identity database schema and migrations | P0 | S | A |
| #192 | CMP-003 | Implement data classification, encryption helpers and log redaction | P0 | M | B |
| #25 | DEV-004 | Add CI workflow for contracts | P1 | S | B |

### Track C
| Issue | ID | Ticket | Prio | Size | Cut |
|---|---|---|---|---|---|
| #70 | DOM-001 | Verify Ethereum Sepolia infrastructure (owner: Phúc) | P0 | S | A |
| #177 | DOM-005 | Author planner scenarios with ground truth (≥30) | P0 | L | A |
| #179 | DOM-006 | Author the red-team invoice set (20) | P0 | M | A |
| #232 | DOM-008 | Review business rules and demo limits from a finance view | P0 | S | A |
| #233 | DOM-009 | Review the threat model and write the known-risk list | P0 | M | A |
| #231 | DOM-003 | Ask the organizers whether testnet evidence is accepted | P1 | S | A |
| #175 | DOM-004 | Author the labelled invoice dataset (30) | P0 | M | B |
| #234 | DOM-010 | Run customer interviews (2–3) | P1 | M | B |
| #239 | DOM-015 | Write the compliance positioning note and license inventory | P1 | S | B |
| #241 | DOM-017 | Choose the repository license | P1 | S | After submission |
| #240 | DOM-016 | Update the FigJam board from the repo diagrams | P2 | S | After submission |

Then follow each module's §13 order and `planning/DEPENDENCIES.md` waves. Priority inside a track: Tier A before B, P0 before P1.

## 3. How to assign and work

1. In the GitHub Project, set **Owner** (name) and **Status = Assigned** on the tickets for each person; move to **In Progress** when work starts.
2. Branch `feat/<ticket-id>-short-name`; PR description contains `Closes #<issue>`; the PR template's checklist must be complete.
3. Merging the PR closes the issue; the dashboard counts closed issues as Done automatically (run `python3 planning/tools/sync_closed_status.py` to fix the Project Status field, or enable the Project workflow "Item closed → Done").
4. Specs are the source of truth: if implementation needs a different decision, update the module README §14 and `docs/decisions-log.md` in the same PR.
5. Daily: Google Sheet dashboard (auto-refresh hourly) shows progress per module and per person.

**v0.3 update (ADR-019):** new Tier A tickets SC-023 (two-option approvals), SC-024 (Aave supply/withdraw), SC-025 (Sepolia fork tests), ENG-013 (reserve formulas), EXE-014 (liquidity cycle), DEV-012 (config gate), WEB-026 (position card); Tier B ENG-014 and WEB-027 (borrow proposal); P2 SC-026 and MDT-011 (borrow/repay execution).

## 4. Actual assignment (project lead, 2026-10-11)

| Area | Owner | Modules / tickets | Default reviewer |
|---|---|---|---|
| Frontend | **@Nostidus4** | WEB | @therealtunguyen |
| Backend | **@Nostidus4** | IDN, TRS, MDT, INV, CHR, ENG, POL, EXE, REC, RCV, NTF, CMP, AUD | @therealtunguyen |
| Infrastructure | **@therealtunguyen** | DEV, OBS | @Nostidus4 (default, can change) |
| AI | **@therealtunguyen** | AGT | @Nostidus4 (default, can change) |
| Blockchain | **@longhuynh55** (anh Phúc) | SC | @Nostidus4 (default, can change) |
| Non-code | to be split later | DOM | – |

Applied on GitHub: issue assignees, Project **Owner** field and Status **Assigned** (182 open M1 code tickets). Default reviewers live in `.github/CODEOWNERS`. Re-run `python3 planning/tools/assign.py` after adding tickets. The suggested tracks in §1 are superseded by this table.

