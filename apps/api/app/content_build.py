"""Content build stamp for session-cached payloads.

Chapter closings, the alignment map and the whole materialization page are
composed once and cached on the session (`_closing_cache`, `_lives`,
`_materialization`). Those caches were keyed only on the journey state, which
holds exactly until the composition code changes — after that a returning
session is served a payload built by code that no longer exists, forever, with
nothing visible from the outside to say so. Refreshing doesn't help; the cache
is the thing being refreshed.

Every cached payload now carries this stamp and is rebuilt when it doesn't
match. Bump it whenever composition changes shape.
"""
from __future__ import annotations

CONTENT_BUILD = "2026-08-19.operator-branch"


def stamped(payload: dict) -> dict:
    """Wrap a freshly composed payload with the build that produced it."""
    return {"build": CONTENT_BUILD, "payload": payload}


def fresh(cache: dict | None) -> dict | None:
    """Return the cached payload only if this build composed it.

    Anything without a stamp predates versioning and is treated as stale, so
    sessions created before this change heal themselves on the next request
    rather than needing to be deleted by hand.
    """
    if not isinstance(cache, dict):
        return None
    if cache.get("build") != CONTENT_BUILD:
        return None
    payload = cache.get("payload")
    return payload if isinstance(payload, dict) else None
