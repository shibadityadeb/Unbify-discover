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
_rest_until = 0.0


def available() -> bool:
    return bool(settings.litellm_key) and time.time() >= _rest_until


def _note(success: bool) -> None:
    global _fail_streak, _rest_until
    if success:
        _fail_streak = 0
    else:
        _fail_streak += 1
        if _fail_streak >= 2:
            _rest_until = time.time() + 240


def generate(db: Session | None, prompt_version: str, structured_input: dict) -> dict | None:
    """Returns validated JSON dict or None (caller must have a deterministic fallback)."""
    spec = PROMPTS[prompt_version]
    if not available():
        return None
    t0 = time.time()
    ok = False
    tokens_in = tokens_out = 0
    try:
        with httpx.Client(timeout=spec["timeout"]) as client:
            res = client.post(
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
                },
            )
        if res.status_code != 200:
            _note(False)
            return None
        data = res.json()
        usage = data.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
        content = data["choices"][0]["message"]["content"]
        out = json.loads(content)
        ok = True
        _note(True)
        return out
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
