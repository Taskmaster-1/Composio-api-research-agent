"""
Fast deterministic verification pass — no LLM anywhere in the loop.

For every record in results.json it re-fetches the record's evidence URLs and
judges each claim mechanically:

  auth_methods  supported if a claimed method's keywords appear in evidence text
  self_serve    supported if access-language keywords match the claimed level
  api_surface   supported if the claimed surface's keywords appear
  mcp           supported if "mcp" / "model context protocol" appears on the
                cited MCP evidence page ("none found" is an absence claim — not
                machine-checkable, counted separately, human-checked on a sample)
  buildable     derived claim — supported when both auth and self_serve are

A claim whose evidence URL is dead or empty can never be supported. This is a
deliberately blunt instrument: it cannot hallucinate agreement (the failure mode
an LLM verifier shares with an LLM researcher), it is reproducible, and it runs
in minutes. The judgment-call layer on top of it is the human spot-check table
in manual_checks.json.

Usage:  python verify_fast.py            # appends passN to verification.json
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import tools

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RESULTS_FILE = Path("results.json")
VERIFICATION_FILE = Path("verification.json")

AUTH_KEYWORDS = {
    "oauth2": ["oauth"], "oauth": ["oauth"],
    "api key": ["api key", "api-key", "apikey", "x-api-key", "api_key"],
    "bearer token": ["bearer", "access token", "personal access token", "auth token", "token"],
    "basic auth": ["basic auth", "basic authentication"],
    "jwt": ["jwt", "key pair", "key-pair"],
    "session": ["session"],
    "none": [],  # absence claim — handled specially
}
ACCESS_KEYWORDS = {
    "self-serve": ["sign up", "signup", "free", "trial", "get started",
                   "create an account", "generate an api key", "create api key",
                   "in minutes", "instantly", "developer account"],
    "partial": ["paid plan", "paid", "upgrade", "approval", "review", "admin",
                "business plan", "enterprise", "subscription", "verification"],
    "gated": ["contact sales", "contact us", "enterprise", "contract", "partner",
              "request access", "apply", "quote", "sales team", "licensing"],
}
SURFACE_KEYWORDS = {
    "rest": ["rest", "http api", "endpoint", "api reference", "curl"],
    "graphql": ["graphql"],
    "cli": ["cli", "command line", "command-line"],
    "sdk": ["sdk"],
}

CHECKED_FIELDS = ("auth_methods", "self_serve", "api_surface", "mcp", "buildable")


def fetch_all(urls):
    """Fetch unique URLs concurrently -> {url: text}."""
    unique = sorted({u for u in urls if u})
    texts = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        for url, text in zip(unique, ex.map(lambda u: tools.fetch_page(u, 12000), unique)):
            texts[url] = text
    return texts


def check_record(r, pages):
    ev = r.get("evidence") or {}
    v = {}

    def page(key):
        return pages.get((ev.get(key) or "").strip(), "")

    # pool of all evidence text for this record
    all_text = " ".join(pages.get((u or "").strip(), "")
                        for u in ev.values()).lower()

    # auth: any claimed method's keywords present anywhere in evidence
    claimed = [a.lower() for a in (r.get("auth_methods") or [])]
    if claimed == ["none"]:
        v["auth_methods"] = {
            "verdict": "not-machine-checkable",
            "why": "absence claim (no auth) — verified by human spot-check only"}
    elif not all_text.strip():
        v["auth_methods"] = {"verdict": "insufficient", "why": "evidence URLs dead or empty"}
    else:
        hits = [a for a in claimed
                for kw in AUTH_KEYWORDS.get(a, [a])
                if kw in all_text]
        v["auth_methods"] = ({"verdict": "supported", "why": f"keywords found for {sorted(set(hits))}"}
                             if hits else
                             {"verdict": "insufficient", "why": f"no keyword match for {claimed}"})

    # self_serve: claimed level's language present on access/auth evidence
    level = (r.get("self_serve") or "unknown").lower()
    txt = (page("access") + " " + page("auth") + " " + page("api")).lower()
    if level not in ACCESS_KEYWORDS:
        v["self_serve"] = {"verdict": "insufficient", "why": f"claim is '{level}'"}
    elif not txt.strip():
        v["self_serve"] = {"verdict": "insufficient", "why": "evidence URLs dead or empty"}
    else:
        kws = [k for k in ACCESS_KEYWORDS[level] if k in txt]
        v["self_serve"] = ({"verdict": "supported", "why": f"matched {kws[:3]}"}
                           if kws else
                           {"verdict": "insufficient", "why": "no access-language match"})

    # api_surface
    surface = (r.get("api_surface") or "unknown").lower()
    api_txt = (page("api") + " " + page("auth")).lower()
    want = [k for k in SURFACE_KEYWORDS if k in surface]
    if surface in ("none", "unknown") or not want:
        v["api_surface"] = {
            "verdict": "not-machine-checkable",
            "why": f"claim '{surface}' — absence/unknown claims are human-checked"}
    elif not api_txt.strip():
        v["api_surface"] = {"verdict": "insufficient", "why": "evidence URLs dead or empty"}
    else:
        ok = all(any(kw in api_txt for kw in SURFACE_KEYWORDS[k]) for k in want)
        v["api_surface"] = ({"verdict": "supported", "why": f"found {want}"}
                            if ok else
                            {"verdict": "insufficient", "why": f"{want} not evident on cited page"})

    # mcp
    mcp_claim = (r.get("mcp") or "unknown").lower()
    mcp_txt = page("mcp").lower()
    if "none" in mcp_claim or mcp_claim == "unknown":
        v["mcp"] = {"verdict": "not-machine-checkable",
                    "why": "absence claim — human-checked on a sample"}
    elif not mcp_txt.strip():
        v["mcp"] = {"verdict": "insufficient", "why": "MCP evidence URL dead or empty"}
    elif "mcp" in mcp_txt or "model context protocol" in mcp_txt:
        v["mcp"] = {"verdict": "supported", "why": "MCP referenced on cited page"}
    else:
        v["mcp"] = {"verdict": "insufficient", "why": "cited page does not mention MCP"}

    # buildable: derived from auth + access
    base = (v["auth_methods"]["verdict"], v["self_serve"]["verdict"])
    if all(b in ("supported", "not-machine-checkable") for b in base):
        v["buildable"] = {"verdict": "supported", "why": "derived: auth + access hold up"}
    else:
        v["buildable"] = {"verdict": "insufficient", "why": "derived: an input claim is unsupported"}
    return v


def main():
    results = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    history = (json.loads(VERIFICATION_FILE.read_text(encoding="utf-8"))
               if VERIFICATION_FILE.exists() else {})
    pass_no = len([k for k in history if k.startswith("pass")]) + 1

    urls = [u for r in results for u in (r.get("evidence") or {}).values()]
    print(f"fetching {len(set(u for u in urls if u))} unique evidence URLs...")
    pages = fetch_all(urls)
    dead = sorted(u for u, t in pages.items() if not t)
    print(f"{len(dead)} evidence URLs dead or empty")

    details, supported, checkable = [], 0, 0
    for r in results:
        verdicts = check_record(r, pages)
        flagged = [f for f in CHECKED_FIELDS
                   if verdicts[f]["verdict"] == "insufficient"]
        n_checkable = sum(1 for f in CHECKED_FIELDS
                          if verdicts[f]["verdict"] != "not-machine-checkable")
        n_sup = sum(1 for f in CHECKED_FIELDS
                    if verdicts[f]["verdict"] == "supported")
        supported += n_sup
        checkable += n_checkable
        details.append({"id": r["id"], "name": r["name"],
                        "verdicts": verdicts, "flagged_fields": flagged})

    summary = {
        "method": "deterministic: evidence-URL liveness + keyword support (no LLM)",
        "claims_checked": checkable,
        "claims_supported": supported,
        "support_rate": round(supported / checkable, 3) if checkable else 0,
        "apps_fully_supported": sum(1 for d in details if not d["flagged_fields"]),
        "dead_evidence_urls": dead,
        "details": details,
    }
    history[f"pass{pass_no}"] = summary
    VERIFICATION_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
    print(f"PASS {pass_no}: {supported}/{checkable} machine-checkable claims supported "
          f"({summary['support_rate']:.0%}); "
          f"{summary['apps_fully_supported']} apps with no flags; "
          f"{len(dead)} dead evidence links")


if __name__ == "__main__":
    main()
