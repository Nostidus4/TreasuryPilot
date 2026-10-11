"""Set Project Status = Done for every closed issue (and back to Ready for Assignment if reopened while Done).
Usage: python3 planning/tools/sync_closed_status.py"""
import json, subprocess

OWNER, NUM = "Nostidus4", 1

def gql(q, **v):
    args = ["gh", "api", "graphql", "-f", f"query={q}"] + sum([["-F", f"{k}={val}"] for k, val in v.items()], [])
    return json.loads(subprocess.run(args, capture_output=True, text=True, check=True).stdout)["data"]

def main():
    meta = gql('query($o:String!,$n:Int!){user(login:$o){projectV2(number:$n){id field(name:"Status"){...on ProjectV2SingleSelectField{id options{id name}}}}}}', o=OWNER, n=NUM)["user"]["projectV2"]
    pid, fid = meta["id"], meta["field"]["id"]
    opt = {o["name"]: o["id"] for o in meta["field"]["options"]}
    after, changed = None, 0
    while True:
        q = 'query($o:String!,$n:Int!,$a:String){user(login:$o){projectV2(number:$n){items(first:100,after:$a){pageInfo{hasNextPage endCursor} nodes{id content{...on Issue{number state}} fieldValueByName(name:"Status"){...on ProjectV2ItemFieldSingleSelectValue{name}}}}}}}'
        d = gql(q, o=OWNER, n=NUM, **({"a": after} if after else {}))["user"]["projectV2"]["items"]
        for it in d["nodes"]:
            c = it.get("content") or {}
            st = (it.get("fieldValueByName") or {}).get("name")
            if c.get("state") == "CLOSED" and st != "Done":
                target = "Done"
            else:
                continue
            gql('mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,value:{singleSelectOptionId:$o}}){projectV2Item{id}}}',
                p=pid, i=it["id"], f=fid, o=opt[target])
            print(f"#{c['number']}: {st} -> {target}"); changed += 1
        if not d["pageInfo"]["hasNextPage"]: break
        after = d["pageInfo"]["endCursor"]
    print("changed", changed)

if __name__ == "__main__": main()
