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
verify_fast.py      deterministic checker (NO LLM): re-fetches every evidence
   │                URL, tests each claim via liveness + keyword support
   │                →  verification.json pass 1
   ▼
fix_pass2.py /      corrections grounded in docs a human actually read,
apply_corrections.py  plus evidence-URL hygiene — all logged in the data
   ▼
verify_fast.py      pass 2 — shows how support moved because of the loop
   │
   ▼
build_site.py  →  index.html (the case study)
```

There is also `verify.py`, an LLM-judge verifier (same independence rules,
richer verdicts including "contradicted"). It works, but on free-tier LLM
quotas it took >75 minutes for one pass, so the shipped numbers come from the
deterministic checker — which has the nicer property that it *cannot*
hallucinate agreement, at the cost of undercounting on JS-rendered docs.

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
copy .env.example .env     # then fill in the keys

python agent.py            # research all 100 apps (resumes if interrupted)
python verify_fast.py      # verification pass 1 (deterministic, ~2 min)
python show_flags.py       # inspect what got flagged
#  fix flagged records (see fix_pass2.py for the pattern), then:
python verify_fast.py      # pass 2 — measures the improvement
python build_site.py       # generate index.html
```

`python agent.py --only 42` re-runs a single app by id.

## Files

| File | Purpose |
|---|---|
| `apps.json` | the 100-app research set (10 categories) |
| `agent.py` | research agent: search → read → extract → checkpoint |
| `llm.py` | Groq/OpenRouter/Gemini fallback client with 429 cool-downs |
| `tools.py` | Serper search + HTML-to-text page fetcher |
| `verify_fast.py` | deterministic verifier (no LLM): liveness + keyword support |
| `verify.py` | LLM-judge verifier (slower, richer verdicts) — kept, works |
| `show_flags.py` | print dead links + flagged apps from the latest pass |
| `apply_corrections.py` | corrections from the human doc-check (5 records) |
| `fix_pass2.py` | corrections + URL hygiene from machine pass 1 (6 records) |
| `build_site.py` | renders results + verification into `index.html` |
| `results.json` | agent output (one record per app, evidence URLs per claim) |
| `verification.json` | claim-level verdicts per pass |
| `manual_checks.json` | 13 human spot-checks, hits and misses |
| `fallback_records.json` | the 16 human-researched records (rate-limit fallback) |
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
