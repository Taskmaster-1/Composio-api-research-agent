"""
Composio take-home: API research agent.

For each of the 100 apps in apps.json the agent:
  1. SEARCH   - Google (Serper) for the app's developer docs + auth model,
                and a second search for existing MCP servers.
  2. READ     - downloads the top 1-2 docs pages and reads the actual text
                (not just search snippets).
  3. EXTRACT  - one LLM call turns the evidence into a structured record:
                description, auth methods, self-serve vs gated, API surface,
                MCP status, buildability verdict, blocker, evidence URLs,
                and a self-reported confidence.
  4. PERSIST  - appends to results.json after every app (crash-safe resume).

LLM: Groq -> OpenRouter -> Gemini fallback chain (see llm.py).
Verification is a separate pass: verify.py.

Usage:
  pip install -r requirements.txt
  # put GROQ_API_KEY (or OPENROUTER_API_KEY) + SERPER_API_KEY in .env
  python agent.py            # full run (resumes if interrupted)
  python agent.py --only 42  # run a single app by id (useful for retries)
"""

import json
import sys
import time
from pathlib import Path

import llm
import tools

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

APPS_FILE = Path("apps.json")
RESULTS_FILE = Path("results.json")

EXTRACT_PROMPT = """You are a technical researcher at an AI integration platform.
We turn SaaS apps into tools AI agents can call. For the app below, extract the
facts from the evidence provided. Use ONLY the evidence; if the evidence does not
answer a field, use "unknown" and lower your confidence. Do not guess.

APP: {name}
CATEGORY: {category}
HINT: {hint}

=== SEARCH RESULTS (docs / auth) ===
{docs_results}

=== SEARCH RESULTS (MCP server) ===
{mcp_results}

=== SEARCH RESULTS (getting credentials / free access) ===
{access_results}

=== PAGE 1 TEXT ({page1_url}) ===
{page1}

=== PAGE 2 TEXT ({page2_url}) ===
{page2}

=== PAGE 3 TEXT, about credential access ({page3_url}) ===
{page3}

Return ONLY a JSON object with exactly these keys:
{{
  "description": "<what the app does, one plain sentence>",
  "auth_methods": ["<OAuth2 | API Key | Basic Auth | Bearer Token | JWT | Session | None | unknown>", ...],
  "self_serve": "<self-serve | partial | gated | unknown>",
  "access_note": "<one short sentence: how a developer gets credentials, and any paywall/approval/partner gate>",
  "api_surface": "<REST | GraphQL | REST + GraphQL | SDK only | CLI only | None | unknown>",
  "api_breadth": "<one short phrase: how broad the API is, e.g. 'full CRUD on all core objects' or 'read-only reporting'>",
  "mcp": "<official | community | none found | unknown>",
  "mcp_note": "<name/source of the MCP server if any, else empty>",
  "buildable": "<yes | partial | no>",
  "blocker": "<main blocker in under 12 words, or 'none'>",
  "evidence": {{
    "auth": "<URL that supports the auth answer, or empty>",
    "access": "<URL that supports the self-serve/gated answer, or empty>",
    "api": "<URL of the main API docs, or empty>",
    "mcp": "<URL that supports the MCP answer, or empty>"
  }},
  "confidence": "<high | medium | low>"
}}

Definitions:
- self-serve: any developer can obtain working API credentials on a free plan or
  trial without talking to sales or waiting for approval.
- partial: credentials exist but need a paid plan, app review, or admin approval.
- gated: enterprise/partner-only API, contact-sales, or no public API at all.
- buildable yes: public documented API + self-serve credentials -> an agent
  toolkit could be built today.
- buildable partial: API exists but with real friction (paid tier, review queue,
  narrow scope).
- buildable no: no public API, or access is closed.
- "buildable" must be yes, partial, or no — derive it from the auth/access/API
  fields above even when individual fields are uncertain.
- Prefer "self-serve"/"partial"/"gated" over "unknown" when search snippets give
  a clear signal (e.g. "sign up free", "contact sales", "apply for access").
- confidence high only if the fetched PAGE TEXT (not just snippets) supports the answers.
"""

REQUIRED_KEYS = ("description", "auth_methods", "self_serve", "access_note",
                 "api_surface", "api_breadth", "mcp", "mcp_note", "buildable",
                 "blocker", "evidence", "confidence")


def research_app(app: dict) -> dict:
    name, hint = app["name"], app["hint"]

    docs_results = tools.search(f'{name} {hint} API documentation authentication developer')
    time.sleep(0.3)
    mcp_results = tools.search(f'"{name}" MCP server model context protocol')
    time.sleep(0.3)
    access_results = tools.search(
        f'{name} API access get API key free plan developer account sign up')

    links = tools.pick_docs_links(docs_results, limit=2)
    page1_url = links[0] if len(links) > 0 else ""
    page2_url = links[1] if len(links) > 1 else ""
    access_links = [u for u in tools.pick_docs_links(access_results, limit=2)
                    if u not in (page1_url, page2_url)]
    page3_url = access_links[0] if access_links else ""
    page1 = tools.fetch_page(page1_url) if page1_url else ""
    page2 = tools.fetch_page(page2_url) if page2_url else ""
    page3 = tools.fetch_page(page3_url) if page3_url else ""

    prompt = EXTRACT_PROMPT.format(
        name=name, category=app["category"], hint=hint,
        docs_results=tools.format_results(docs_results) or "none",
        mcp_results=tools.format_results(mcp_results) or "none",
        access_results=tools.format_results(access_results) or "none",
        page1_url=page1_url or "n/a", page1=page1 or "(fetch failed or empty)",
        page2_url=page2_url or "n/a", page2=page2 or "(fetch failed or empty)",
        page3_url=page3_url or "n/a", page3=page3 or "(fetch failed or empty)",
    )

    data = llm.chat_json(prompt)
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"LLM output missing keys: {missing}")

    record = {"id": app["id"], "name": name, "category": app["category"]}
    record.update({k: data[k] for k in REQUIRED_KEYS})
    record["sources_fetched"] = [u for u in (page1_url, page2_url) if u]
    record["verified"] = False  # verify.py flips this
    return record


def load_results() -> list:
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    return []


def save_results(results: list):
    RESULTS_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False),
                            encoding="utf-8")


def main():
    apps = json.loads(APPS_FILE.read_text(encoding="utf-8"))

    only_id = None
    if "--only" in sys.argv:
        only_id = int(sys.argv[sys.argv.index("--only") + 1])
        apps = [a for a in apps if a["id"] == only_id]

    results = load_results()
    done = {r["id"] for r in results}

    print(f"=== Composio research agent: {len(apps)} apps, {len(done)} already done ===")
    for app in apps:
        if app["id"] in done and only_id is None:
            continue
        print(f"[{app['id']:3d}/100] {app['name']} ({app['category']})")
        try:
            record = research_app(app)
            # --only reruns replace the existing record
            results = [r for r in results if r["id"] != app["id"]] + [record]
            results.sort(key=lambda r: r["id"])
            print(f"    auth={record['auth_methods']} access={record['self_serve']} "
                  f"buildable={record['buildable']} conf={record['confidence']}")
        except Exception as e:
            print(f"    FAILED: {e}")
            results = [r for r in results if r["id"] != app["id"]]
            results.append({"id": app["id"], "name": app["name"],
                            "category": app["category"], "error": str(e)[:200],
                            "confidence": "low", "verified": False})
            results.sort(key=lambda r: r["id"])
        save_results(results)
        time.sleep(1.0)

    print(f"\nDone. {len(results)} records in {RESULTS_FILE}")
    print(f"LLM usage by model: {llm.usage}")


if __name__ == "__main__":
    main()
