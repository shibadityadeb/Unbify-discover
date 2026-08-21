"""The orchestrator: questionnaire → capability profile → candidate discovery
→ live + official market evidence → skill overlap → AI impact → deterministic
ranking → explanation. Cached per session against the profile hash, recomputed
when answers change or market evidence goes stale."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import DiscoverSession, DiscoveryCache
from . import candidates as cand_svc
from . import evidence as evidence_svc
from . import explain as explain_svc
from . import impact as impact_svc
from . import market
from . import matcher
from . import profile as profile_svc
from . import queries as query_svc
from . import ranker

RECOMMENDATION_TTL_HOURS = 24
MAX_LIVE_QUERIES = 6          # cost control: per recompute, not per page view


def _cached(db: Session, session: DiscoverSession, h: str) -> dict | None:
    row = (db.query(DiscoveryCache)
           .filter_by(session_id=session.id, kind="recommendations", profile_hash=h)
           .order_by(DiscoveryCache.created_at.desc()).first())
    if not row:
        return None
    age_h = (datetime.utcnow() - row.created_at).total_seconds() / 3600
    if age_h > RECOMMENDATION_TTL_HOURS:
        return None
    payload = dict(row.payload)
    payload["cache"] = {"hit": True, "ageHours": round(age_h, 1)}
    return payload


def run(db: Session, session: DiscoverSession, force: bool = False) -> dict:
    prof_payload = profile_svc.extract(db, session)
    h = prof_payload["profileHash"]
    if not force:
        hit = _cached(db, session, h)
        if hit:
            return hit

    profile = prof_payload["profile"]
    gen = cand_svc.generate(db, session, prof_payload)
    geography = (profile.get("location") or "").strip() or "*"
    qs = query_svc.generate(profile, gen["candidates"], geography)

    # live market sweep, bounded by query count AND wall clock — a recompute
    # happens at most daily per profile, but must never hang the request
    import time as _time
    live_runs = []
    live_ok, live_why = market.live_available(db)
    if live_ok:
        sweep_deadline = _time.monotonic() + 75
        for q in qs["queries"][:MAX_LIVE_QUERIES]:
            if _time.monotonic() >= sweep_deadline:
                live_runs.append({"query": q, "ok": False, "skipped": True,
                                  "why": "sweep time budget exhausted"})
                continue
            live_runs.append({"query": q, **market.search(db, q, geography)})

    user_caps = profile_svc.capability_names(profile)
    recs = []
    for c in gen["candidates"]:
        match = matcher.overlap(user_caps, c["requiredCapabilities"])
        impact_read = impact_svc.analyze(db, c)
        official = evidence_svc.official_evidence(db, c["title"])
        cand_queries = (c.get("searchTerms") or [])[:3] or [c["title"].lower()]
        live = evidence_svc.live_evidence(db, c["title"], cand_queries, geography)
        demand = evidence_svc.demand_summary(official, live)
        demand["officialGrowthPcts"] = [
            float(str(e["value"]).strip("+%")) for e in official["entries"]
            if e.get("metric") == "employment growth projection"
            and str(e.get("value", "")).strip("+%").replace(".", "", 1).isdigit()]
        comps = ranker.components(match, impact_read, demand, live)
        scored = ranker.score(comps)
        evidence_entries = official["entries"] + live["entries"]
        rec = {
            "title": c["title"], "type": c["type"],
            "whyFromProfile": c["whyFromProfile"],
            "steps": c.get("steps") or [],
            "score": scored["score"],
            "scoreBreakdown": scored,
            "skillOverlap": match,
            "impact": impact_read,
            "demand": {k: v for k, v in demand.items() if k != "officialGrowthPcts"},
            "salary": live.get("salary"),
            "evidence": evidence_entries,
            "evidenceState": evidence_svc.confidence_state(official, live),
        }
        recs.append(rec)

    recs.sort(key=lambda r: -r["score"])
    # model-written explanations only for the top of the list — the fallback
    # composition covers the tail, and a page must not wait on a dozen calls
    for i, rec in enumerate(recs):
        rec["explanation"] = (explain_svc.explain(db, rec) if i < 5
                              else explain_svc._fallback(rec))
    emerging = market.emerging_clusters(db) if live_ok else []
    payload = {
        "profile": {
            "capabilities": profile.get("capabilities", []),
            "currentOccupation": profile.get("current_occupation"),
            "industries": profile.get("industry", []),
            "location": profile.get("location"),
            "entrepreneurialIntent": profile.get("entrepreneurial_intent"),
            "aiOnYourWork": {
                "augments": profile.get("ai_augments", []),
                "automates": profile.get("ai_automates", []),
                "humanEssential": profile.get("human_essential", []),
            },
            "basis": prof_payload["basis"],
        },
        "recommendations": recs,
        "emergingClusters": emerging,
        "meta": {
            "profileHash": h,
            "candidateBasis": gen["basis"],
            "geography": geography,
            "queries": qs["queries"],
            "liveMarket": ({"enabled": True, "runs": live_runs} if live_ok
                           else {"enabled": False, "why": live_why}),
            "weights": ranker.WEIGHTS,
            "computedAt": datetime.utcnow().isoformat() + "Z",
        },
        "cache": {"hit": False},
    }
    db.add(DiscoveryCache(session_id=session.id, kind="recommendations",
                          profile_hash=h, payload=payload))
    db.flush()
    return payload
