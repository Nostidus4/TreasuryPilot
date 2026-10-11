"""Assign open M1 tickets by area (project lead's split, 2026-10-11) and set Project Owner + Status = Assigned.
frontend, backend -> Nostidus4 · infrastructure, ai -> therealtunguyen · contracts -> longhuynh55 · non-code -> unassigned.
Usage: python3 planning/tools/assign.py [--dry]"""
import json, subprocess, sys, pathlib, time
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import gen_issues as G
from data import TICKETS

OWNER, NUM, REPO = "Nostidus4", 1, "Nostidus4/TreasuryPilot"
BY_AREA = {"frontend": "Nostidus4", "backend": "Nostidus4", "infrastructure": "therealtunguyen", "ai": "therealtunguyen", "contracts": "longhuynh55"}
ROOT = pathlib.Path(__file__).resolve().parents[2]
gm = json.loads((ROOT / "planning/tools/github_map.json").read_text())["issues"]

def gql(q, **v):
    args = ["gh", "api", "graphql", "-f", f"query={q}"] + sum([["-F", f"{k}={val}"] for k, val in v.items()], [])
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode: raise RuntimeError(r.stderr)
    return json.loads(r.stdout)["data"]

def main():
    dry = "--dry" in sys.argv
    meta = gql('query($o:String!,$n:Int!){user(login:$o){projectV2(number:$n){id fields(first:40){nodes{...on ProjectV2Field{id name} ...on ProjectV2SingleSelectField{id name options{id name}}}}}}}', o=OWNER, n=NUM)["user"]["projectV2"]
    pid = meta["id"]; fields = {f["name"]: f for f in meta["fields"]["nodes"] if f}
    owner_f, status_f = fields["Owner"]["id"], fields["Status"]
    opt = {o["name"]: o["id"] for o in status_f["options"]}
    items, after = {}, None
    while True:
        q = 'query($o:String!,$n:Int!,$a:String){user(login:$o){projectV2(number:$n){items(first:100,after:$a){pageInfo{hasNextPage endCursor} nodes{id content{...on Issue{number state assignees(first:5){nodes{login}}}} fieldValueByName(name:"Status"){...on ProjectV2ItemFieldSingleSelectValue{name}} owner: fieldValueByName(name:"Owner"){...on ProjectV2ItemFieldTextValue{text}}}}}}}'
        d = gql(q, o=OWNER, n=NUM, **({"a": after} if after else {}))["user"]["projectV2"]["items"]
        for it in d["nodes"]:
            c = it.get("content") or {}
            if c.get("number"): items[c["number"]] = it
        if not d["pageInfo"]["hasNextPage"]: break
        after = d["pageInfo"]["endCursor"]
    n = 0
    for t in TICKETS:
        if t["phase"] != "M1": continue
        who = BY_AREA.get(G.area(t))
        num = gm.get(t["id"], {}).get("number")
        it = items.get(num)
        if not who or not it: continue
        c = it["content"]
        if c["state"] == "CLOSED": continue
        cur = [a["login"] for a in c["assignees"]["nodes"]]
        if cur != [who]:
            if not dry: subprocess.run(["gh", "api", "-X", "PATCH", f"repos/{REPO}/issues/{num}", "-f", f"assignees[]={who}"], capture_output=True, text=True, check=True)
        if ((it.get("owner") or {}).get("text")) != who and not dry:
            gql('mutation($p:ID!,$i:ID!,$f:ID!,$t:String!){updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,value:{text:$t}}){projectV2Item{id}}}', p=pid, i=it["id"], f=owner_f, t=who)
        st = (it.get("fieldValueByName") or {}).get("name")
        if st in ("Ready for Assignment", None) and not dry:
            gql('mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,value:{singleSelectOptionId:$o}}){projectV2Item{id}}}', p=pid, i=it["id"], f=status_f["id"], o=opt["Assigned"])
        n += 1
        if not dry: time.sleep(0.6)
    print("assigned", n)

if __name__ == "__main__": main()
