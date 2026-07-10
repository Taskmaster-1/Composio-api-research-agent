"""Quick distribution sanity check of results.json (dev helper)."""
import json
from collections import Counter

d = json.load(open("results.json", encoding="utf-8"))
ok = [r for r in d if "error" not in r]
print(f"{len(d)} records, {len(d) - len(ok)} errors")
print("access:", Counter((r.get("self_serve") or "?").lower() for r in ok))
print("buildable:", Counter((r.get("buildable") or "?").lower() for r in ok))
print("mcp:", Counter((r.get("mcp") or "?").lower() for r in ok))
print("confidence:", Counter((r.get("confidence") or "?").lower() for r in ok))
auth = Counter()
for r in ok:
    for a in r.get("auth_methods") or []:
        auth[a.lower()] += 1
print("auth raw:", auth.most_common(12))
no_ev = [r["name"] for r in ok if not any((r.get("evidence") or {}).values())]
print("records with zero evidence URLs:", no_ev)
