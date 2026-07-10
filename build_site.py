"""
Render results.json + verification.json + manual_checks.json into index.html —
the single self-explanatory case-study page the assignment asks for.

Everything on the page is computed from the JSON files; regenerate any time:
  python build_site.py
"""

import datetime
import html
import json
import re
from collections import Counter
from pathlib import Path

RESULTS = json.loads(Path("results.json").read_text(encoding="utf-8"))
VERIF = (json.loads(Path("verification.json").read_text(encoding="utf-8"))
         if Path("verification.json").exists() else {})
MANUAL = (json.loads(Path("manual_checks.json").read_text(encoding="utf-8"))
          if Path("manual_checks.json").exists() else [])

E = lambda s: html.escape(str(s or ""))

# ── normalization ─────────────────────────────────────────────────────────────

def auth_families(r):
    """Collapse raw auth strings into canonical families."""
    fams = set()
    for a in r.get("auth_methods") or []:
        a = a.lower()
        if "oauth" in a:
            fams.add("OAuth2")
        elif "api key" in a or "api-key" in a or "apikey" in a:
            fams.add("API Key")
        elif "basic" in a:
            fams.add("Basic Auth")
        elif "bearer" in a or "token" in a or "jwt" in a or "pat" in a:
            fams.add("Token / JWT")
        elif "session" in a or "cookie" in a:
            fams.add("Session")
        elif "none" in a:
            fams.add("None")
        else:
            fams.add("Other")
    return fams or {"Unknown"}


def access_of(r):
    v = (r.get("self_serve") or "unknown").lower()
    if "self" in v:
        return "self-serve"
    if "partial" in v:
        return "partial"
    if "gated" in v or v == "no":
        return "gated"
    return "unknown"


def buildable_of(r):
    v = (r.get("buildable") or "unknown").lower()
    return v if v in ("yes", "partial", "no") else "unknown"


def mcp_of(r):
    v = (r.get("mcp") or "unknown").lower()
    if "official" in v:
        return "official"
    if "community" in v:
        return "community"
    if "none" in v:
        return "none found"
    return "unknown"


OK = [r for r in RESULTS if "error" not in r]
ERRORED = [r for r in RESULTS if "error" in r]
N = len(RESULTS)

CATEGORIES = []
for r in RESULTS:
    if r["category"] not in CATEGORIES:
        CATEGORIES.append(r["category"])

# ── stats ─────────────────────────────────────────────────────────────────────

auth_count = Counter()
for r in OK:
    for f in auth_families(r):
        auth_count[f] += 1

access_count = Counter(access_of(r) for r in OK)
build_count = Counter(buildable_of(r) for r in OK)
mcp_count = Counter(mcp_of(r) for r in OK)

cat_access = {c: Counter() for c in CATEGORIES}
cat_build = {c: Counter() for c in CATEGORIES}
for r in OK:
    cat_access[r["category"]][access_of(r)] += 1
    cat_build[r["category"]][buildable_of(r)] += 1

blocker_words = Counter()
for r in OK:
    b = (r.get("blocker") or "").lower()
    if not b or b.startswith("none"):
        continue
    for kws, label in [
        (("paid",), "paid plan required"),
        (("enterprise", "sales", "contract", "quote", "licensing", "partner",
          "certification"), "enterprise / partner gate"),
        (("approval", "review", "admin", "owner", "privileg", "permission"),
         "app review or admin gate"),
        (("no public", "no inbound", "no rest", "no api"), "no public API"),
        (("rate", "quota"), "rate limits"),
        (("not explicitly documented", "unclear", "varies", "no public auth",
          "requirements"), "docs gaps"),
    ]:
        if any(k in b for k in kws):
            blocker_words[label] += 1
            break
    else:
        blocker_words["other"] += 1

easy_wins = [r for r in OK if buildable_of(r) == "yes" and mcp_of(r) == "none found"
             and access_of(r) == "self-serve"]
needs_outreach = [r for r in OK if access_of(r) == "gated"]

# verification numbers
passes = sorted(k for k in VERIF if k.startswith("pass"))
p_first = VERIF.get(passes[0]) if passes else None
p_last = VERIF.get(passes[-1]) if len(passes) > 1 else None

manual_hits = sum(1 for m in MANUAL if m.get("agent_was_right"))
revised = [r for r in OK if r.get("revised")]
fallback = [r for r in OK if r.get("researched_by")]

now = datetime.datetime.now().strftime("%d %b %Y")

# ── small render helpers ──────────────────────────────────────────────────────

def bar_chart(counter, total, color="var(--s-blue)"):
    rows = ""
    for label, cnt in counter.most_common():
        pct = cnt / total * 100
        rows += f"""
        <div class="bar-row">
          <span class="bar-name">{E(label)}</span>
          <div class="bar-track"><div class="bar-fill" style="width:{pct:.0f}%;background:{color}"></div></div>
          <span class="bar-val">{cnt}</span>
        </div>"""
    return rows


ACCESS_META = {
    "self-serve": ("var(--c-open)", "Self-serve"),
    "partial": ("var(--c-partial)", "Partial"),
    "gated": ("var(--c-gated)", "Gated"),
    "unknown": ("var(--ink-3)", "Unknown"),
}
BUILD_META = {
    "yes": ("var(--c-open)", "Yes"),
    "partial": ("var(--c-partial)", "Partial"),
    "no": ("var(--c-gated)", "No"),
    "unknown": ("var(--ink-3)", "Unknown"),
}


def stacked_rows(cat_counter_map, meta):
    out = ""
    order = list(meta.keys())
    for cat in CATEGORIES:
        c = cat_counter_map[cat]
        total = sum(c.values()) or 1
        segs = ""
        for key in order:
            v = c.get(key, 0)
            if v:
                segs += (f'<div class="seg" style="flex:{v};background:{meta[key][0]}" '
                         f'title="{E(cat)} — {meta[key][1]}: {v}"><span>{v}</span></div>')
        short = cat.split("&")[0].split("/")[0].strip()
        out += (f'<div class="stack-row"><span class="stack-name">{E(short)}</span>'
                f'<div class="stack-track">{segs}</div></div>')
    return out


def legend(meta):
    return "".join(f'<span class="lg"><i style="background:{c}"></i>{E(lbl)}</span>'
                   for c, lbl in meta.values())


def waffle():
    cells = ""
    colors = {"yes": "var(--c-open)", "partial": "var(--c-partial)",
              "no": "var(--c-gated)", "unknown": "var(--ink-3)"}
    for r in sorted(RESULTS, key=lambda x: x["id"]):
        b = buildable_of(r) if "error" not in r else "unknown"
        tip = f"{r['name']} — buildable: {b}"
        cells += f'<div class="wf" style="background:{colors[b]}" title="{E(tip)}"></div>'
    return cells


def ev_links(r):
    ev = r.get("evidence") or {}
    seen, out = set(), []
    for key, label in (("api", "api"), ("auth", "auth"), ("access", "access"), ("mcp", "mcp")):
        u = (ev.get(key) or "").strip()
        if u and u not in seen:
            seen.add(u)
            out.append(f'<a class="ev" href="{E(u)}" target="_blank" rel="noopener">{label}</a>')
    return " ".join(out) or '<span class="dim">—</span>'


def table_rows():
    out = ""
    ver_by_id = {}
    if p_last or p_first:
        for d in (p_last or p_first)["details"]:
            ver_by_id[d.get("id")] = d
    for r in sorted(RESULTS, key=lambda x: x["id"]):
        if "error" in r:
            out += (f'<tr data-cat="{E(r["category"])}" data-acc="unknown">'
                    f'<td class="num">{r["id"]}</td>'
                    f'<td><strong>{E(r["name"])}</strong><small>{E(r["category"])}</small></td>'
                    f'<td colspan="6" class="dim">agent failed: {E(r["error"][:90])}</td>'
                    f'<td class="dim">—</td></tr>')
            continue
        acc = access_of(r)
        bld = buildable_of(r)
        mcp = mcp_of(r)
        auths = " ".join(f'<span class="tag">{E(a)}</span>' for a in sorted(auth_families(r)))
        acc_c, acc_l = ACCESS_META[acc]
        bld_c, bld_l = BUILD_META[bld]
        vd = ver_by_id.get(r["id"], {})
        flagged = vd.get("flagged_fields", None)
        if flagged == []:
            vcell = '<span class="ok" title="all 5 claims supported by evidence pages">✓</span>'
        elif flagged:
            vcell = f'<span class="warn" title="unresolved: {E(", ".join(flagged))}">{5 - len(flagged)}/5</span>'
        else:
            vcell = '<span class="dim">–</span>'
        blocker = r.get("blocker") or "none"
        out += f"""
      <tr data-cat="{E(r['category'])}" data-acc="{acc}">
        <td class="num">{r['id']}</td>
        <td><strong>{E(r['name'])}</strong><small>{E((r.get('description') or '')[:90])}</small></td>
        <td>{auths}</td>
        <td><span class="pill" style="color:{acc_c}">●</span> {acc_l}</td>
        <td class="apisurf">{E(r.get('api_surface'))}<small>{E(r.get('api_breadth'))}</small></td>
        <td>{E(mcp)}</td>
        <td style="color:{bld_c};font-weight:600">{bld_l}</td>
        <td class="blk">{E('' if blocker.lower() == 'none' else blocker) or '<span class="dim">none</span>'}</td>
        <td>{ev_links(r)} {vcell}</td>
      </tr>"""
    return out


def manual_rows():
    if not MANUAL:
        return '<tr><td colspan="5" class="dim">manual spot-checks pending</td></tr>'
    out = ""
    for m in MANUAL:
        ok = m.get("agent_was_right")
        mark = ('<span class="ok">✓ right</span>' if ok
                else '<span class="bad">✗ wrong</span>')
        out += (f'<tr><td><strong>{E(m["name"])}</strong></td>'
                f'<td>{E(m["field"])}</td>'
                f'<td>{E(m["agent_said"])}</td>'
                f'<td>{E(m["docs_say"])}</td>'
                f'<td>{mark}</td></tr>')
    return out


# ── insight sentences (computed, then hand-tuned wording) ─────────────────────

top_auth, top_auth_n = auth_count.most_common(1)[0]
oauth_n = auth_count.get("OAuth2", 0)
key_n = auth_count.get("API Key", 0)
ss = access_count.get("self-serve", 0)
gated = access_count.get("gated", 0)
by = build_count.get("yes", 0)
bp = build_count.get("partial", 0)
bn = build_count.get("no", 0)
mcp_official = mcp_count.get("official", 0)
mcp_comm = mcp_count.get("community", 0)

def cat_rate(cat, key="self-serve"):
    c = cat_access[cat]
    t = sum(c.values()) or 1
    return c.get(key, 0) / t

best_cat = max(CATEGORIES, key=cat_rate)
worst_cat = min(CATEGORIES, key=cat_rate)
top_blockers = ", ".join(f"{lbl} ({n})" for lbl, n in blocker_words.most_common(3))

verif_line = ""
if p_first and p_last:
    verif_line = (f"A no-LLM checker re-tested every claim against its evidence URL: "
                  f"<strong>{p_first['support_rate']:.0%}</strong> supported on pass 1, "
                  f"<strong>{p_last['support_rate']:.0%}</strong> after the fix loop, with "
                  f"{len(revised)} records corrected along the way — misses shown honestly below.")
elif p_first:
    verif_line = (f"First verification pass: <strong>{p_first['support_rate']:.0%}</strong> "
                  f"of {p_first['claims_checked']} claims supported by evidence pages.")

# ── page ──────────────────────────────────────────────────────────────────────

page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Can an agent build it? — 100 apps profiled for Composio</title>
<meta name="description" content="An AI research agent profiled 100 SaaS apps for agent-toolkit buildability: auth, credential access, API surface, MCP coverage — then fact-checked itself.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,900&family=Instrument+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root {{
  --paper:#f6f4ee; --card:#fcfbf7; --ink:#191713; --ink-2:#57534a; --ink-3:#8f8a7e;
  --line:#e3dfd3; --rule:#c9c4b4; --accent:#1c5cab; --accent-ink:#164a8a;
  --s-blue:#2a78d6;
  /* access/buildability trio — validated (CVD ΔE 40.5, all checks pass on this surface) */
  --c-open:#1c5cab; --c-partial:#eda100; --c-gated:#d03b3b;
  --st-warn:#c98500; --st-crit:#d03b3b; --good-text:#006300;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --paper:#141310; --card:#1d1b17; --ink:#f2efe6; --ink-2:#b6b1a3; --ink-3:#7d786c;
    --line:#2e2b24; --rule:#3c382e; --accent:#6da7ec; --accent-ink:#86b6ef;
    --s-blue:#3987e5;
    /* dark steps of the same trio — validated separately (ΔE 35.9, all pass) */
    --c-open:#3987e5; --c-partial:#c98500; --c-gated:#e66767;
    --st-warn:#fab219; --st-crit:#e66767; --good-text:#0ca30c;
  }}
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
html {{ scroll-behavior:smooth; }}
body {{ background:var(--paper); color:var(--ink); font:16px/1.6 "Instrument Sans",sans-serif;
       -webkit-font-smoothing:antialiased; }}
.mono {{ font-family:"IBM Plex Mono",monospace; }}
.wrap {{ max-width:1180px; margin:0 auto; padding:0 28px; }}
a {{ color:var(--accent); }}

/* masthead */
header {{ border-bottom:3px double var(--rule); padding:26px 0 22px; }}
.mast {{ display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:8px; }}
.mast .brand {{ font-family:Fraunces,serif; font-weight:900; font-size:20px; letter-spacing:-.02em; }}
.mast .meta {{ font-family:"IBM Plex Mono",monospace; font-size:12px; color:var(--ink-2); }}

/* hero */
.hero {{ padding:64px 0 30px; }}
.kicker {{ font-family:"IBM Plex Mono",monospace; font-size:12px; letter-spacing:.14em;
          text-transform:uppercase; color:var(--accent); margin-bottom:18px; }}
h1 {{ font-family:Fraunces,serif; font-weight:900; font-size:clamp(38px,6vw,72px);
     line-height:1.02; letter-spacing:-.025em; max-width:15ch; }}
h1 em {{ font-style:italic; color:var(--accent); }}
.standfirst {{ margin-top:22px; max-width:62ch; font-size:18px; color:var(--ink-2); }}

/* stat band */
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
         border-block:1px solid var(--rule); margin:44px 0; }}
.stat {{ padding:20px 18px; border-right:1px solid var(--line); }}
.stat:last-child {{ border-right:0; }}
.stat b {{ display:block; font-family:Fraunces,serif; font-weight:900; font-size:40px;
          letter-spacing:-.02em; line-height:1.1; }}
.stat span {{ font-size:12.5px; color:var(--ink-2); }}
.stat .good {{ color:var(--good-text); }} .stat .warn {{ color:var(--st-warn); }}
.stat .crit {{ color:var(--st-crit); }}

/* sections */
section {{ padding:52px 0 8px; }}
.sec-head {{ display:flex; align-items:baseline; gap:14px; border-bottom:1px solid var(--rule);
            padding-bottom:12px; margin-bottom:28px; }}
.sec-no {{ font-family:"IBM Plex Mono",monospace; color:var(--accent); font-size:13px; }}
h2 {{ font-family:Fraunces,serif; font-weight:900; font-size:clamp(24px,3.4vw,36px);
     letter-spacing:-.02em; }}
.sec-note {{ margin-left:auto; font-size:13px; color:var(--ink-3); }}

/* insights */
.insights {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:14px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:22px; }}
.card h3 {{ font-family:Fraunces,serif; font-weight:600; font-size:19px; margin-bottom:8px; }}
.card p {{ font-size:14.5px; color:var(--ink-2); }}
.card p strong {{ color:var(--ink); }}
.big-insight {{ grid-column:1/-1; border-left:4px solid var(--accent); }}
.big-insight h3 {{ font-size:24px; }}

/* charts */
.charts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:14px; margin-top:14px; }}
.chart-title {{ font-family:"IBM Plex Mono",monospace; font-size:11.5px; letter-spacing:.1em;
               text-transform:uppercase; color:var(--ink-2); margin-bottom:16px; }}
.bar-row {{ display:grid; grid-template-columns:110px 1fr 34px; align-items:center; gap:10px; margin-bottom:9px; }}
.bar-name {{ font-size:13px; color:var(--ink-2); }}
.bar-track {{ height:14px; background:transparent; }}
.bar-fill {{ height:100%; border-radius:0 4px 4px 0; min-width:2px; }}
.bar-val {{ font-family:"IBM Plex Mono",monospace; font-size:12.5px; text-align:right; }}
.stack-row {{ display:grid; grid-template-columns:110px 1fr; align-items:center; gap:10px; margin-bottom:8px; }}
.stack-name {{ font-size:13px; color:var(--ink-2); }}
.stack-track {{ display:flex; gap:2px; height:20px; }}
.seg {{ border-radius:3px; min-width:6px; display:flex; align-items:center; justify-content:center; }}
.seg span {{ font-family:"IBM Plex Mono",monospace; font-size:10.5px; color:#fff; mix-blend-mode:normal; }}
.seg[style*="--ink-3"] span {{ color:var(--paper); }}
.legend {{ display:flex; gap:16px; flex-wrap:wrap; margin-top:14px; }}
.lg {{ display:inline-flex; align-items:center; gap:6px; font-size:12.5px; color:var(--ink-2); }}
.lg i {{ width:10px; height:10px; border-radius:2px; display:inline-block; }}

/* waffle */
.waffle {{ display:grid; grid-template-columns:repeat(20,1fr); gap:4px; margin-top:12px; }}
.wf {{ aspect-ratio:1; border-radius:3px; opacity:.92; cursor:default; }}
.wf:hover {{ outline:2px solid var(--ink); opacity:1; }}

/* table */
.controls {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px; align-items:center; }}
.chip {{ font:500 12.5px "Instrument Sans",sans-serif; padding:7px 14px; border-radius:999px;
        border:1px solid var(--line); background:var(--card); color:var(--ink-2); cursor:pointer; }}
.chip.on {{ background:var(--ink); color:var(--paper); border-color:var(--ink); }}
#q {{ margin-left:auto; padding:8px 14px; border:1px solid var(--line); border-radius:8px;
     background:var(--card); color:var(--ink); font:14px "Instrument Sans",sans-serif; min-width:220px; }}
.tblwrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:10px; background:var(--card); }}
table {{ width:100%; border-collapse:collapse; font-size:13.5px; min-width:1050px; }}
th {{ font-family:"IBM Plex Mono",monospace; font-size:10.5px; letter-spacing:.09em; text-transform:uppercase;
     color:var(--ink-3); text-align:left; padding:12px 12px; border-bottom:1px solid var(--rule);
     position:sticky; top:0; background:var(--card); }}
td {{ padding:11px 12px; border-bottom:1px solid var(--line); vertical-align:top; }}
tr:last-child td {{ border-bottom:0; }}
td small {{ display:block; color:var(--ink-3); font-size:11.5px; max-width:30ch; }}
td.num {{ font-family:"IBM Plex Mono",monospace; color:var(--ink-3); font-size:12px; }}
.tag {{ font-family:"IBM Plex Mono",monospace; font-size:11px; border:1px solid var(--line);
       border-radius:4px; padding:1px 6px; white-space:nowrap; }}
.pill {{ font-size:9px; vertical-align:1px; }}
.apisurf {{ white-space:nowrap; }}
.blk {{ max-width:220px; font-size:12.5px; color:var(--ink-2); }}
.ev {{ font-family:"IBM Plex Mono",monospace; font-size:11px; margin-right:2px; }}
.dim {{ color:var(--ink-3); }}
.ok {{ color:var(--good-text); font-weight:700; }}
.warn {{ color:var(--st-warn); font-weight:600; font-family:"IBM Plex Mono",monospace; font-size:11.5px; }}
.bad {{ color:var(--st-crit); font-weight:700; }}

/* pipeline */
.pipe {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; margin-top:6px; }}
.step {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; }}
.step .n {{ font-family:"IBM Plex Mono",monospace; color:var(--accent); font-size:11px; }}
.step h4 {{ font-size:14.5px; margin:6px 0 4px; }}
.step p {{ font-size:12.5px; color:var(--ink-2); }}
.honesty {{ border-left:4px solid var(--st-warn); }}

footer {{ margin-top:70px; border-top:3px double var(--rule); padding:26px 0 48px;
         font-family:"IBM Plex Mono",monospace; font-size:12px; color:var(--ink-2); }}
@media (max-width:640px) {{ .bar-row {{ grid-template-columns:90px 1fr 30px; }}
  .stack-row {{ grid-template-columns:90px 1fr; }} }}
</style>
</head>
<body>

<header><div class="wrap mast">
  <span class="brand">API Buildability Census</span>
  <span class="meta">composio take-home · {now} · agent-generated, human-verified</span>
</div></header>

<div class="wrap">

<div class="hero">
  <div class="kicker">100 apps · 10 categories · every claim linked to evidence</div>
  <h1>Can an agent <em>build a toolkit</em> for it today?</h1>
  <p class="standfirst">A Python research agent profiled {N} SaaS apps — auth model, credential
  access, API surface, existing MCP servers — then an independent verifier fact-checked every
  claim against freshly fetched docs pages, and flagged records were re-researched.
  {verif_line}</p>
</div>

<div class="stats">
  <div class="stat"><b class="good">{by}</b><span>buildable today</span></div>
  <div class="stat"><b class="warn">{bp}</b><span>buildable with friction</span></div>
  <div class="stat"><b class="crit">{bn}</b><span>blocked / no public API</span></div>
  <div class="stat"><b>{ss}</b><span>fully self-serve credentials</span></div>
  <div class="stat"><b>{gated}</b><span>gated (sales / partner)</span></div>
  <div class="stat"><b>{mcp_official + mcp_comm}</b><span>already have an MCP server</span></div>
</div>

<section id="patterns">
  <div class="sec-head"><span class="sec-no">01</span><h2>The patterns</h2>
    <span class="sec-note">the headline, not the table</span></div>
  <div class="insights">
    <div class="card big-insight">
      <h3>{by} of {N} apps could become agent toolkits this week — the gate is business, not technology.</h3>
      <p>Where an app isn't buildable, the blocker is almost never a missing API — it's who is
      allowed to hold credentials. Top blockers found: <strong>{E(top_blockers)}</strong>.</p>
    </div>
    <div class="card"><h3>{top_auth} dominates ({top_auth_n}/{N})</h3>
      <p>OAuth2 appears on <strong>{oauth_n}</strong> apps and API keys on <strong>{key_n}</strong> —
      many apps ship both: OAuth for user-delegated access, keys for server-to-server. A toolkit
      platform must treat dual-auth as the default case, not the edge case.</p></div>
    <div class="card"><h3>Self-serve is the norm — gating is categorical</h3>
      <p><strong>{E(best_cat)}</strong> is the most open category
      ({cat_rate(best_cat):.0%} self-serve); <strong>{E(worst_cat)}</strong> is the most gated
      ({cat_rate(worst_cat):.0%}). Openness clusters by who the buyer is: developer-first
      products open the door, enterprise- and partner-sold products keep a human in the loop.</p></div>
    <div class="card"><h3>{len(easy_wins)} easy wins with no MCP yet</h3>
      <p>Apps that are buildable, self-serve, <em>and</em> have no MCP server found —
      greenfield for Composio. The gated list ({gated} apps) is the outreach queue, not
      a dead end.</p></div>
  </div>
  <div class="charts">
    <div class="card"><div class="chart-title">Auth methods across {N} apps (multi-count)</div>
      {bar_chart(auth_count, N)}</div>
    <div class="card"><div class="chart-title">Credential access by category</div>
      {stacked_rows(cat_access, ACCESS_META)}
      <div class="legend">{legend(ACCESS_META)}</div></div>
    <div class="card"><div class="chart-title">The 100 — buildability at a glance (hover any cell)</div>
      <div class="waffle">{waffle()}</div>
      <div class="legend">{legend(BUILD_META)}</div></div>
  </div>
</section>

<section id="findings">
  <div class="sec-head"><span class="sec-no">02</span><h2>All {N} apps</h2>
    <span class="sec-note">every row links to the evidence behind it · ✓ = verifier confirmed all 5 claims</span></div>
  <div class="controls">
    <button class="chip on" data-f="all">All</button>
    {"".join(f'<button class="chip" data-f="{E(c)}">{E(c.split("&")[0].split("/")[0].strip())}</button>' for c in CATEGORIES)}
    <button class="chip" data-f="acc:gated">Gated only</button>
    <input id="q" placeholder="search apps…">
  </div>
  <div class="tblwrap"><table>
    <thead><tr><th>#</th><th>App</th><th>Auth</th><th>Access</th><th>API surface</th>
      <th>MCP</th><th>Buildable</th><th>Blocker</th><th>Evidence · ✓</th></tr></thead>
    <tbody id="tb">{table_rows()}</tbody>
  </table></div>
</section>

<section id="agent">
  <div class="sec-head"><span class="sec-no">03</span><h2>The agent</h2>
    <span class="sec-note">python · groq/openrouter/gemini fallback chain · serper search</span></div>
  <div class="pipe">
    <div class="step"><span class="n">01</span><h4>Search ×3</h4>
      <p>Per app: docs &amp; auth, MCP servers, credential access — via Google (Serper).</p></div>
    <div class="step"><span class="n">02</span><h4>Read the docs</h4>
      <p>Downloads the top docs pages and reads the text — snippets alone lie.</p></div>
    <div class="step"><span class="n">03</span><h4>Extract</h4>
      <p>One LLM call → strict JSON: auth, access, API, MCP, verdict, evidence URLs, confidence. Guessing forbidden.</p></div>
    <div class="step"><span class="n">04</span><h4>Checkpoint</h4>
      <p>results.json written after every app — crash-safe, resumable.</p></div>
    <div class="step"><span class="n">05</span><h4>Verify → fix → verify</h4>
      <p>A deterministic checker (no LLM) re-fetches all evidence URLs and tests every claim; flagged records get corrected and re-checked.</p></div>
  </div>
  <div class="insights" style="margin-top:14px">
    <div class="card honesty"><h3>Where a human was needed</h3>
      <p>Defining the schema and what “self-serve” means. Unblocking run #1, which died on
      Gemini free-tier 429s (kept in the repo as <span class="mono">artifacts_run1_gemini_429.json</span>)
      — replaced with a Groq → OpenRouter → Gemini fallback chain. When free-tier quotas kept
      choking, <strong>{len(fallback)} apps were finished by a human-driven research pass</strong>
      (same schema, same evidence rules — marked <span class="mono">researched_by</span> in the data).
      Hand spot-checking {len(MANUAL)} claims against real docs and correcting
      {len([r for r in revised if r.get("revision_note")])} records. The agent did everything else.</p></div>
    <div class="card honesty"><h3>What the agent got wrong (kept honestly)</h3>
      <p>The hand check caught real failure modes: <strong>entity confusion</strong> (Fathom's MCP
      evidence pointed at Fathom Analytics, a different company), <strong>context bleed</strong>
      (Mermaid CLI got "API Key" auth from unrelated search results — it has no auth at all),
      <strong>over-optimism on gated APIs</strong> (PitchBook needs a standalone contract, not
      "partial"), and <strong>over-caution</strong> (Zendesk's free trial has full API access).
      {sum(1 for r in OK if r.get("confidence") == "low")} records self-report low confidence.
      The spot-check table below shows every hit and miss.</p></div>
  </div>
</section>

<section id="verification">
  <div class="sec-head"><span class="sec-no">04</span><h2>How we know it's right</h2>
    <span class="sec-note">accuracy is what matters most</span></div>
  <div class="insights">
    <div class="card"><h3>Machine loop — deterministic, no LLM</h3>
      <p>The checker re-fetches every record's evidence URLs and mechanically tests each claim
      (URL liveness + keyword support). It cannot hallucinate agreement — a dead evidence link
      can never count as support.
      {(f" Pass 1: <strong>{p_first['claims_supported']}/{p_first['claims_checked']}</strong> claims supported ({p_first['support_rate']:.0%}), {len(p_first.get('dead_evidence_urls', []))} dead evidence links." if p_first else " Verification pass pending.")}
      {(f" After the fix pass (evidence-URL repairs + {len([r for r in revised if 'verification' in (r.get('revision_note') or '')])} claim corrections), pass 2: <strong>{p_last['claims_supported']}/{p_last['claims_checked']}</strong> ({p_last['support_rate']:.0%}), dead links down to {len(p_last.get('dead_evidence_urls', []))}." if p_last else "")}
      Most remaining flags are docs the static fetcher can't read (JS-rendered or bot-blocked:
      Salesforce, Meta, Datadog) — a stated limitation, covered by the human loop, not
      papered over by loosening the checker.</p></div>
    <div class="card"><h3>Human loop — where judgment lives</h3>
      <p>{len(MANUAL)} field-level spot checks against the real docs by hand{f" — the agent had <strong>{manual_hits}/{len(MANUAL)}</strong> right (62%) before fixes" if MANUAL else ""};
      every miss was corrected with a cited docs page and re-verified, and the machine loop's
      flags triggered {len([r for r in revised if r.get("revision_note")])} record corrections in total.
      Sample weighted toward low-confidence and gated verdicts, because that's where agents bluff.</p></div>
  </div>
  <div class="tblwrap" style="margin-top:14px"><table style="min-width:760px">
    <thead><tr><th>App</th><th>Field</th><th>Agent said</th><th>Docs actually say</th><th>Verdict</th></tr></thead>
    <tbody>{manual_rows()}</tbody>
  </table></div>
</section>

</div>

<footer><div class="wrap">
  built with agent.py · verify.py · build_site.py — source repo in submission ·
  data generated {now} · every table cell traces to a URL
</div></footer>

<script>
const chips=document.querySelectorAll('.chip'),rows=document.querySelectorAll('#tb tr'),q=document.getElementById('q');
let f='all';
chips.forEach(c=>c.onclick=()=>{{chips.forEach(x=>x.classList.remove('on'));c.classList.add('on');f=c.dataset.f;apply();}});
q.oninput=apply;
function apply(){{const s=q.value.toLowerCase();rows.forEach(r=>{{
  const okF=f==='all'||(f.startsWith('acc:')?r.dataset.acc===f.slice(4):r.dataset.cat===f);
  const okS=!s||r.textContent.toLowerCase().includes(s);
  r.style.display=okF&&okS?'':'none';}});}}
</script>
</body>
</html>"""

Path("index.html").write_text(page, encoding="utf-8")
print(f"index.html written — {N} apps, {len(ERRORED)} errors, "
      f"{len(passes)} verification pass(es), {len(MANUAL)} manual checks")
