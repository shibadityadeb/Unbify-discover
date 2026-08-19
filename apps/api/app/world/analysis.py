"""Real-time recommendation pipeline.

USER ACTION → latest human profile → professional state → intent →
relevant world scope → freshness + coverage check →
    sufficient?  rank now
    stale/thin?  targeted refresh, then rerank →
versioned analysis.

The recommendation is always COMPUTED at request time from the latest
versions available at that moment. Nothing is served from a pre-baked answer,
and a stale world is never presented as a live one.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import (AnalysisVersion, DiscoverSession, ProfileVersion,
                      RecommendationItem, WIMarketSignal)
from . import matching, refresh, signals

ANALYSIS_VERSION = "analysis_v1"

# what each user-facing action actually needs from the world
ACTION_INTENT = {
    "explore_opportunities": "explore_opportunities",
    "analyze_position": "analyze_position",
    "whats_changing": "whats_changing",
    "active_now": "active_now",
    "independent_work": "independent_work",
    "build_something": "build_something",
    "transfer": "transfer",
    "qualification": "qualification",
    "compare": "explore_opportunities",
}

# user intent reshapes ranking — the same human asking different questions
# gets different candidates (§44/§67)
INTENT_TO_RANKING = {
    "independent_work": "build", "build_something": "build",
    "active_now": "max_income", "explore_opportunities": None,
    "analyze_position": "stability", "transfer": None,
    "whats_changing": None, "qualification": None,
}


def latest_profile_version(db: Session, session: DiscoverSession) -> ProfileVersion | None:
    return (db.query(ProfileVersion).filter_by(session_id=session.id)
            .order_by(ProfileVersion.created_at.desc()).first())


def _market_snapshot_version(db: Session, occupation_id: str | None) -> str | None:
    if not occupation_id:
        return None
    sig = (db.query(WIMarketSignal).filter_by(occupation_id=occupation_id)
           .order_by(WIMarketSignal.updated_at.desc()).first())
    return sig.snapshot_version if sig else None


def _describe_freshness(assessment: dict) -> dict:
    """Per-signal freshness surfaced honestly — never one fake timestamp."""
    out = {"state": assessment["state"], "coverage": assessment["coverage"], "signals": {}}
    for construct, f in (assessment.get("signalFreshness") or {}).items():
        out["signals"][construct] = {
            "present": f["present"],
            "ageHours": f.get("ageHours"),
            "stale": f["stale"],
            "label": ("missing" if not f["present"] else
                      "stale" if f["stale"] else
                      f"refreshed {int((f.get('ageHours') or 0) // 24)}d ago"
                      if (f.get("ageHours") or 0) >= 24 else "refreshed today"),
        }
    return out


def _diff(previous: AnalysisVersion | None, directions: list[dict]) -> str | None:
    """§51 — never silently swap conclusions underneath the user."""
    if not previous:
        return None
    old = [d.get("key") for d in (previous.payload or {}).get("directions", [])]
    new = [d.get("key") for d in directions]
    if old == new:
        return None
    appeared = [k for k in new if k not in old]
    gone = [k for k in old if k not in new]
    if not appeared and not gone:
        return "The current market evidence changed the order of these slightly."
    bits = []
    if appeared:
        bits.append(f"{len(appeared)} direction{'s' if len(appeared) > 1 else ''} appeared")
    if gone:
        bits.append(f"{len(gone)} dropped out")
    return "The current market evidence changed this: " + " and ".join(bits) + "."


def analyze(db: Session, session: DiscoverSession, action: str,
            intent_overrides: dict | None = None,
            refresh_preference: str = "live_if_needed",
            geography: str | None = None) -> dict:
    """The real-time pipeline. Returns a response with status complete |
    refreshing, always carrying whatever is genuinely supported right now."""
    intent = ACTION_INTENT.get(action, "explore_opportunities")
    overrides = intent_overrides or {}
    geo = geography or (session.practical_context or {}).get("geography") or "*"

    # 1. relevant world scope, built by UNBIFY from the latest human state
    scope = refresh.build_query_scope(db, session, intent, geo)
    # 2. what do we actually know, per signal
    assessment = refresh.assess(db, scope)
    # 3. refresh only the slice this request needs, only if it needs it
    allow = refresh_preference in ("live_if_needed", "force")
    if refresh_preference == "force":
        assessment = {**assessment, "state": "STALE_BUT_USABLE"}
    depth = "deep" if assessment["coverage"] < 0.2 else "fast"
    assessment = refresh.ensure_fresh(db, scope, assessment, depth=depth, allow_refresh=allow)

    # 4. rank from the best evidence available RIGHT NOW (never block on scraping)
    ranking_intent = overrides.get("ranking") or INTENT_TO_RANKING.get(intent)
    from ..materialization import directions as build_directions
    directions = build_directions(db, session)
    if ranking_intent:
        gen = matching.generate_candidates(db, session, geo)
        if gen["status"] == "ok":
            ranked = matching.rank(gen["candidates"], session, ranking_intent)[:3]
            keys = [f"world_{(c['occupationId'] or c.get('problemId'))}_{c['pathway']}"[:60]
                    for c in ranked]
            order = {k: i for i, k in enumerate(keys)}
            directions.sort(key=lambda d: order.get(d["key"], 99))

    pv = latest_profile_version(db, session)
    snapshot_version = _market_snapshot_version(db, scope.get("occupationId"))
    previous = (db.query(AnalysisVersion)
                .filter_by(session_id=session.id, action=action)
                .order_by(AnalysisVersion.created_at.desc()).first())
    change = _diff(previous, directions)

    payload = {
        "action": action,
        "intent": {"kind": intent, **overrides},
        "directions": directions,
        "marketFreshness": _describe_freshness(assessment),
        "worldEvidenceNote": (
            "Current market evidence is limited here — this reasoning leans on durable "
            "occupational knowledge rather than fresh market activity."
            if assessment["coverage"] < 0.35 else None),
        "changeSummary": change,
    }
    row = AnalysisVersion(
        session_id=session.id, action=action, intent=payload["intent"],
        profile_version_id=(pv.id if pv else None),
        market_snapshot_version=snapshot_version,
        ranker_version=matching.RANKING_VERSION,
        scope_hash=assessment["scopeHash"],
        freshness_state=assessment["state"],
        coverage_score=assessment["coverage"],
        payload=payload,
        supersedes_id=(previous.id if previous else None),
        change_summary=change)
    db.add(row)
    db.flush()

    refreshing = assessment["state"] == "REFRESHING" and assessment.get("refreshId")
    return {
        "status": "refreshing" if refreshing else "complete",
        "analysisId": row.id,
        "analysisVersion": ANALYSIS_VERSION,
        "refreshId": assessment.get("refreshId"),
        "analysis": payload,
        "versions": {
            "profileVersionId": row.profile_version_id,
            "marketSnapshotVersion": row.market_snapshot_version,
            "rankerVersion": row.ranker_version,
            "analysisId": row.id,
        },
        "marketFreshness": payload["marketFreshness"],
    }


def rerun_after_refresh(db: Session, session: DiscoverSession, action: str) -> dict:
    """§49 — when a targeted refresh lands, recompute rather than append."""
    return analyze(db, session, action, refresh_preference="never")
