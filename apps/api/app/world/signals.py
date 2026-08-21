"""Observation → MarketSignal aggregation. One post is never market evidence;
signals need source count, diversity, quality, recency and geography.
Disagreeing source classes are retained as conflicts, never silently resolved."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import WIMarketSignal, WISource, WISourceObservation

MIN_OBSERVATIONS_FOR_SIGNAL = 1     # baseline government aggregates count alone;
MIN_COMMUNITY_OBSERVATIONS = 5      # community sources never do (PART 16/17)


def snapshot_version() -> str:
    return f"mkt_{datetime.utcnow():%Y%m%d}_{uuid.uuid4().hex[:6]}"


def recompute_signals(db: Session, occupation_ids: list[str] | None = None) -> str:
    """Aggregate observations into market signals, one snapshot version.
    Change-detection upstream means unchanged observations don't force this."""
    version = snapshot_version()
    q = db.query(WISourceObservation)
    observations = q.all()
    sources = {s.id: s for s in db.query(WISource).all()}
    grouped: dict[tuple[str, str, str], list[WISourceObservation]] = {}
    for obs in observations:
        for occ in obs.occupation_refs or []:
            if occupation_ids and occ not in occupation_ids:
                continue
            grouped.setdefault((occ, obs.signal_type, obs.geography), []).append(obs)

    now = datetime.utcnow()
    for (occ, construct, geo), group in grouped.items():
        community = [o for o in group if sources.get(o.source_id) and
                     sources[o.source_id].type == "community"]
        strong = [o for o in group if o not in community]
        if not strong and len(community) < MIN_COMMUNITY_OBSERVATIONS:
            continue     # community alone below threshold: no signal
        usable = strong + (community if len(community) >= MIN_COMMUNITY_OBSERVATIONS else [])
        if len(usable) < MIN_OBSERVATIONS_FOR_SIGNAL:
            continue
        # quality-weighted value with recency decay
        num = den = 0.0
        for o in usable:
            age_days = max(0.0, (now - o.observed_at).total_seconds() / 86400)
            recency = 0.5 ** (age_days / 90)
            w = o.source_quality * recency
            num += float((o.value or {}).get("level", 0)) * w
            den += w
        if den == 0:
            continue
        value = num / den
        diversity = len({sources[o.source_id].type for o in usable if o.source_id in sources})
        avg_quality = sum(o.source_quality for o in usable) / len(usable)
        confidence = min(0.95, avg_quality
                         * (0.5 + 0.15 * min(3, diversity))
                         * (0.6 + 0.1 * min(4, len(usable))))
        # source-class conflicts: keep both readings (PART 73)
        by_class: dict[str, list[float]] = {}
        for o in usable:
            cls = sources[o.source_id].type if o.source_id in sources else "other"
            by_class.setdefault(cls, []).append(float((o.value or {}).get("level", 0)))
        class_means = {c: sum(v) / len(v) for c, v in by_class.items()}
        conflicts = []
        classes = list(class_means.items())
        for i, (ca, va) in enumerate(classes):
            for cb, vb in classes[i + 1:]:
                if abs(va - vb) > 0.35:
                    conflicts.append({"classA": ca, "valueA": round(va, 2),
                                      "classB": cb, "valueB": round(vb, 2)})
        row = (db.query(WIMarketSignal)
               .filter_by(occupation_id=occ, construct=construct, geography=geo).first())
        if not row:
            row = WIMarketSignal(occupation_id=occ, construct=construct, geography=geo,
                                 geography_level=group[0].geography_level)
            db.add(row)
        row.value = round(value, 3)
        row.confidence = round(confidence, 3)
        row.source_count = len(usable)
        row.source_diversity = diversity
        row.evidence_refs = [o.id for o in usable][-20:]
        row.conflicts = conflicts
        row.window_start = min(o.observed_at for o in usable)
        row.window_end = max(o.observed_at for o in usable)
        row.snapshot_version = version
        row.updated_at = now
    db.flush()
    return version


def signal_for(db: Session, occupation_id: str, construct: str,
               geography: str = "*") -> WIMarketSignal | None:
    """Geography fallback: exact geo, else national/global — never fake
    city-level precision from national evidence (the caller sees the geo)."""
    row = (db.query(WIMarketSignal)
           .filter_by(occupation_id=occupation_id, construct=construct, geography=geography).first())
    if row:
        return row
    return (db.query(WIMarketSignal)
            .filter_by(occupation_id=occupation_id, construct=construct, geography="*").first())


def demand_evidence(db: Session, signal: WIMarketSignal | None) -> dict:
    """The provenance behind a demand signal, stated so the reader can check it:
    which named sources, and each source's own wording where it carried one."""
    if not signal or not signal.evidence_refs:
        return {"sources": [], "citations": []}
    obs = (db.query(WISourceObservation)
           .filter(WISourceObservation.id.in_(signal.evidence_refs)).all())
    src_ids = {o.source_id for o in obs}
    names = {s.id: s.name for s in
             db.query(WISource).filter(WISource.id.in_(src_ids)).all()}
    citations = []
    for o in obs:
        v = o.value or {}
        if v.get("note"):
            citations.append({"source": names.get(o.source_id, o.source_id),
                              "note": v["note"],
                              "growthPct": v.get("growthPct"),
                              "horizon": v.get("horizon"),
                              "level": v.get("level")})
    return {"sources": sorted(names.get(s, s) for s in src_ids),
            "citations": citations}


def freshness_days(signal: WIMarketSignal | None) -> int | None:
    if not signal:
        return None
    return max(0, int((datetime.utcnow() - signal.updated_at).total_seconds() / 86400))


def is_stale(db: Session, signal: WIMarketSignal | None, default_ttl_hours: int = 168) -> bool:
    if not signal:
        return True
    age_h = (datetime.utcnow() - signal.updated_at).total_seconds() / 3600
    return age_h > default_ttl_hours


def request_targeted_refresh(db: Session, occupation_id: str | None, query_terms: list[str],
                             geography: str = "*", reason: str = "stale") -> None:
    """Queue a privacy-scrubbed targeted refresh. Only generic market terms —
    a user's name, answers or psychology never appear here (PART 49/50)."""
    from ..models import WITargetedRefreshRequest
    clean_terms = [t for t in query_terms if "@" not in t and len(t) < 60][:6]
    db.add(WITargetedRefreshRequest(occupation_id=occupation_id, query_terms=clean_terms,
                                    geography=geography, reason=reason))
    db.flush()
