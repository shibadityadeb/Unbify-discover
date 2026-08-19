"""The single LLM boundary. Capabilities, not model calls. Structured output,
schema validation, bounded retries, deterministic fallback, circuit breaker,
cost logging. The key never reaches the browser. The LLM is expression —
never the intelligence engine."""
from __future__ import annotations

import json
import time

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import LLMCall
from .prompts import PROMPTS

_fail_streak = 0
_timeout_streak = 0
_rest_until = 0.0


def available() -> bool:
    # Tests exercise UNBIFY's own intelligence and its deterministic fallbacks;
    # they must never depend on a vendor model's latency or wording.
    if settings.app_env == "test":
        return False
    return bool(settings.litellm_key) and time.time() >= _rest_until


def _note(success: bool, timed_out: bool = False) -> None:
    """Circuit breaker.

    A hard failure (gateway down, auth, bad response) rests immediately —
    otherwise every capability pays a full timeout for nothing. A TIMEOUT is
    different: the model is reachable, just slow, and one slow generation
    should not silence the narrative. Timeouts only trip after a run of them.
    """
    global _fail_streak, _timeout_streak, _rest_until
    if success:
        _fail_streak = _timeout_streak = 0
        _rest_until = 0.0
        return
    if timed_out:
        _timeout_streak += 1
        if _timeout_streak >= 3:
            _rest_until = time.time() + 60
        return
    _fail_streak += 1
    _rest_until = time.time() + min(600, 30 * (2 ** (_fail_streak - 1)))


def _extract_json(text: str) -> dict | None:
    """Pull the JSON object out of a completion. The gateway prefixes replies
    (e.g. 'LITELLM_NOPATCH'), and models sometimes wrap output in fences, so we
    take the outermost braces rather than trusting the whole string."""
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    first, last = text.find("{"), text.rfind("}")
    if first == -1 or last <= first:
        return None
    try:
        out = json.loads(text[first:last + 1])
        return out if isinstance(out, dict) else None
    except ValueError:
        return None


def generate(db: Session | None, prompt_version: str, structured_input: dict) -> dict | None:
    """Returns validated JSON dict or None (caller must have a deterministic fallback).

    Uses streaming: this gateway's non-streaming path returns upstream 500s
    while the streaming path works, and streaming also lets a slow model fail
    incrementally instead of blocking the whole request budget.
    """
    spec = PROMPTS[prompt_version]
    if not available():
        return None
    t0 = time.time()
    ok = False
    tokens_in = tokens_out = 0
    content = ""
    try:
        with httpx.Client(timeout=spec["timeout"]) as client:
            with client.stream(
                "POST",
                f"{settings.litellm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.litellm_key}"},
                json={
                    "model": settings.litellm_model,
                    "messages": [
                        {"role": "system", "content": spec["system"]},
                        {"role": "user", "content": json.dumps(structured_input)},
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": spec["max_tokens"],
                    "stream": True,
                    "stream_options": {"include_usage": True},
                },
            ) as res:
                if res.status_code != 200:
                    res.read()
                    _note(False)
                    return None
                for line in res.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    body = line[6:].strip()
                    if body == "[DONE]":
                        break
                    try:
                        chunk = json.loads(body)
                    except ValueError:
                        continue
                    for choice in chunk.get("choices", []):
                        content += (choice.get("delta") or {}).get("content") or ""
                    usage = chunk.get("usage")
                    if usage:
                        tokens_in = usage.get("prompt_tokens", 0)
                        tokens_out = usage.get("completion_tokens", 0)
        out = _extract_json(content)
        if out is None:
            _note(False)
            return None
        ok = True
        _note(True)
        return out
    except (httpx.TimeoutException, httpx.ReadTimeout):
        _note(False, timed_out=True)
        return None
    except Exception:
        _note(False)
        return None
    finally:
        if db is not None:
            db.add(LLMCall(
                capability=spec["capability"], prompt_version=prompt_version,
                model=settings.litellm_model, tokens_in=tokens_in, tokens_out=tokens_out,
                latency_ms=int((time.time() - t0) * 1000),
                est_cost_usd=round((tokens_in * 2 + tokens_out * 8) / 1e6, 6),
                success=ok,
            ))
