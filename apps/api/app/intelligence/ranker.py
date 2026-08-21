"""RecommendationRanker: a deterministic, reproducible score. The weights live
here as configuration; the same inputs always produce the same score, and the
full component breakdown ships with every recommendation so the ranking can be
audited. The LLM explains scores — it never sets them."""
from __future__ import annotations

WEIGHTS = {
    "skillOverlap": 0.25,
    "marketDemand": 0.20,
    "yoyGrowth": 0.15,
    "aiLeverage": 0.15,
    "humanAdvantage": 0.10,
    "transitionFeasibility": 0.10,
    "economic": 0.05,
}

_DIFFICULTY = {"low": 1.0, "medium": 0.65, "high": 0.35, "very high": 0.15}


def components(match: dict, impact_read: dict, demand: dict, live: dict) -> dict:
    """Each component normalized to 0..1 from actual computed inputs. A
    component without evidence contributes 0 and says so — it never borrows a
    made-up middle value."""
    sig = demand.get("officialSignal") or {}
    market_demand = 0.0
    if sig.get("confidence", 0) >= 0.4:
        market_demand = float(sig["value"])
    elif demand.get("livePostings", 0) >= 20:
        market_demand = 0.5
    elif demand.get("livePostings", 0) >= 5:
        market_demand = 0.3

    yoy = 0.0
    yoy_known = False
    for entry in (live.get("windows") or {}).values():
        if entry.get("state") == "ok":
            yoy = max(yoy, min(1.0, 0.5 + entry["pct"] / 100))
            yoy_known = True
    if not yoy_known:
        # official projection growth stands in when live history is absent
        for e in (demand.get("officialGrowthPcts") or []):
            yoy = max(yoy, min(1.0, 0.5 + e / 100))
            yoy_known = True

    salary = live.get("salary") or {}
    economic = 0.0
    if salary.get("median"):
        economic = min(1.0, float(salary["median"]) / 150000)

    return {
        "skillOverlap": float(match.get("overall") or 0),
        "marketDemand": round(market_demand, 3),
        "yoyGrowth": round(yoy, 3) if yoy_known else 0.0,
        "yoyKnown": yoy_known,
        "aiLeverage": float(impact_read.get("aiLeverage") or 0),
        "humanAdvantage": float(impact_read.get("humanAdvantage") or 0),
        "transitionFeasibility": _DIFFICULTY.get(match.get("transitionDifficulty"), 0.35),
        "economic": round(economic, 3),
        "economicKnown": bool(salary.get("median")),
    }


def score(comps: dict, weights: dict | None = None) -> dict:
    w = weights or WEIGHTS
    total = sum(w[k] * float(comps.get(k) or 0) for k in w)
    return {"score": round(total * 100),
            "weights": w,
            "components": {k: comps.get(k) for k in w},
            "notes": [n for n in (
                None if comps.get("yoyKnown") else "growth component: insufficient historical data",
                None if comps.get("economicKnown") else "economic component: no salary evidence",
            ) if n]}
