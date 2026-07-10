# Composio Take-Home — API Research Agent

Research agent that profiles 100 SaaS apps for agent-toolkit buildability:
auth model, self-serve vs gated credentials, API surface, existing MCP servers,
and a buildability verdict — each backed by evidence URLs, then fact-checked by
an independent verification loop.

**Live case study:** see `index.html` (deployed link in the submission).

## How it works

```
apps.json (100 apps)
   │
   ▼
agent.py ──► per app: 3 Google searches (Serper)  ──►  fetch top docs pages
   │             docs/auth · MCP servers · credential access
   │
   ▼
LLM extraction (Groq → OpenRouter → Gemini fallback chain, llm.py)
   │        structured JSON: auth, access, API surface, MCP, verdict,
   │        per-field evidence URLs, self-reported confidence
   ▼
results.json  (checkpointed after every app — crash-safe resume)
   │
   ▼
verify.py --check   independent verifier re-fetches each record's evidence
   │                URLs and judges every claim: supported / contradicted /
   │                insufficient  →  verification.json (pass 1 accuracy)
   ▼
verify.py --fix     re-researches every flagged app, feeding the verifier's
   │                objection back into the research prompt
   ▼
verify.py --check   pass 2 — shows how accuracy moved because of the loop
   │
   ▼
build_site.py  →  index.html (the case study)
```

Design choices worth knowing:

- **The agent reads pages, not just snippets.** Search snippets say "X has an
  API"; only the docs page says whether the OAuth app needs a review queue.
- **The verifier is independent.** It never sees the researcher's search
  results — only the claimed record and freshly fetched evidence pages. A claim
  whose evidence URL doesn't load cannot be "supported".
- **Provider fallback chain.** Run #1 of this project died on Gemini free-tier
  429s (`artifacts_run1_gemini_429.json` kept as proof). The client now rotates
  Groq → OpenRouter → Gemini with backoff, and reports which models did the work.
- **"Unknown" is allowed.** The extraction prompt forbids guessing; a gated app
  with evidence is a correct finding, not a failure.

## Run it

```powershell
pip install -r requirements.txt

# .env
#   GROQ_API_KEY=...        (or OPENROUTER_API_KEY / GEMINI_API_KEY — any subset)
#   SERPER_API_KEY=...      (google search, free tier is plenty)

python agent.py            # research all 100 apps (resumes if interrupted)
python verify.py --check   # verification pass 1
python verify.py --fix     # re-research flagged apps
python verify.py --check   # verification pass 2
python build_site.py       # generate index.html
```

`python agent.py --only 42` re-runs a single app by id.

## Files

| File | Purpose |
|---|---|
| `apps.json` | the 100-app research set (10 categories) |
| `agent.py` | research agent: search → read → extract → checkpoint |
| `llm.py` | Groq/OpenRouter/Gemini fallback client with 429 handling |
| `tools.py` | Serper search + HTML-to-text page fetcher |
| `verify.py` | verification loop: check pass, fix pass, accuracy history |
| `build_site.py` | renders results + verification into `index.html` |
| `results.json` | agent output (one record per app) |
| `verification.json` | claim-level verdicts per pass |
| `manual_checks.json` | human spot-checks merged into the report |
| `artifacts_run1_gemini_429.json` | the failed first run, kept honestly |

## Where a human was needed

Documented on the case-study page itself — in short:

- choosing the field schema and definitions (what "self-serve" means);
- unblocking the quota-exhausted first run and building the fallback chain;
- **16 apps finished by a human-driven research pass** (same schema, same
  evidence-URL rules) when every free-tier LLM in the chain was rate-limited —
  marked `researched_by` in `results.json`;
- 13 hand spot-checks against real docs (`manual_checks.json`), which caught
  entity confusion, context bleed, and wrong gating verdicts — 5 records
  corrected via `apply_corrections.py`;
- writing the pattern analysis that the table alone doesn't give you.

## Deploying the case study

`index.html` is fully static — GitHub Pages, Netlify drop, or Vercel all work:

```powershell
git init && git add -A && git commit -m "API research agent + case study"
# push to GitHub, then enable Pages on the repo (deploy from branch, root)
```
