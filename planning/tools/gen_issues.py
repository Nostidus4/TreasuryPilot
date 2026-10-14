#!/usr/bin/env python3
"""Generate ticket drafts, the backlog and the dependency map from planning/tools/data.
Usage: python3 planning/tools/gen_issues.py   (run from the repo root)"""
import os, re, sys, shutil
from collections import defaultdict, Counter
sys.path.insert(0, os.path.dirname(__file__))
from data import TICKETS, MODULES
from data.cut import tier, TIER_A, TIER_B

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "planning", "issues")
BY_ID = {t["id"]: t for t in TICKETS}
SIZE = {"S": "S (≤ 0.5 day)", "M": "M (~1 day)", "L": "L (1.5–2 days; split if it grows)"}

def feature_titles():
    txt = open(os.path.join(ROOT, "docs", "FEATURES.md")).read()
    return dict(re.findall(r"^\| (F-\d+) \| (.+?) \|", txt, re.M))
FT = feature_titles()

def feature_problems():
    txt = open(os.path.join(ROOT, "docs", "FEATURES.md")).read()
    out = {}
    for m in re.finditer(r"^#### (F-\d+) .*?\n(.*?)(?=^#### |\Z)", txt, re.M | re.S):
        pm = re.search(r"\*\*Problem solved:\*\* (.+)", m.group(2))
        if pm: out[m.group(1)] = pm.group(1).strip()
    return out
FP = feature_problems()

def expand_feats(s):
    out = []
    for a, b in re.findall(r"F-(\d+)\s*[–-]\s*F-(\d+)", s):
        out += [f"F-{i:03d}" for i in range(int(a), int(b) + 1)]
    out += re.findall(r"F-\d+", s)
    seen = []
    for f in out:
        if f in FT and f not in seen:
            seen.append(f)
    return seen

def prefix(t): return t["id"].split("-")[0]
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]
def status(t): return "Ready for Assignment" if t["phase"] == "M1" else "Accepted"  # G3 accepted 2026-10-11
def area(t):
    p = prefix(t)
    return {"SC": "contracts", "WEB": "frontend", "AGT": "ai", "DEV": "infrastructure", "DOM": "non-code",
            "OBS": "infrastructure"}.get(p, "backend")
def title(t): return f"[{MODULES[prefix(t)][1]}] {t['title']}"

def render(t):
    slugdir, tag, mid, mname = MODULES[prefix(t)]
    feats = expand_feats(t["feats"])
    feat_lines = "\n".join(f"- {f}: {FT[f]}" for f in feats) or "- (supporting work; no single feature)"
    deps = "\n".join(f"- {d}: {BY_ID[d]['title']}" for d in t["deps"]) or "- None"
    blocks = [x["id"] for x in TICKETS if t["id"] in x["deps"]]
    blocks_s = ", ".join(blocks) if blocks else "—"
    noncode = prefix(t) == "DOM"
    if noncode:
        dod = "- [ ] Deliverable committed to the repository at the stated path\n- [ ] Reviewed by one other team member\n- [ ] Linked from the relevant document or issue"
        testing = "- Not applicable (non-code). Review by a second person is required."
    else:
        dod = "- [ ] Code completed and merged through a reviewed PR\n- [ ] Tests listed above pass in CI\n- [ ] Docs / ADR updated if behaviour or design changed\n- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone"
        testing = "\n".join(f"- {x}" for x in t["tests"]) or "- Unit tests for the new logic"
    probs = [f"- **{f}** solves: {FP[f]}" for f in feats[:3] if f in FP]
    why = ("Problem behind this work (from `docs/FEATURES.md`):\n\n" + "\n".join(probs)) if probs else \
          "This is enabling work: other tickets cannot start, or evidence cannot be produced, without it."
    if t["phase"] != "M1" and t.get("split_plan"):
        later_note = ("\n> **Phase: Later.** Re-estimated as L (2 days) and split before scheduling:\n>\n"
                      + "\n".join(f"> - {part}" for part in t["split_plan"]) + "\n")
    elif t["phase"] != "M1":
        later_note = ("\n> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. "
                      "It must be re-estimated and split before it is scheduled.\n")
    else:
        later_note = ""
    return f"""# {title(t)}

| Field | Value |
|---|---|
| **ID** | {t['id']} |
| **Epic** | {mid} · {mname} |
| **Module** | `{slugdir}` ([spec](../../../docs/modules/{slugdir}/README.md)) |
| **Phase / Priority** | {t['phase']} / {t['prio']} |
| **Size** | {SIZE.get(t['size'], t['size'])} |
| **Area** | {area(t)} |
| **Status** | {status(t)} |
| **Traces to** | {t['refs'] or '—'} |
| **Blocks** | {blocks_s} |
| **Submission cut** | {tier(t['id'])} |
{later_note}
## Context

This ticket belongs to the epic **{mname}**. It supports:

{feat_lines}

{why}

## Objective

{t['objective']}

## Scope

{chr(10).join('- ' + s for s in t['scope'])}

## Out of scope

{t['oos'] or 'Nothing specific beyond the scope above.'}

## Technical notes

{t['notes'] or 'Follow the module spec and the relevant ADRs.'}

## Dependencies

{deps}

## Acceptance criteria

{chr(10).join('- [ ] ' + a for a in t['ac'])}

## Testing requirements

{testing}

## Definition of Done

{dod}
"""

def write_issues():
    if os.path.isdir(OUT): shutil.rmtree(OUT)
    for t in TICKETS:
        d = os.path.join(OUT, MODULES[prefix(t)][0]); os.makedirs(d, exist_ok=True)
        num = t["id"].split("-", 1)[1]
        open(os.path.join(d, f"{num.lower()}-{slug(t['title'])}.md"), "w").write(render(t))

def waves():
    m1 = [t for t in TICKETS if t["phase"] == "M1"]
    done, order = set(), []
    while len(done) < len(m1):
        w = [t for t in m1 if t["id"] not in done and all(d in done or BY_ID[d]["phase"] != "M1" for d in t["deps"])]
        if not w: raise SystemExit("dependency cycle among: " + ", ".join(t["id"] for t in m1 if t["id"] not in done))
        order.append(w); done |= {t["id"] for t in w}
    return order

def write_backlog():
    L = ["# Master Backlog", "",
         "Generated from `planning/tools/data` by `planning/tools/gen_issues.py`. Do not edit by hand.", "",
         "**Status legend:** Draft → Needs Discussion → Ready for Review → Accepted → Ready for Assignment → Assigned → In Progress → Review → Done.",
         "Gate G3 accepted by the project lead on 2026-10-11: M1 tickets are **Ready for Assignment**, Later tickets are **Accepted** (not scheduled). Nobody is assigned yet.", ""]
    c = Counter((t["phase"], t["prio"]) for t in TICKETS)
    L += ["## Totals", "", "| Phase | P0 | P1 | P2 | Total |", "|---|---:|---:|---:|---:|",
          f"| M1 | {c[('M1','P0')]} | {c[('M1','P1')]} | {c[('M1','P2')]} | {sum(v for k,v in c.items() if k[0]=='M1')} |",
          f"| Later | – | – | – | {sum(v for k,v in c.items() if k[0]=='Later')} |",
          f"| **All** | | | | **{len(TICKETS)}** |", "", "## Epics", "",
          "| Epic | Module | Tickets (M1) | Tickets (Later) | Folder |", "|---|---|---:|---:|---|"]
    for p, (sd, tag, mid, name) in MODULES.items():
        ts = [t for t in TICKETS if prefix(t) == p]
        L.append(f"| {mid} · {name} | `{sd}` | {sum(t['phase']=='M1' for t in ts)} | {sum(t['phase']!='M1' for t in ts)} | [`issues/{sd}/`](issues/{sd}/) |")
    L += ["", "## All tickets", "", "| ID | Module | Epic | Issue | Features | Phase | Prio | Size | Cut | Dependency | Status |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in TICKETS:
        sd, tag, mid, name = MODULES[prefix(t)]
        num = t["id"].split("-", 1)[1].lower()
        link = f"issues/{sd}/{num}-{slug(t['title'])}.md"
        L.append(f"| {t['id']} | {sd} | {mid} | [{t['title']}]({link}) | {t['feats']} | {t['phase']} | {t['prio']} | {t['size']} | {tier(t['id'])} | {', '.join(t['deps']) or '—'} | {status(t)} |")
    open(os.path.join(ROOT, "planning", "BACKLOG.md"), "w").write("\n".join(L) + "\n")

def write_deps():
    W = waves()
    edges = Counter()
    for t in TICKETS:
        if t["phase"] != "M1": continue
        for d in t["deps"]:
            a, b = prefix(BY_ID[d]), prefix(t)
            if a != b: edges[(a, b)] += 1
    L = ["# Dependency Map", "", "Generated by `planning/tools/gen_issues.py`.", "",
         "## 1. Module-level blocking dependencies (M1)", "",
         "An arrow A → B means at least one ticket in B is blocked by a ticket in A. The number is how many such links exist.", "",
         "```mermaid", "flowchart LR"]
    for p, (sd, tag, mid, name) in MODULES.items():
        if any(prefix(t) == p and t["phase"] == "M1" for t in TICKETS): L.append(f'  {p}["{mid} {sd}"]')
    for (a, b), n in sorted(edges.items()): L.append(f"  {a} -->|{n}| {b}")
    L += ["```", "", "## 2. Dependency types", "",
          "| Type | Meaning | Examples |", "|---|---|---|",
          "| **Blocking** | B cannot start until A is merged (listed in each ticket's *Dependencies*). | SC-005 → SC-006; ENG-010 → INV-010; POL-006 → EXE-005 |",
          "| **Soft** | B can start against a stub or recorded data and integrate later. | WEB-* pages against the OpenAPI schema before endpoints are finished; AGT-004 with recorded model responses; AGT-013/014 scaffolding before DOM datasets are complete |",
          "| **Parallel** | No dependency in either direction. | Contracts (SC) ‖ py-core engine (ENG) ‖ identity (IDN) ‖ web shell (WEB-001) ‖ all DOM tickets |", "",
          "## 3. Execution waves (M1)", "",
          "Tickets in the same wave have no blocking dependency on each other, so they **can run in parallel**. A ticket appears in the earliest wave in which all of its blockers are done.", ""]
    for i, w in enumerate(W, 1):
        L += [f"### Wave {i} ({len(w)} tickets)", "", "| ID | Title | Prio | Size | Blocked by |", "|---|---|---|---|---|"]
        for t in sorted(w, key=lambda x: (x["prio"], x["id"])):
            L.append(f"| {t['id']} | {t['title']} | {t['prio']} | {t['size']} | {', '.join(t['deps']) or '—'} |")
        L.append("")
    # critical path (longest chain by ticket count)
    memo = {}
    def depth(i):
        if i not in memo:
            ds = [d for d in BY_ID[i]["deps"] if BY_ID[d]["phase"] == "M1"]
            memo[i] = (1 + max((depth(d)[0] for d in ds), default=0), max(ds, key=lambda d: depth(d)[0]) if ds else None)
        return memo[i]
    end = max((t["id"] for t in TICKETS if t["phase"] == "M1"), key=lambda i: depth(i)[0])
    chain = []
    while end: chain.append(end); end = depth(end)[1]
    L += ["## 4. Longest blocking chain", "",
          "The longest chain of blocking dependencies. Anything on it that slips delays the end of M1.", "",
          " → ".join(reversed(chain)), ""]
    open(os.path.join(ROOT, "planning", "DEPENDENCIES.md"), "w").write("\n".join(L) + "\n")
    return W, chain

def write_cut():
    d = {"S": 0.5, "M": 1, "L": 2}
    def days(S, code=True): return sum(d[BY_ID[i]["size"]] for i in S if (prefix(BY_ID[i]) != "DOM") == code)
    rest = {t["id"] for t in TICKETS if t["phase"] == "M1"} - TIER_A - TIER_B
    L = ["# Submission Cut (proposal for gate G3)", "",
         "Generated by `planning/tools/gen_issues.py` from `planning/tools/data/cut.py`. **Nothing is removed from the plan.** The cut only says what is built before 20/10.", "",
         "| Tier | Meaning | Tickets | Code (est. days) | Non-code (est. days) |", "|---|---|---:|---:|---:|",
         f"| **A** | Required for one credible end-to-end demo on testnet. Dependency-closed: every blocker of an A ticket is also A. | {len(TIER_A)} | {days(TIER_A)} | {days(TIER_A, False)} |",
         f"| **B** | Stretch: raises the score, but the demo works without it. | {len(TIER_B)} | {days(TIER_B)} | {days(TIER_B, False)} |",
         f"| After submission | Remaining M1 tickets; still planned. | {len(rest)} | {days(rest)} | {days(rest, False)} |", "",
         "Estimates use the ticket sizes (S = 0.5, M = 1, L = 2 dev-days) at a conventional pace. They have **not** been re-estimated by the developers.", "",
         "## Capacity check", "",
         f"- Tier A code ≈ **{days(TIER_A)} dev-days**. Two developers between 11/10 and 19/10 have ≈ **18 dev-days**.",
         "- At conventional pace, Tier A does **not** fit. It fits only if the developers' real pace (for example with AI coding assistants) is about 5× the estimates, or the scope is simplified.",
         "- Tier A non-code work fits the three advisors.", "",
         "## Options for the team (decide at G3)", "",
         "1. **Re-estimate Tier A with the developers today** (30 minutes, planning poker on the A list). Use their numbers, not these.",
         "2. **Adopt a documented submission profile (ADR-019, not yet written)** that keeps the on-chain enforcement and the AI story, and simplifies the off-chain platform. Candidates are listed below.",
         "3. **Shrink the demo story**: drop the AI planner from Tier A (keep extraction + deterministic scheduler), saving about 4 dev-days (AGT-007, AGT-008, AGT-009, AGT-010, AGT-014). EXE-004 then uses the deterministic plan only.", "",
         "### Submission-profile candidates (ADR-019, not yet decided)", "",
         "| Simplification | Replaces | Approx. saving | Cost to the score |",
         "|---|---|---:|---|",
         "| Seeded demo org, users and treasury instead of setup UIs | WEB-004, parts of TRS-006/TRS-007 UI flow | 1–2 days | Low: judges see the result, not the setup |",
         "| Wallet-only login (SIWE) with seeded roles; no magic link | IDN-002 | 1 day | Low |",
         "| Run tasks in-process with APScheduler; no Celery/Redis | EXE-002 | 1 day | Low: reverses decision Q32 for the submission only |",
         "| Store invoice files on local disk instead of MinIO | part of INV-004, DEV-002 | 0.5 day | None |",
         "| Keep the signer as a separate process but drop simulation and allowlist extras | part of EXE-005 | 0.5–1 day | Medium: weakens the key-isolation story |",
         "| Skip the planner benchmark harness; report a small hand-run comparison | AGT-014 | 1 day | Medium: weaker answer to 'why AI?' |", "",
         "## Tier A tickets", "", "| ID | Title | Prio | Size |", "|---|---|---|---|"]
    for t in TICKETS:
        if t["id"] in TIER_A: L.append(f"| {t['id']} | {t['title']} | {t['prio']} | {t['size']} |")
    L += ["", "## Tier B tickets", "", "| ID | Title | Prio | Size |", "|---|---|---|---|"]
    for t in TICKETS:
        if t["id"] in TIER_B: L.append(f"| {t['id']} | {t['title']} | {t['prio']} | {t['size']} |")
    open(os.path.join(ROOT, "planning", "SUBMISSION_CUT.md"), "w").write("\n".join(L) + "\n")

if __name__ == "__main__":
    write_issues(); write_backlog(); write_cut(); W, chain = write_deps()
    covered = set()
    for t in TICKETS: covered |= set(expand_feats(t["feats"]))
    missing = sorted(set(FT) - covered)
    print(f"tickets={len(TICKETS)} waves={len(W)} chain={len(chain)} features_without_ticket={missing}")
