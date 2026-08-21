"""SkillMatcher: the user's actual capabilities vs an opportunity's required
capabilities. Produces per-capability overlap, an overall score, named gaps,
and a transition-difficulty read — so the product can say "you already hold
72% of this; the largest gap is X" instead of "become X"."""
from __future__ import annotations

import re

_SYNONYMS = {
    "coding": "software construction", "programming": "software construction",
    "software development": "software construction", "development": "software construction",
    "communication": "stakeholder communication",
    "ml": "machine learning", "ai": "ai tools",
}


def _norm(s: str) -> str:
    s = re.sub(r"[^\w\s]", " ", (s or "").lower().replace("_", " "))
    s = " ".join(s.split())
    return _SYNONYMS.get(s, s)


def _tokens(s: str) -> set[str]:
    return set(_norm(s).split())


def _similarity(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.85
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    jac = len(ta & tb) / len(ta | tb)
    return round(jac, 2)


def overlap(user_capabilities: list[str], required: list[str]) -> dict:
    """Per-required-capability best match against what the user holds."""
    per = []
    for req in required:
        best, best_cap = 0.0, None
        for cap in user_capabilities:
            s = _similarity(cap, req)
            if s > best:
                best, best_cap = s, cap
        per.append({"capability": req, "match": round(best, 2),
                    "matchedFrom": best_cap if best >= 0.4 else None})
    matched = [p for p in per if p["match"] >= 0.75]
    transferable = [p for p in per if 0.4 <= p["match"] < 0.75]
    gaps = [p for p in per if p["match"] < 0.4]
    overall = round(sum(p["match"] for p in per) / len(per), 2) if per else 0.0
    difficulty = ("low" if overall >= 0.7 and len(gaps) <= 1 else
                  "medium" if overall >= 0.45 else
                  "high" if overall >= 0.25 else "very high")
    return {
        "overall": overall,
        "perCapability": per,
        "have": [p["capability"] for p in matched],
        "transferable": [p["capability"] for p in transferable],
        "gaps": [p["capability"] for p in gaps],
        "largestGap": gaps[0]["capability"] if gaps else None,
        "transitionDifficulty": difficulty,
    }
