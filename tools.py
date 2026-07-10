"""
Research tools: web search (Serper.dev) and web page fetching.

The agent doesn't reason over search snippets alone — for each app it also
downloads the top developer-docs pages and reads the actual text. Snippets
say "X has an API"; only the page says whether the OAuth app needs review.
"""

import html
import json
import re

import requests
from dotenv import load_dotenv
import os

load_dotenv()
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "").strip().strip('"')

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Domains that are never developer docs — skip when picking pages to fetch.
SKIP_DOMAINS = ("youtube.com", "reddit.com", "linkedin.com/posts", "twitter.com",
                "x.com/", "facebook.com/", "medium.com", "quora.com", "g2.com",
                "capterra.com", "wikipedia.org")


def search(query: str, num: int = 6) -> list[dict]:
    """Google search via Serper. Returns [{title, link, snippet}]."""
    if not SERPER_API_KEY:
        raise RuntimeError("SERPER_API_KEY missing from .env")
    r = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
        json={"q": query, "num": num},
        timeout=15,
    )
    if r.status_code == 400 and '"' in query:
        # Serper rejects some quoted phrases (e.g. quoted dotted domains like
        # "systeme.io") — retry unquoted.
        return search(query.replace('"', ""), num)
    r.raise_for_status()
    return [
        {"title": o.get("title", ""), "link": o.get("link", ""),
         "snippet": o.get("snippet", "")}
        for o in r.json().get("organic", [])[:num]
    ]


def strip_html(raw: str) -> str:
    """Crude but dependency-free HTML -> text."""
    raw = re.sub(r"<(script|style|noscript|svg|nav|footer)[^>]*>.*?</\1>", " ",
                 raw, flags=re.S | re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", " ", raw).strip()


def fetch_page(url: str, max_chars: int = 5000) -> str:
    """Download a page and return readable text (empty string on failure)."""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20,
                         allow_redirects=True)
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", "text/html"):
            return ""
        return strip_html(r.text)[:max_chars]
    except Exception:
        return ""


def pick_docs_links(results: list[dict], limit: int = 2) -> list[str]:
    """Choose the most docs-like links from search results."""
    def score(r):
        link = r["link"].lower()
        s = 0
        if any(k in link for k in ("docs.", "developer", "developers.", "/docs", "/api",
                                   "api.", "/developer", "reference")):
            s += 2
        if any(d in link for d in SKIP_DOMAINS):
            s -= 5
        return -s  # sort ascending

    ranked = sorted(results, key=score)
    out = []
    for r in ranked:
        if len(out) >= limit:
            break
        if r["link"] and not any(d in r["link"].lower() for d in SKIP_DOMAINS):
            out.append(r["link"])
    return out


def format_results(results: list[dict]) -> str:
    return "\n".join(f"- {r['title']} ({r['link']}): {r['snippet']}" for r in results)
