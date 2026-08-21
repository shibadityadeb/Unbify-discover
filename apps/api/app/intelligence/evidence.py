"""EvidenceNormalizer + EvidenceValidator: every market claim a recommendation
makes is assembled here, carrying source, metric, value, period, geography and
retrieval time. Confidence states depend on source count, quality, recency and
historical depth — never on how confident a sentence sounds."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import WISourceObservation
from ..world import signals as wsignals
from . import growth, market

# registry metadata (about the sources themselves, not market values)
SOURCE_URLS = {
    "src_bls_projections": "https://www.bls.gov/emp/",
    "src_industry_outlook": "https://www.weforum.org/publications/the-future-of-jobs-report-2025/",
    "src_seed_labor_stats": None,
    "src_apify_job_postings": None,
}

STATES = ("HIGH_CONFIDENCE", "MODERATE_CONFIDENCE", "LIMITED_EVIDENCE", "INSUFFICIENT_DATA")


def _resolve_occupation_id(db: Session, title: str) -> str | None:
    from ..models import WIOccupationAlias
    t = (title or "").lower().strip()
    row = db.query(WIOccupationAlias).filter(WIOccupationAlias.alias == t).first()
    return row.occupation_id if row else None


def official_evidence(db: Session, title: str) -> dict:
    """Tier 1/2: seeded official observations for a resolvable occupation.
    Unresolvable titles simply have no official tier — stated, not padded."""
    occ_id = _resolve_occupation_id(db, title)
    if not occ_id:
        return {"signal": None, "entries": []}
    sig = wsignals.signal_for(db, occ_id, "demand_direction")
    if not sig:
        return {"signal": None, "entries": []}
    ev = wsignals.demand_evidence(db, sig)
    entries = []
    obs_dates = {}
    if sig.evidence_refs:
        for o in db.query(WISourceObservation).filter(
                WISourceObservation.id.in_(sig.evidence_refs)).all():
            obs_dates[(o.source_id, (o.value or {}).get("note"))] = o
    for c in ev.get("citations", []):
        obs = next((o for (sid, note), o in obs_dates.items() if note == c.get("note")), None)
        entries.append({
            "source": c["source"], "publisher": c["source"],
            "url": SOURCE_URLS.get(obs.source_id) if obs else None,
            "metric": "employment growth projection" if c.get("growthPct") is not None
                      else "demand direction reading",
            "value": (f"+{c['growthPct']}%" if c.get("growthPct") is not None
                      else f"{c.get('level')}"),
            "period": c.get("horizon"),
            "geography": sig.geography or "*",
            "retrieved_at": (obs.observed_at.isoformat() + "Z") if obs else None,
            "methodology": "official projection" if c.get("growthPct") is not None
                           else "curated reading",
        })
    return {"signal": {"value": sig.value, "confidence": sig.confidence,
                       "sourceCount": sig.source_count, "geography": sig.geography},
            "entries": entries}


def live_evidence(db: Session, title: str, queries: list[str],
                  geography: str = "*") -> dict:
    """Tier 3: statistics over stored live postings relevant to this candidate
    — its own search terms plus title-matched postings from the whole sweep —
    with rolling-window changes computed from the rows."""
    postings = market.candidate_postings(db, title, queries, geography)
    st = market.postings_stats(db, postings)
    changes = growth.window_comparison(st["windows"])
    entries = []
    if st["postings"]:
        entries.append({
            "source": "Live job postings (company career sites via Apify)",
            "publisher": "employer career sites / ATS platforms",
            "url": st["sampleUrls"][0] if st["sampleUrls"] else None,
            "metric": "job postings observed",
            "value": st["postings"], "period": "rolling windows",
            "geography": geography or "*",
            "retrieved_at": st["lastRetrievedAt"],
            "methodology": f"{st['postings']} deduplicated postings from "
                           f"{st['companies']} companies matched to this opportunity",
        })
    return {"postings": st["postings"], "companies": st["companies"], "windows": changes,
            "salary": st["salary"], "topSkills": st["topSkills"],
            "entries": entries, "lastRetrievedAt": st["lastRetrievedAt"]}


def confidence_state(official: dict, live: dict) -> str:
    official_n = len(official.get("entries", []))
    has_live = live.get("postings", 0) >= 5
    has_history = any(c.get("state") == "ok" for c in (live.get("windows") or {}).values()) \
        or any(e.get("metric") == "employment growth projection" for e in official.get("entries", []))
    if official_n >= 2 and has_live:
        return "HIGH_CONFIDENCE"
    if (official_n >= 2) or (official_n >= 1 and has_live):
        return "MODERATE_CONFIDENCE"
    if official_n or live.get("postings", 0) > 0:
        return "LIMITED_EVIDENCE"
    return "INSUFFICIENT_DATA"


def demand_summary(official: dict, live: dict) -> dict:
    """One honest demand cell: direction from official signal when strong
    enough, live windows for recency, or an explicit insufficiency."""
    sig = official.get("signal")
    direction = None
    if sig and sig.get("confidence", 0) >= 0.4:
        v = sig["value"]
        direction = "growing" if v >= 0.65 else "steady" if v >= 0.45 else "softening"
    recent = (live.get("windows") or {}).get("30d") or {}
    return {
        "direction": direction or "unknown",
        "officialSignal": sig,
        "livePostings": live.get("postings", 0),
        "windows": live.get("windows"),
        "recentChangePct": recent.get("pct") if recent.get("state") == "ok" else None,
        "note": None if direction else "Evidence insufficient for a demand direction",
        "lastUpdated": live.get("lastRetrievedAt") or datetime.utcnow().isoformat() + "Z",
    }
