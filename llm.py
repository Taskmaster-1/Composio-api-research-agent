"""
LLM client with a provider fallback chain.

Providers are tried in order: Groq -> OpenRouter -> Gemini.
Whichever API keys exist in .env are used. On a 429 (rate limit) the client
backs off and retries; if a provider's quota is exhausted it moves to the
next model, then the next provider. This exists because run #1 of this
project died on Gemini free-tier 429s.
"""

import json
import os
import re
import time

import requests
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY       = os.getenv("GROQ_API_KEY", "").strip().strip('"')
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip().strip('"')
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY", "").strip().strip('"')

# (provider, model) pairs, tried in order.
CHAIN = []
if GROQ_API_KEY:
    CHAIN += [
        ("groq", "llama-3.3-70b-versatile"),
        ("groq", "openai/gpt-oss-120b"),
        ("groq", "llama-3.1-8b-instant"),
    ]
if OPENROUTER_API_KEY:
    CHAIN += [
        ("openrouter", os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")),
        ("openrouter", "openai/gpt-oss-120b:free"),
        ("openrouter", "qwen/qwen3-next-80b-a3b-instruct:free"),
        ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free"),
    ]
if GEMINI_API_KEY:
    CHAIN += [("gemini", "gemini-2.0-flash-lite")]

# Models that burned all their rate-limit retries cool down for a while
# instead of being parked forever — per-minute windows recover mid-run.
COOLDOWN_S = 120
_cooldown = {}  # (provider, model) -> unix time when usable again

# Simple usage counter so the run can report which models did the work.
usage = {}


def _openai_compatible(base_url, key, model, prompt, max_tokens):
    r = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": max_tokens,
        },
        timeout=90,
    )
    if r.status_code == 429:
        raise RateLimited(r.headers.get("retry-after"))
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _gemini(key, model, prompt, max_tokens):
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": max_tokens},
        },
        timeout=90,
    )
    if r.status_code == 429:
        raise RateLimited(None)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


class RateLimited(Exception):
    def __init__(self, retry_after):
        self.retry_after = retry_after


def chat(prompt: str, max_tokens: int = 1024) -> str:
    """Call the first working (provider, model) in the chain."""
    if not CHAIN:
        raise RuntimeError(
            "No LLM API key found. Put GROQ_API_KEY or OPENROUTER_API_KEY "
            "(or GEMINI_API_KEY) in .env"
        )
    last_err = None
    for provider, model in CHAIN:
        if _cooldown.get((provider, model), 0) > time.time():
            continue
        for attempt in range(2):
            try:
                if provider == "groq":
                    out = _openai_compatible("https://api.groq.com/openai/v1",
                                             GROQ_API_KEY, model, prompt, max_tokens)
                elif provider == "openrouter":
                    out = _openai_compatible("https://openrouter.ai/api/v1",
                                             OPENROUTER_API_KEY, model, prompt, max_tokens)
                else:
                    out = _gemini(GEMINI_API_KEY, model, prompt, max_tokens)
                usage[f"{provider}/{model}"] = usage.get(f"{provider}/{model}", 0) + 1
                return out
            except RateLimited as e:
                wait = float(e.retry_after) if e.retry_after else 5 * (2 ** attempt)
                wait = min(wait, 25)  # long waits: cheaper to fail over down the chain
                print(f"    [429] {provider}/{model} rate limited, waiting {wait:.0f}s "
                      f"(attempt {attempt + 1}/2)")
                time.sleep(wait)
                last_err = e
            except Exception as e:
                print(f"    [ERR] {provider}/{model}: {e}")
                last_err = e
                break  # non-429 error: try next model
        else:
            # 3 rate-limit retries burned: cool this model down, move on
            print(f"    [COOL] {provider}/{model} cooling down {COOLDOWN_S}s")
            _cooldown[(provider, model)] = time.time() + COOLDOWN_S
            continue
    raise RuntimeError(f"All LLM providers failed. Last error: {last_err!r}")


def _parse_json(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, re.S)
        if not m:
            raise
        block = m.group()
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            # common LLM slips: trailing commas before } or ]
            return json.loads(re.sub(r",\s*([}\]])", r"\1", block))


def chat_json(prompt: str, max_tokens: int = 1800) -> dict:
    """chat() + robust JSON parsing, with one repair round-trip on failure."""
    raw = chat(prompt, max_tokens)
    try:
        return _parse_json(raw)
    except json.JSONDecodeError:
        repaired = chat(
            "Fix this into strictly valid JSON. Return ONLY the corrected JSON, "
            "complete and nothing else:\n\n" + raw,
            max_tokens,
        )
        try:
            return _parse_json(repaired)
        except json.JSONDecodeError:
            raise ValueError(f"LLM did not return JSON: {raw[:200]}")
