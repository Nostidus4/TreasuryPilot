"""Rebuild the 20 epic issue bodies from the module specs and ticket data. Usage: python3 planning/tools/epic_bodies.py [--apply]"""
import json, re, subprocess, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from data import TICKETS, MODULES
from data.cut import tier

ROOT = pathlib.Path(__file__).resolve().parents[2]
REPO = "Nostidus4/TreasuryPilot"
gm = json.loads((ROOT / "planning/tools/github_map.json").read_text())

def section(md, n):
    m = re.search(rf"^## {n}\. .*?$(.*?)(?=^## \d+\.|\Z)", md, re.S | re.M)
    return m.group(1).strip() if m else ""

def first_table(text):
    lines, out, started = text.splitlines(), [], False
    for l in lines:
        if l.startswith("|"): out.append(l); started = True
        elif started: break
    return "\n".join(out)

def body(prefix):
    folder, _, mnum, name = MODULES[prefix]
    md = (ROOT / f"docs/modules/{folder}/README.md").read_text()
    s1 = section(md, 1)
    purpose = s1.split("\n\n")[0]
    scope = first_table(s1)
    decisions = first_table(section(md, 14))
    order = section(md, 13)
    ts = [t for t in TICKETS if t["id"].startswith(prefix + "-")]
    m1 = [t for t in ts if t["phase"] == "M1"]; later = [t for t in ts if t["phase"] != "M1"]
    def row(t):
        num = gm["issues"].get(t["id"], {}).get("number")
        link = f"#{num}" if num else "—"
        return f"| {link} | {t['id']} | {t['title']} | {t['prio']} | {t['size']} | {tier(t['id']) if t['phase']=='M1' else 'Later'} |"
    spec = f"https://github.com/{REPO}/blob/main/docs/modules/{folder}/README.md"
    out = [f"# {mnum} · {name}", "",
           f"**Full spec (14 sections):** {spec}", "",
           "## Purpose", purpose, ""]
    if scope: out += ["## Scope", scope, ""]
    out += ["## Tickets (M1)", "| Issue | ID | Title | Prio | Size | Cut |", "|---|---|---|---|---|---|", *[row(t) for t in m1], ""]
    if later: out += ["## Tickets (Later)", "| Issue | ID | Title | Prio | Size | Cut |", "|---|---|---|---|---|---|", *[row(t) for t in later], ""]
    if order: out += ["## Order of work", order, ""]
    if decisions: out += ["## Key decisions", decisions, ""]
    out += ["Child tickets are attached as sub-issues. Decisions marked *(mặc định)* are proposals accepted by default and open for review."]
    return "\n".join(out)

if __name__ == "__main__":
    apply = "--apply" in sys.argv
    for prefix, e in gm["epics"].items():
        b = body(prefix)
        if apply:
            subprocess.run(["gh", "issue", "edit", str(e["number"]), "--repo", REPO, "--body-file", "-"], input=b, text=True, check=True, capture_output=True)
            print("epic", prefix, "#", e["number"], len(b))
        else:
            print(b[:1500] if prefix == "EXE" else "", end="")
