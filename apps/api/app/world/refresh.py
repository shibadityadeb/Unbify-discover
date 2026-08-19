"""Targeted refresh: keeping the relevant slice of the world current.

Two modes coexist — a broad scheduled refresh (worker) and a user-triggered
targeted refresh that runs only when the *specific* intelligence a request
needs is stale or thin. Concurrent identical requests collapse onto one run
via a scope hash and a PostgreSQL-owned cache row.

Nothing user-identifying ever reaches a source: UNBIFY translates human state
into an impersonal public market query.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import (DiscoverSession, DomainEnrichmentRequest, IntelligenceScopeCache,
                      WIMarketSignal, WIOccupation, WISource, WISourceObservation)
from . import jobs

# §23/§45 — signals age at different rates; one timestamp per profession is a lie
SIGNAL_TTL_HOURS = {
    "occupation_definition": 24 * 90,
    "skills": 24 * 30,
    "demand_direction": 72,
    "posting_volume": 24,
    "compensation": 24 * 21,
    "qualification_requirement": 24 * 30,
    "regulation": 24 * 30,
    "business_problem": 24 * 14,
    "tool_adoption": 24 * 21,
    "self_employment_prevalence": 24 * 60,
}
DEFAULT_TTL_HOURS = 168

# which signals an intent actually depends on — a position analysis leans on
# durable data, "what's active right now" does not
INTENT_SIGNAL_NEEDS = {
    "analyze_position": ["occupation_definition", "skills", "demand_direction"],
    "explore_opportunities": ["demand_direction", "skills", "business_problem"],
    "whats_changing": ["demand_direction", "tool_adoption", "skills"],
    "active_now": ["posting_volume", "demand_direction"],
    "qualification": ["qualification_requirement", "regulation"],
    "independent_work": ["self_employment_prevalence", "business_problem", "demand_direction"],
    "build_something": ["business_problem", "tool_adoption"],
    "transfer": ["skills", "demand_direction"],
}

FRESHNESS = ("CURRENT", "REFRESHING", "PARTIAL", "STALE_BUT_USABLE", "INSUFFICIENT")

# A scope we just refreshed must not immediately re-trigger. Some signals
# simply cannot be obtained from currently-permitted sources; retrying every
# request would burn cost forever and teach us nothing (§56/§84/§90).
REFRESH_COOLDOWN_MINUTES = {"fast": 20, "deep": 180}

# these are properties of the occupation ontology, not of the live market —
# they must never be judged against market TTLs (§40)
ONTOLOGY_CONSTRUCTS = {"occupation_definition", "skills"}


def scope_hash(occupation_id: str | None, geography: str, intent: str,
               source_family: str = "market") -> str:
    basis = f"{occupation_id or 'unknown'}|{(geography or '*').lower()}|{intent}|{source_family}"
    return hashlib.sha256(basis.encode()).hexdigest()[:32]


# ---------------- query scope (UNBIFY builds it, never the LLM alone) ----------------

INTENT_TERMS = {
    "independent_work": ["independent", "self-employed", "contracting"],
    "build_something": ["services", "small business", "problems"],
    "explore_opportunities": ["adjacent roles", "specialization"],
    "whats_changing": ["skills change", "technology adoption"],
    "qualification": ["licence", "certification", "qualification requirements"],
    "active_now": ["hiring", "current openings"],
}


def build_query_scope(db: Session, session: DiscoverSession, intent: str,
                      geography: str = "*") -> dict:
    """Human state → impersonal public market query (§52/§53). Names, emails,
    free text and psychological hypotheses never leave UNBIFY."""
    from .ontology import resolve_user_occupation
    pc = session.practical_context or {}
    resolution = resolve_user_occupation(db, session)
    occupation_id = (resolution["candidates"][0]["occupationId"]
                     if resolution.get("candidates") else None)
    terms: list[str] = []
    if occupation_id:
        occ = db.get(WIOccupation, occupation_id)
        if occ:
            terms.append(occ.preferred_label.lower())
            # adjacent occupations are part of the same market question
            from ..models import WIOccupationTransition
            for t in (db.query(WIOccupationTransition)
                      .filter_by(from_occupation_id=occupation_id).limit(3).all()):
                adj = db.get(WIOccupation, t.to_occupation_id)
                if adj:
                    terms.append(adj.preferred_label.lower())
    else:
        title = pc.get("current_occupation_title")
        if title:
            terms.append(str(title).lower())
    terms.extend(INTENT_TERMS.get(intent, []))
    # scrub: no identifiers, no long free text, bounded set
    clean = []
    for t in terms:
        t = str(t).strip()
        if not t or "@" in t or len(t) > 60:
            continue
        if t not in clean:
            clean.append(t)
    return {"occupationId": occupation_id, "geography": geography or "*",
            "intent": intent, "queryTerms": clean[:8],
            "signals": INTENT_SIGNAL_NEEDS.get(intent, ["demand_direction"])}


# ---------------- coverage + freshness ----------------

def coverage_score(db: Session, occupation_id: str | None, geography: str = "*") -> float:
    """How well do we actually know this corner of the world? Sources,
    diversity, quality, freshness, observation count, geographic specificity."""
    if not occupation_id:
        return 0.0
    signals = (db.query(WIMarketSignal)
               .filter(WIMarketSignal.occupation_id == occupation_id).all())
    if not signals:
        return 0.0
    obs_ids = {i for s in signals for i in (s.evidence_refs or [])}
    observations = [db.get(WISourceObservation, i) for i in list(obs_ids)[:60]]
    observations = [o for o in observations if o]
    source_ids = {o.source_id for o in observations}
    source_types = set()
    quality = []
    for sid in source_ids:
        src = db.get(WISource, sid)
        if src:
            source_types.add(src.type)
            quality.append(src.trust_score)
    geo_specific = any(s.geography == geography for s in signals) if geography != "*" else True
    now = datetime.utcnow()
    freshest = min(((now - s.updated_at).total_seconds() / 3600) for s in signals)
    score = (
        0.25 * min(1.0, len(source_ids) / 3)
        + 0.2 * min(1.0, len(source_types) / 3)
        + 0.2 * (sum(quality) / len(quality) if quality else 0.3)
        + 0.15 * min(1.0, len(observations) / 12)
        + 0.1 * (1.0 if geo_specific else 0.4)
        + 0.1 * (1.0 if freshest < DEFAULT_TTL_HOURS else 0.3)
    )
    return round(min(1.0, score), 3)


def signal_freshness(db: Session, occupation_id: str | None, needed: list[str],
                     geography: str = "*") -> dict:
    """Per-signal ages and TTLs — never one timestamp for a whole profession."""
    out = {}
    now = datetime.utcnow()
    for construct in needed:
        ttl = SIGNAL_TTL_HOURS.get(construct, DEFAULT_TTL_HOURS)
        if construct in ONTOLOGY_CONSTRUCTS:
            # durable occupational knowledge — a different clock entirely
            occ = db.get(WIOccupation, occupation_id) if occupation_id else None
            if not occ:
                out[construct] = {"present": False, "ageHours": None,
                                  "ttlHours": ttl, "stale": True}
                continue
            age = (now - occ.definition_updated_at).total_seconds() / 3600
            out[construct] = {"present": True, "ageHours": round(age, 1), "ttlHours": ttl,
                              "stale": age > ttl, "confidence": 0.9,
                              "snapshotVersion": f"occdef_v{occ.definition_version}"}
            continue
        sig = None
        if occupation_id:
            sig = (db.query(WIMarketSignal)
                   .filter_by(occupation_id=occupation_id, construct=construct,
                              geography=geography).first())
            if not sig:
                sig = (db.query(WIMarketSignal)
                       .filter_by(occupation_id=occupation_id, construct=construct,
                                  geography="*").first())
        if not sig:
            out[construct] = {"present": False, "ageHours": None, "ttlHours": ttl, "stale": True}
            continue
        age = (now - sig.updated_at).total_seconds() / 3600
        out[construct] = {"present": True, "ageHours": round(age, 1), "ttlHours": ttl,
                          "stale": age > ttl, "confidence": sig.confidence,
                          "snapshotVersion": sig.snapshot_version}
    return out


def assess(db: Session, scope: dict) -> dict:
    """→ {state, coverage, signalFreshness, scopeHash}. The honest picture of
    what we currently know before deciding whether to go get more."""
    occupation_id = scope.get("occupationId")
    geography = scope.get("geography", "*")
    sh = scope_hash(occupation_id, geography, scope.get("intent", "explore"))
    freshness = signal_freshness(db, occupation_id, scope.get("signals", []), geography)
    coverage = coverage_score(db, occupation_id, geography)
    cache = db.get(IntelligenceScopeCache, sh)
    if cache and cache.refreshing_job_id:
        job = db.get(jobs.IntelligenceJob, cache.refreshing_job_id)
        if job and job.status in ("pending", "running"):
            return {"state": "REFRESHING", "coverage": coverage, "scopeHash": sh,
                    "signalFreshness": freshness, "refreshId": job.id}
    present = [f for f in freshness.values() if f["present"]]
    stale = [f for f in freshness.values() if f["stale"]]
    if not present:
        state = "INSUFFICIENT"
    elif not stale:
        state = "CURRENT"
    elif len(present) < len(freshness):
        state = "PARTIAL"
    else:
        state = "STALE_BUT_USABLE"
    if coverage < 0.25 and state != "CURRENT":
        state = "INSUFFICIENT"
    return {"state": state, "coverage": coverage, "scopeHash": sh,
            "signalFreshness": freshness, "refreshId": None}


# ---------------- triggering refresh ----------------

def ensure_fresh(db: Session, scope: dict, assessment: dict, depth: str = "fast",
                 allow_refresh: bool = True) -> dict:
    """Trigger a targeted refresh when — and only when — the specific
    intelligence this request needs is stale or missing. Identical concurrent
    scopes reuse one job."""
    state = assessment["state"]
    if state in ("CURRENT", "REFRESHING") or not allow_refresh:
        return assessment
    sh = assessment["scopeHash"]
    cache = db.get(IntelligenceScopeCache, sh)
    if cache and cache.last_refresh_at:
        cooldown = REFRESH_COOLDOWN_MINUTES.get(depth, 20)
        if datetime.utcnow() - cache.last_refresh_at < timedelta(minutes=cooldown):
            # we already went and looked; what's missing isn't available right
            # now, so say so rather than scraping in a loop
            return {**assessment, "refreshId": None, "refreshCooldown": True}
    if not cache:
        cache = IntelligenceScopeCache(scope_hash=sh, occupation_id=scope.get("occupationId"),
                                       geography=scope.get("geography", "*"),
                                       intent=scope.get("intent", "explore"),
                                       query_terms=scope.get("queryTerms", []))
        db.add(cache)
        db.flush()
    job = jobs.enqueue(db, "deep_refresh" if depth == "deep" else "targeted_refresh",
                       scope={**scope, "depth": depth}, scope_hash=sh,
                       priority=50 if depth == "fast" else 120)
    cache.refreshing_job_id = job.id
    cache.freshness_state = "REFRESHING"
    cache.coverage_score = assessment["coverage"]
    cache.query_terms = scope.get("queryTerms", [])
    db.flush()
    # weak coverage also raises the domain's standing enrichment priority
    if assessment["coverage"] < 0.35:
        note_domain_demand(db, scope)
    return {**assessment, "state": "REFRESHING", "refreshId": job.id}


def note_domain_demand(db: Session, scope: dict) -> None:
    """§69/§70 — repeated arrivals from a thin domain pull enrichment forward."""
    domain = scope.get("occupationId") or (scope.get("queryTerms") or ["unknown"])[0]
    geo = scope.get("geography", "*")
    row = (db.query(DomainEnrichmentRequest)
           .filter_by(domain=str(domain)[:120], geography=geo).first())
    if not row:
        row = DomainEnrichmentRequest(domain=str(domain)[:120], geography=geo,
                                      current_coverage=0.0, request_count=1, priority=100)
        db.add(row)
    else:
        row.request_count = (row.request_count or 0) + 1
    row.last_requested_at = datetime.utcnow()
    row.priority = max(1, 100 - (row.request_count or 1) * 5)
    db.flush()


def mark_refreshed(db: Session, scope_hash_value: str, snapshot_version: str | None,
                   coverage: float) -> None:
    cache = db.get(IntelligenceScopeCache, scope_hash_value)
    if not cache:
        return
    cache.refreshing_job_id = None
    cache.freshness_state = "CURRENT"
    cache.latest_snapshot_version = snapshot_version
    cache.coverage_score = coverage
    cache.last_refresh_at = datetime.utcnow()
    db.flush()
