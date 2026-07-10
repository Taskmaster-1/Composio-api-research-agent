"""Apply hand-verified corrections from manual_checks.json findings to results.json.

Each correction cites the docs page a human actually read; records are marked
revised so the case study can count human fixes honestly.
"""
import json

CORRECTIONS = {
    90: {  # PitchBook — Postman docs: "requires a standalone contract agreement"
        "self_serve": "gated",
        "access_note": "The API is a separate offering from the PitchBook platform that requires a standalone contract agreement — sales-gated.",
        "buildable": "no",
        "blocker": "standalone contract with PitchBook sales required",
        "evidence.access": "https://documenter.getpostman.com/view/5190535/TzCV1iRc",
    },
    11: {  # Zendesk — free trial + sponsored dev accounts have full API access
        "self_serve": "self-serve",
        "access_note": "Free 14-day trial has full API access, and Zendesk sponsors non-expiring dev instances for integration builders.",
        "buildable": "yes",
        "blocker": "none",
        "evidence.access": "https://developer.zendesk.com/documentation/api-basics/getting-started/getting-a-trial-or-sponsored-account-for-development/",
    },
    98: {  # Mermaid CLI — local npm CLI, no hosted API, no credentials
        "auth_methods": ["None"],
        "self_serve": "self-serve",
        "access_note": "Open-source npm CLI (mmdc); no credentials of any kind — runs locally.",
        "api_surface": "CLI only",
        "api_breadth": "diagram file in, SVG/PNG/PDF out; also a Node.js run() API",
        "buildable": "partial",
        "blocker": "no hosted API — a toolkit would wrap the local CLI",
        "evidence.auth": "https://github.com/mermaid-js/mermaid-cli",
        "evidence.access": "https://github.com/mermaid-js/mermaid-cli",
    },
    28: {  # WhatsApp — Cloud API uses Bearer access tokens
        "auth_methods": ["Bearer Token"],
        "access_note": "Free test number + temporary access token on signup; production messaging needs a permanent system-user token and Meta business verification.",
        "blocker": "business verification for production messaging",
        "evidence.auth": "https://developers.facebook.com/docs/whatsapp/cloud-api/get-started",
    },
    93: {  # Fathom — MCP link was for Fathom Analytics, a different company
        "mcp": "none found",
        "mcp_note": "earlier hit (mcp-fathom-analytics) is for Fathom Analytics, a different product",
        "evidence.mcp": "",
    },
}

results = json.load(open("results.json", encoding="utf-8"))
by_id = {r["id"]: r for r in results}
for app_id, changes in CORRECTIONS.items():
    r = by_id[app_id]
    for key, val in changes.items():
        if key.startswith("evidence."):
            r.setdefault("evidence", {})[key.split(".", 1)[1]] = val
        else:
            r[key] = val
    r["revised"] = True
    r["revision_note"] = "corrected after human docs check (see manual_checks.json)"
    print(f"corrected {app_id}: {r['name']}")

json.dump(results, open("results.json", "w", encoding="utf-8"),
          indent=2, ensure_ascii=False)
print("saved")
