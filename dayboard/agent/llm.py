"""Provider-agnostic LLM client.

One function, complete(), that returns text for a prompt. Which backend it uses
is decided by environment variables, so swapping Gemini for another model is a
config change, not a code change. If no key is configured, callers fall back to
the deterministic logic in rules.py - that is what keeps the public demo free
and always-working.
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error


class LLMUnavailable(Exception):
    """Raised when no LLM is configured or the call fails. Callers catch this
    and fall back to deterministic logic."""


def is_configured() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def complete(prompt: str, *, temperature: float = 0.2, timeout: int = 30) -> str:
    """Return the model's text response to prompt. Raises LLMUnavailable on any
    problem so the caller can fall back cleanly."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise LLMUnavailable("no GEMINI_API_KEY set")

    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["candidates"][0]["content"]["parts"][0]["text"]
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as exc:
        raise LLMUnavailable(str(exc)) from exc


def complete_json(prompt: str, **kwargs) -> dict | list:
    """complete(), but parse the result as JSON. Strips a ```json fence if the
    model wraps its output in one (common with Gemini)."""
    raw = complete(prompt, **kwargs).strip()
    if raw.startswith("```"):
        # drop the first fence line and any trailing fence
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"model did not return valid JSON: {exc}") from exc
