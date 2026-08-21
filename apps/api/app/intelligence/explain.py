"""RecommendationExplainer: words for numbers that already exist. The LLM
restates the computed score, overlap and evidence in plain language; the
fallback composes the same explanation directly from the data. Neither path
may introduce a number the pipeline did not compute."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..llm import gateway


def _fallback(rec: dict) -> dict:
    match = rec.get("skillOverlap") or {}
    have = ", ".join((match.get("have") or match.get("transferable") or [])[:3])
    gap = match.get("largestGap")
    demand = rec.get("demand") or {}
    ev = rec.get("evidence") or []
    market_bits = []
    if demand.get("direction") not in (None, "unknown"):
        market_bits.append(f"official readings put demand {demand['direction']}")
    if demand.get("livePostings"):
        market_bits.append(f"{demand['livePostings']} live postings observed")
    return {
        "whyFitsYou": (f"You already hold {int((match.get('overall') or 0) * 100)}% of what this "
                       f"needs{' — notably ' + have if have else ''}."),
        "whatToLearn": (f"The largest gap is {gap}." if gap
                        else "No major capability gap showed up against your profile."),
        "whyMarketMoves": ("; ".join(market_bits).capitalize() + "."
                           if market_bits else
                           "Market evidence is currently insufficient — treat this as a "
                           "capability match, not a demand claim."),
        "firstStep": (f"Spend two hours this week closing the {gap} gap on a real example "
                      f"of your own work." if gap else
                      "Give this two honest hours this week: sketch the first concrete step."),
        "basis": "deterministic_fallback",
        "evidenceSources": sorted({e.get("source") for e in ev if e.get("source")}),
    }


def explain(db: Session, rec: dict) -> dict:
    out = gateway.generate(db, "recommendation_explain_v1", {
        "title": rec.get("title"), "type": rec.get("type"),
        "score": rec.get("score"), "skillOverlap": rec.get("skillOverlap"),
        "impact": rec.get("impact"), "demand": rec.get("demand"),
        "evidence": rec.get("evidence"),
    })
    fb = _fallback(rec)
    if out and out.get("whyFitsYou"):
        return {**fb, **{k: str(out.get(k))[:400] for k in
                         ("whyFitsYou", "whatToLearn", "whyMarketMoves", "firstStep")
                         if out.get(k)}, "basis": "llm"}
    return fb
