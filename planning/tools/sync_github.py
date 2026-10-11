#!/usr/bin/env python3
"""Create labels, milestones, epic issues, ticket issues, sub-issue links, blocked-by
dependencies and the GitHub Project from planning/tools/data.

Idempotent: planning/tools/github_map.json remembers what already exists.
Usage (repo root):  python3 planning/tools/sync_github.py [step ...]
Steps: labels milestones epics issues subissues deps project   (default: all)
"""
import json, os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from data import TICKETS, MODULES
from data.cut import tier
import gen_issues as G

OWNER, REPO = "Nostidus4", "TreasuryPilot"
FULL = f"{OWNER}/{REPO}"
BLOB = f"https://github.com/{FULL}/blob/main/"
MAP_PATH = os.path.join(os.path.dirname(__file__), "github_map.json")
BY_ID = {t["id"]: t for t in TICKETS}

def load_map():
    return json.load(open(MAP_PATH)) if os.path.exists(MAP_PATH) else {"issues": {}, "epics": {}, "labels": [], "milestones": {}, "project": {}}
def save_map(m): json.dump(m, open(MAP_PATH, "w"), indent=1, sort_keys=True)

def gh(args, inp=None, ok_fail=False):
    for attempt in range(6):
        p = subprocess.run(["gh"] + args, input=inp, capture_output=True, text=True)
        if p.returncode == 0:
            return p.stdout
        err = p.stderr
        if "rate limit" in err.lower() or "secondary" in err.lower() or "502" in err or "503" in err:
            time.sleep(60 * (attempt + 1)); continue
        if ok_fail: return None
        raise SystemExit(f"gh {' '.join(args[:4])} failed: {err.strip()}")
    raise SystemExit("gave up after retries")

def api(method, path, body=None, ok_fail=False):
    args = ["api", "-X", method, path, "-H", "Accept: application/vnd.github+json"]
    out = gh(args + (["--input", "-"] if body is not None else []), json.dumps(body) if body is not None else None, ok_fail)
    return json.loads(out) if out else None

def gql(query, **variables):
    body = {"query": query, "variables": variables}
    out = gh(["api", "graphql", "--input", "-"], json.dumps(body))
    data = json.loads(out)
    if data.get("errors"): raise SystemExit(json.dumps(data["errors"])[:800])
    return data["data"]

# ── labels ───────────────────────────────────────────────────────────
AREA_COLOR = {"contracts": "5319e7", "backend": "1d76db", "frontend": "0e8a16", "ai": "d93f0b",
              "infrastructure": "c5def5", "non-code": "fbca04"}
def wanted_labels():
    L = {}
    for p, (slug, tag, mid, name) in MODULES.items(): L[f"module:{slug}"] = ("bfdadc", f"{mid} {name}")
    for a, c in AREA_COLOR.items(): L[f"area:{a}"] = (c, f"Area: {a}")
    for pr, c in (("P0", "b60205"), ("P1", "d93f0b"), ("P2", "fbca04")): L[f"priority:{pr}"] = (c, f"M1 priority {pr}")
    for ph in ("M1", "Later"): L[f"phase:{ph}"] = ("ededed", f"Phase {ph}")
    for s in ("S", "M", "L"): L[f"size:{s}"] = ("f9d0c4", {"S": "≤ 0.5 day", "M": "~1 day", "L": "1.5–2 days"}[s])
    for c in ("A", "B", "after-submission"): L[f"cut:{c}"] = ("0052cc" if c == "A" else "5ebeff" if c == "B" else "d4c5f9", f"Submission cut {c}")
    L["type:epic"] = ("3e4b9e", "Epic (parent issue)"); L["type:task"] = ("ededed", "Implementation ticket"); L["non-code"] = ("fbca04", "Non-code work")
    L["security"] = ("b60205", "Security-relevant")
    return L

def step_labels(m):
    existing = {l["name"] for l in json.loads(gh(["api", f"repos/{FULL}/labels?per_page=100"]))}
    for name, (color, desc) in wanted_labels().items():
        if name not in existing:
            api("POST", f"repos/{FULL}/labels", {"name": name, "color": color, "description": desc[:100]})
    print("labels ok")

# ── milestones ───────────────────────────────────────────────────────
def step_milestones(m):
    existing = {x["title"]: x["number"] for x in json.loads(gh(["api", f"repos/{FULL}/milestones?state=all&per_page=100"]))}
    for title, due, desc in (("M1 · FinTechathon submission", "2026-10-20T15:59:00Z", "Competition build. Deadline 2026-10-20 23:59 Beijing time."),
                             ("Later · Full product", None, "Post-submission roadmap.")):
        if title not in existing:
            body = {"title": title, "description": desc}
            if due: body["due_on"] = due
            existing[title] = api("POST", f"repos/{FULL}/milestones", body)["number"]
    m["milestones"] = existing; save_map(m); print("milestones ok", existing)

# ── helpers ──────────────────────────────────────────────────────────
def labels_for(t):
    p = G.prefix(t); slug = MODULES[p][0]
    L = [f"module:{slug}", f"area:{G.area(t)}", f"phase:{t['phase']}", f"size:{t['size']}"]
    L.append("non-code" if p == "DOM" else "type:task")
    if t["prio"] in ("P0", "P1", "P2"): L.append(f"priority:{t['prio']}")
    if t["phase"] == "M1":
        tr = tier(t["id"]); L.append("cut:" + ("A" if tr == "A" else "B" if tr == "B" else "after-submission"))
    if p in ("SC",) or "security" in t["title"].lower() or "SEC" in t["refs"] or "bypass" in t["title"].lower() or p == "CMP":
        L.append("security")
    return L

def body_for(t, m):
    md = G.render(t)
    md = md.split("\n", 2)[2]  # drop H1 (it becomes the title)
    md = md.replace("](../../../", "](" + BLOB)
    def dep(mo):
        i = mo.group(1); n = m["issues"].get(i, {}).get("number")
        return f"- {i}{f' (#{n})' if n else ''}:"
    md = re.sub(r"^- ([A-Z]{2,3}-L?\d+):", dep, md, flags=re.M)
    src = f"planning/issues/{MODULES[G.prefix(t)][0]}/"
    md += f"\n---\n_Generated from `{src}` by `planning/tools/sync_github.py`. Edit the source data, not this issue body, for structural changes._\n"
    return md

def topo_order():
    seen, order = set(), []
    def visit(i):
        if i in seen: return
        seen.add(i)
        for d in BY_ID[i]["deps"]: visit(d)
        order.append(i)
    for t in TICKETS: visit(t["id"])
    return order

# ── epics ────────────────────────────────────────────────────────────
def step_epics(m):
    for p, (slug, tag, mid, name) in MODULES.items():
        if p in m["epics"]: continue
        ts = [t for t in TICKETS if G.prefix(t) == p]
        body = (f"Epic for module **{mid} · {name}**.\n\n- Spec: {BLOB}docs/modules/{slug}/README.md\n"
                f"- Ticket drafts: {BLOB}planning/issues/{slug}/\n- Tickets: {sum(t['phase']=='M1' for t in ts)} (M1) + "
                f"{sum(t['phase']!='M1' for t in ts)} (Later)\n\nChild tickets are attached as sub-issues.")
        r = api("POST", f"repos/{FULL}/issues", {"title": f"[EPIC] {mid} · {name}", "body": body,
                                                  "labels": ["type:epic", f"module:{slug}"]})
        m["epics"][p] = {"number": r["number"], "id": r["id"], "node_id": r["node_id"]}; save_map(m); time.sleep(1)
    print("epics ok", len(m["epics"]))

# ── issues ───────────────────────────────────────────────────────────
def step_issues(m):
    ms = m["milestones"]
    created = 0
    for i in topo_order():
        if i in m["issues"]: continue
        t = BY_ID[i]
        milestone = ms["M1 · FinTechathon submission"] if t["phase"] == "M1" else ms["Later · Full product"]
        r = api("POST", f"repos/{FULL}/issues", {"title": G.title(t), "body": body_for(t, m),
                                                  "labels": labels_for(t), "milestone": milestone})
        m["issues"][i] = {"number": r["number"], "id": r["id"], "node_id": r["node_id"]}; save_map(m)
        created += 1
        time.sleep(4)
        if created % 25 == 0: print("created", created, flush=True)
    print("issues ok", len(m["issues"]))

# ── sub-issues ───────────────────────────────────────────────────────
def step_subissues(m):
    m.setdefault("subissues_done", [])
    for t in TICKETS:
        i = t["id"]
        if i in m["subissues_done"]: continue
        epic = m["epics"][G.prefix(t)]["number"]
        r = api("POST", f"repos/{FULL}/issues/{epic}/sub_issues", {"sub_issue_id": m["issues"][i]["id"]}, ok_fail=True)
        if r is None:
            print("sub-issue API unavailable or failed for", i); break
        m["subissues_done"].append(i); save_map(m); time.sleep(0.4)
    print("subissues", len(m["subissues_done"]))

# ── blocked-by dependencies ──────────────────────────────────────────
def step_deps(m):
    m.setdefault("deps_done", [])
    for t in TICKETS:
        for d in t["deps"]:
            key = f"{t['id']}<-{d}"
            if key in m["deps_done"]: continue
            r = api("POST", f"repos/{FULL}/issues/{m['issues'][t['id']]['number']}/dependencies/blocked_by",
                    {"issue_id": m["issues"][d]["id"]}, ok_fail=True)
            if r is None:
                print("dependency API unavailable or failed for", key, "- relying on issue-body references"); return
            m["deps_done"].append(key); save_map(m); time.sleep(0.4)
    print("deps", len(m["deps_done"]))

# ── project ──────────────────────────────────────────────────────────
STATUSES = ["Draft", "Needs Discussion", "Ready for Review", "Accepted", "Ready for Assignment", "Assigned", "In Progress", "Review", "Done"]
SELECT_FIELDS = {
    "Module": [MODULES[p][0] for p in MODULES],
    "Priority": ["P0", "P1", "P2", "—"],
    "Phase": ["M1", "Later"],
    "Size": ["S", "M", "L"],
    "Cut": ["A", "B", "After submission", "Later"],
    "Area": list(AREA_COLOR),
}
def step_project(m):
    pj = m["project"]
    owner_id = gql("query{viewer{id}}")["viewer"]["id"]
    if "id" not in pj:
        r = gql("mutation($o:ID!,$t:String!){createProjectV2(input:{ownerId:$o,title:$t}){projectV2{id number url}}}",
                o=owner_id, t="TreasuryPilot · Delivery")["createProjectV2"]["projectV2"]
        pj.update(r); save_map(m)
        gql("mutation($p:ID!,$r:ID!){linkProjectV2ToRepository(input:{projectId:$p,repositoryId:$r}){repository{id}}}",
            p=pj["id"], r="R_kgDOVDSK4w")
    fields = gql("query($p:ID!){node(id:$p){...on ProjectV2{fields(first:50){nodes{...on ProjectV2FieldCommon{id name dataType}"
                 " ...on ProjectV2SingleSelectField{options{id name}}}}}}}", p=pj["id"])["node"]["fields"]["nodes"]
    byname = {f["name"]: f for f in fields}
    # Status field: replace default options with the 9-step workflow
    st = byname["Status"]
    if [o["name"] for o in st.get("options", [])] != STATUSES:
        gql("mutation($f:ID!,$o:[ProjectV2SingleSelectFieldOptionInput!]){updateProjectV2Field(input:{fieldId:$f,singleSelectOptions:$o}){projectV2Field{...on ProjectV2SingleSelectField{id}}}}",
            f=st["id"], o=[{"name": s, "color": "GRAY", "description": ""} for s in STATUSES])
    for name, opts in SELECT_FIELDS.items():
        if name not in byname:
            gql("mutation($p:ID!,$n:String!,$o:[ProjectV2SingleSelectFieldOptionInput!]){createProjectV2Field(input:{projectId:$p,dataType:SINGLE_SELECT,name:$n,singleSelectOptions:$o}){projectV2Field{...on ProjectV2SingleSelectField{id}}}}",
                p=pj["id"], n=name, o=[{"name": x, "color": "GRAY", "description": ""} for x in opts])
    for name in ("Ticket ID", "Blocked by"):
        if name not in byname:
            gql("mutation($p:ID!,$n:String!){createProjectV2Field(input:{projectId:$p,dataType:TEXT,name:$n}){projectV2Field{...on ProjectV2Field{id}}}}", p=pj["id"], n=name)
    fields = gql("query($p:ID!){node(id:$p){...on ProjectV2{fields(first:50){nodes{...on ProjectV2FieldCommon{id name}"
                 " ...on ProjectV2SingleSelectField{options{id name}}}}}}}", p=pj["id"])["node"]["fields"]["nodes"]
    F = {f["name"]: f for f in fields}
    opt = lambda field, val: next(o["id"] for o in F[field]["options"] if o["name"] == val)
    pj.setdefault("items", {})
    todo = [(p, None) for p in MODULES if f"EPIC:{p}" not in pj["items"]] + [(None, t) for t in TICKETS if t["id"] not in pj["items"]]
    for k in range(0, len(todo), 10):
        chunk = todo[k:k + 10]
        parts = []
        for j, (p, t) in enumerate(chunk):
            node = m["epics"][p]["node_id"] if p else m["issues"][t["id"]]["node_id"]
            parts.append(f'a{j}:addProjectV2ItemById(input:{{projectId:"{pj["id"]}",contentId:"{node}"}}){{item{{id}}}}')
        res = gql("mutation{" + " ".join(parts) + "}")
        sets = []
        for j, (p, t) in enumerate(chunk):
            item = res[f"a{j}"]["item"]["id"]
            if p:
                vals = {"Module": MODULES[p][0], "Status": "Accepted"}
                texts = {"Ticket ID": f"EPIC-{p}"}
                pj["items"][f"EPIC:{p}"] = item
            else:
                tr = tier(t["id"]) if t["phase"] == "M1" else "Later"
                vals = {"Status": "Ready for Assignment" if t["phase"] == "M1" else "Accepted",
                        "Module": MODULES[G.prefix(t)][0], "Priority": t["prio"] if t["prio"] != "-" else "—",
                        "Phase": t["phase"], "Size": t["size"], "Cut": tr, "Area": G.area(t)}
                texts = {"Ticket ID": t["id"], "Blocked by": ", ".join(t["deps"])}
                pj["items"][t["id"]] = item
            for fname, v in vals.items():
                sets.append(f'u{len(sets)}:updateProjectV2ItemFieldValue(input:{{projectId:"{pj["id"]}",itemId:"{item}",fieldId:"{F[fname]["id"]}",value:{{singleSelectOptionId:"{opt(fname, v)}"}}}}){{clientMutationId}}')
            for fname, v in texts.items():
                if v:
                    sets.append(f'u{len(sets)}:updateProjectV2ItemFieldValue(input:{{projectId:"{pj["id"]}",itemId:"{item}",fieldId:"{F[fname]["id"]}",value:{{text:{json.dumps(v)}}}}}){{clientMutationId}}')
        for s in range(0, len(sets), 25):
            gql("mutation{" + " ".join(sets[s:s + 25]) + "}")
        save_map(m); time.sleep(0.5)
        print("project items", len(pj["items"]), flush=True)
    print("project ok", pj.get("url"))

STEPS = {"labels": step_labels, "milestones": step_milestones, "epics": step_epics, "issues": step_issues,
         "subissues": step_subissues, "deps": step_deps, "project": step_project}
if __name__ == "__main__":
    m = load_map()
    for s in (sys.argv[1:] or list(STEPS)):
        STEPS[s](m)
