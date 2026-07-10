"""Fix pass after deterministic verification pass 1.

Two kinds of fixes, both logged:
  1. data hygiene — evidence fields where the LLM emitted two URLs joined by a
     comma (unusable as a link) are cut to the first URL;
  2. claim corrections for records the checker caught with dubious claims,
     each grounded in a docs page a human actually looked at.
Checker limitations (JS-rendered or bot-blocked docs) are NOT "fixed" by
loosening the checker — they stay flagged and are covered by the human loop.
"""
import json

results = json.load(open("results.json", encoding="utf-8"))
by_id = {r["id"]: r for r in results}

# 1. split comma-joined evidence URLs
n_split = 0
for r in results:
    for k, u in list((r.get("evidence") or {}).items()):
        if u and "," in u:
            r["evidence"][k] = u.split(",")[0].strip()
            n_split += 1
print(f"split {n_split} comma-joined evidence URLs")

CORRECTIONS = {
    72: {  # Airtable — cited /tokens path 404s; support article is the real source
        "evidence.auth": "https://support.airtable.com/docs/creating-personal-access-tokens",
        "evidence.access": "https://support.airtable.com/docs/creating-personal-access-tokens",
    },
    84: {  # Paygent — cited "MCP" page never mentions MCP; claim was wrong
        "mcp": "none found",
        "mcp_note": "earlier 'official' claim cited a page that does not mention MCP",
        "evidence.mcp": "",
        "confidence": "low",
    },
    44: {  # Salesforce Commerce Cloud — auth was 'unknown'; it's OAuth2 via Account Manager/SLAS,
           # and access needs a B2C Commerce license (realm) — gated, not unknown
        "auth_methods": ["OAuth2"],
        "self_serve": "gated",
        "access_note": "Requires a B2C Commerce license (realm); API clients are issued via Account Manager, shopper APIs use SLAS OAuth2.",
        "buildable": "partial",
        "blocker": "Commerce Cloud license required — no self-serve path",
        "evidence.auth": "https://developer.salesforce.com/docs/commerce/commerce-api/guide/authorization-for-shopper-apis.html",
        "confidence": "medium",
    },
    17: {  # Plain — access was 'unknown' and surface is GraphQL, not REST
        "self_serve": "self-serve",
        "access_note": "API keys are created for Machine Users in workspace settings; free trial available.",
        "api_surface": "GraphQL",
        "buildable": "yes",
        "evidence.auth": "https://www.plain.com/docs/graphql/authentication",
        "evidence.api": "https://www.plain.com/docs/graphql/introduction",
        "evidence.access": "https://www.plain.com/docs/graphql/authentication",
    },
}

for app_id, changes in CORRECTIONS.items():
    r = by_id[app_id]
    for key, val in changes.items():
        if key.startswith("evidence."):
            r.setdefault("evidence", {})[key.split(".", 1)[1]] = val
        else:
            r[key] = val
    r["revised"] = True
    r["revision_note"] = "corrected in verification fix pass (see verification.json pass1)"
    print(f"corrected {app_id}: {r['name']}")

json.dump(results, open("results.json", "w", encoding="utf-8"),
          indent=2, ensure_ascii=False)
print("saved")
