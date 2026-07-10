"""Print dead evidence URLs and flagged apps from the latest verification pass."""
import json

v = json.load(open("verification.json", encoding="utf-8"))
last = v[sorted(k for k in v if k.startswith("pass"))[-1]]
print("DEAD URLS:")
for u in last["dead_evidence_urls"]:
    print(" -", u[:100])
print("\nFLAGGED APPS:")
for d in last["details"]:
    if d["flagged_fields"]:
        why = {f: d["verdicts"][f]["why"][:48] for f in d["flagged_fields"]}
        print(f"{d['id']:3d} {d['name'][:22]:22s} {why}")
