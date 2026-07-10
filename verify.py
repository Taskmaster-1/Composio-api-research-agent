"""
Verification loop for the research agent's output.

The agent's first pass can be wrong (stale snippets, marketing pages, LLM
overconfidence). This script runs an independent check pass and a fix pass:

  python verify.py --check     # pass 1: re-fetch each record's evidence URLs
                               # and have a verifier LLM judge every claim
                               # against the page text. Writes verification.json
  python verify.py --fix       # re-research every app the verifier flagged,
                               # feeding the verifier's objection back into the
                               # research prompt. Updates results.json
  python verify.py --check     # pass 2: re-judge, so accuracy before vs after
                               # the fix loop is measurable

The verifier is deliberately independent from the researcher: it never sees
the researcher's search results, only the claimed record + freshly fetched
evidence pages. A claim with no working evidence URL cannot be "supported".

Manual (human) spot checks live in manual_checks.json and are merged into the
final report by build_site.py.
"""

import json
import sys
import time
from pathlib import Path

import llm
import tools

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RESULTS_FILE = Path("results.json")
VERIFICATION_FILE = Path("verification.json")

CHECKED_FIELDS = ("auth_methods", "self_serve", "api_surface", "mcp", "buildable")

VERIFY_PROMPT = """You are an independent fact-checker. Another researcher produced
this record about the app "{name}". Judge each claim ONLY against the evidence
page text below. Do not use prior knowledge to mark something supported; if the
pages do not contain enough information, say "insufficient".

CLAIMED RECORD:
  auth_methods: {auth_methods}
  self_serve:   {self_serve}   (note: {access_note})
  api_surface:  {api_surface}
  mcp:          {mcp}          (note: {mcp_note})
  buildable:    {buildable}    (blocker: {blocker})

=== EVIDENCE PAGE 1 ({url1}) ===
{page1}

=== EVIDENCE PAGE 2 ({url2}) ===
{page2}

Return ONLY JSON:
{{
  "auth_methods": {{"verdict": "<supported|contradicted|insufficient>", "why": "<short>"}},
  "self_serve":   {{"verdict": "<supported|contradicted|insufficient>", "why": "<short>"}},
  "api_surface":  {{"verdict": "<supported|contradicted|insufficient>", "why": "<short>"}},
  "mcp":          {{"verdict": "<supported|contradicted|insufficient>", "why": "<short>"}},
  "buildable":    {{"verdict": "<supported|contradicted|insufficient>", "why": "<short>"}}
}}
Rules:
- "supported": the page text directly backs the claim.
- "contradicted": the page text says something different -> quote it in "why".
- "insufficient": pages are empty, irrelevant, or silent on this field.
- For "mcp" = "none found", treat as supported only if an MCP search would
  plausibly have found nothing; if pages are silent, use "insufficient".
"""


def evidence_pages(record):
    """Fetch up to two distinct evidence URLs for a record."""
    urls = []
    ev = record.get("evidence", {}) or {}
    for key in ("auth", "access", "api", "mcp"):
        u = (ev.get(key) or "").strip()
        if u and u not in urls:
            urls.append(u)
    urls = urls[:2]
    pages = [tools.fetch_page(u, max_chars=4500) for u in urls]
    while len(urls) < 2:
        urls.append("")
        pages.append("")
    return urls, pages


def check_record(record) -> dict:
    urls, pages = evidence_pages(record)
    if not any(pages):
        # No fetchable evidence at all: every claim is unverifiable.
        return {f: {"verdict": "insufficient", "why": "no fetchable evidence URL"}
                for f in CHECKED_FIELDS}
    prompt = VERIFY_PROMPT.format(
        name=record["name"],
        auth_methods=record.get("auth_methods"),
        self_serve=record.get("self_serve"),
        access_note=record.get("access_note", ""),
        api_surface=record.get("api_surface"),
        mcp=record.get("mcp"),
        mcp_note=record.get("mcp_note", ""),
        buildable=record.get("buildable"),
        blocker=record.get("blocker", ""),
        url1=urls[0] or "n/a", page1=pages[0] or "(empty)",
        url2=urls[1] or "n/a", page2=pages[1] or "(empty)",
    )
    return llm.chat_json(prompt)


def run_check():
    results = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    history = {}
    if VERIFICATION_FILE.exists():
        history = json.loads(VERIFICATION_FILE.read_text(encoding="utf-8"))
    pass_no = len([k for k in history if k.startswith("pass")]) + 1

    details, supported = [], 0
    total_claims = 0
    for r in results:
        if "error" in r:
            details.append({"id": r["id"], "name": r["name"], "skipped": "agent error"})
            continue
        print(f"[verify {r['id']:3d}] {r['name']}")
        try:
            verdicts = check_record(r)
        except Exception as e:
            print(f"    verifier failed: {e}")
            verdicts = {f: {"verdict": "insufficient", "why": f"verifier error: {e}"}
                        for f in CHECKED_FIELDS}
        flagged = [f for f in CHECKED_FIELDS
                   if verdicts.get(f, {}).get("verdict") != "supported"]
        n_sup = len(CHECKED_FIELDS) - len(flagged)
        supported += n_sup
        total_claims += len(CHECKED_FIELDS)
        details.append({"id": r["id"], "name": r["name"],
                        "verdicts": verdicts, "flagged_fields": flagged})
        print(f"    {n_sup}/{len(CHECKED_FIELDS)} claims supported"
              + (f" — flagged: {flagged}" if flagged else ""))
        time.sleep(0.5)

    summary = {
        "claims_checked": total_claims,
        "claims_supported": supported,
        "support_rate": round(supported / total_claims, 3) if total_claims else 0,
        "apps_fully_supported": sum(1 for d in details if d.get("flagged_fields") == []),
        "details": details,
    }
    history[f"pass{pass_no}"] = summary
    VERIFICATION_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
    print(f"\nPASS {pass_no}: {supported}/{total_claims} claims supported "
          f"({summary['support_rate']:.0%}), "
          f"{summary['apps_fully_supported']} apps fully supported.")
    print(f"Written to {VERIFICATION_FILE}")


def run_fix():
    """Re-research flagged apps, telling the researcher what the verifier objected to."""
    import agent

    results = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    history = json.loads(VERIFICATION_FILE.read_text(encoding="utf-8"))
    last_pass = history[sorted(k for k in history if k.startswith("pass"))[-1]]

    apps = {a["id"]: a for a in json.loads(Path("apps.json").read_text(encoding="utf-8"))}
    by_id = {r["id"]: r for r in results}

    to_fix = [d for d in last_pass["details"]
              if d.get("flagged_fields") or "error" in by_id.get(d["id"], {})]
    print(f"=== fix pass: {len(to_fix)} apps flagged ===")

    for d in to_fix:
        app = apps[d["id"]]
        old = by_id.get(d["id"], {})
        objections = "; ".join(
            f"{f}: {d['verdicts'][f]['why']}" for f in d.get("flagged_fields", [])
            if f in d.get("verdicts", {})
        ) or "previous attempt errored out"
        print(f"[fix {app['id']:3d}] {app['name']} — {objections[:100]}")
        # Feed the objection into the research by appending it to the hint, so
        # the researcher targets the disputed facts and finds better evidence.
        patched = dict(app)
        patched["hint"] = (f"{app['hint']}. A fact-checker disputed the previous "
                           f"answer ({objections}). Find authoritative docs pages "
                           f"that settle: auth model, credential access, API type, MCP.")
        try:
            record = agent.research_app(patched)
            record["revised"] = True
            by_id[app["id"]] = record
        except Exception as e:
            print(f"    fix failed: {e}")
        time.sleep(1.0)

    merged = sorted(by_id.values(), key=lambda r: r["id"])
    RESULTS_FILE.write_text(json.dumps(merged, indent=2, ensure_ascii=False),
                            encoding="utf-8")
    print(f"Updated {RESULTS_FILE}. Now run: python verify.py --check  (pass 2)")


if __name__ == "__main__":
    if "--fix" in sys.argv:
        run_fix()
    else:
        run_check()
