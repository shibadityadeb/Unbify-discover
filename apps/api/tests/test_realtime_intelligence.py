"""§82-89 QA: real-time recomputation, stale/fresh refresh behavior, concurrent
refresh dedup, cross-profession breadth, retirement intent, regulated fields,
source provenance — and no Redis anywhere."""
from datetime import datetime, timedelta

import pytest


@pytest.fixture()
def db(client):
    from app.db import SessionLocal
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


def make_session(db, practical=None, dims=None, status="DISCOVER_WORKSPACE"):
    from app.models import AnonymousIdentity, DiscoverSession
    anon = AnonymousIdentity()
    db.add(anon)
    db.flush()
    s = DiscoverSession(anon_id=anon.id, journey_status=status,
                        dimensions=dims or {}, practical_context=practical or {}, counters={})
    db.add(s)
    db.flush()
    return s


ELECTRICIAN_CTX = {"current_occupation_title": "electrician", "current_status": "employed",
                   "hands_on_technical": True, "builds_things": True,
                   "commercial_evidence": True, "professional": {"domain": "electrician"}}


def age_signals(db, occupation_id, hours):
    from app.models import WIMarketSignal
    old = datetime.utcnow() - timedelta(hours=hours)
    for sig in db.query(WIMarketSignal).filter_by(occupation_id=occupation_id).all():
        sig.updated_at = old
    db.flush()


# ---------------- §79: no Redis ----------------

def test_no_redis_anywhere():
    """§79 — no Redis/Celery/broker dependency. Comments saying we don't use
    them are fine; imports, packages and services are not."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    usage = re.compile(
        r"^\s*(?:import|from)\s+(?:redis|celery)\b"          # python imports
        r"|require\(['\"](?:redis|ioredis|bullmq)['\"]\)"      # node requires
        r"|redis://"                                          # connection urls
        r"|^\s*image:\s*redis"                                # compose services
        r"|^(?:redis|celery)[><=~]",                          # requirements pins
        re.IGNORECASE | re.MULTILINE)
    offenders = []
    for pattern in ("apps/api/app/**/*.py", "apps/api/requirements.txt",
                    "infra/docker-compose.yml", "apps/web/*.js"):
        for path in root.glob(pattern):
            if usage.search(path.read_text(errors="ignore")):
                offenders.append(str(path.relative_to(root)))
    assert not offenders, f"Redis/broker still in use: {offenders}"


def test_jobs_are_postgres_backed(db):
    from app.world import jobs
    job = jobs.enqueue(db, "targeted_refresh", {"occupationId": "occupation_unbify_elec"},
                       scope_hash="testscope1")
    assert job.status == "pending"
    claimed = jobs.claim(db, ["targeted_refresh"])
    assert claimed is not None and claimed.status == "running"
    assert claimed.attempt_count == 1
    jobs.complete(db, claimed, {"records": 3})
    assert claimed.status == "completed" and claimed.result_metadata["records"] == 3


def test_failed_jobs_retry_then_stop(db):
    from app.world import jobs
    job = jobs.enqueue(db, "_test_retry", {}, scope_hash="testscope_fail")
    for _ in range(jobs.MAX_ATTEMPTS):
        claimed = jobs.claim(db, ["_test_retry"])
        assert claimed is not None
        jobs.fail(db, claimed, "source down")
    assert job.status == "failed", "a job must stop retrying eventually"
    assert jobs.claim(db, ["_test_retry"]) is None, "exhausted jobs must not be reclaimed"


# ---------------- §85: concurrent refresh dedup ----------------

def test_twenty_identical_requests_cause_one_refresh(db):
    from app.models import IntelligenceJob
    from app.world import refresh
    scope = {"occupationId": "occupation_unbify_software", "geography": "bengaluru",
             "intent": "explore_opportunities", "queryTerms": ["software engineer"],
             "signals": ["demand_direction"]}
    before = db.query(IntelligenceJob).count()
    job_ids = set()
    for _ in range(20):
        assessment = refresh.assess(db, scope)
        out = refresh.ensure_fresh(db, scope, assessment, depth="fast")
        if out.get("refreshId"):
            job_ids.add(out["refreshId"])
    created = db.query(IntelligenceJob).count() - before
    assert created <= 1, f"identical scopes must collapse onto one refresh, created {created}"
    assert len(job_ids) <= 1


def test_different_scopes_do_not_collapse(db):
    from app.world import refresh
    a = refresh.scope_hash("occupation_unbify_elec", "pune", "explore_opportunities")
    b = refresh.scope_hash("occupation_unbify_elec", "bengaluru", "explore_opportunities")
    c = refresh.scope_hash("occupation_unbify_elec", "pune", "independent_work")
    assert len({a, b, c}) == 3, "geography and intent must change the scope"


# ---------------- §83/§84: stale triggers refresh, fresh does not ----------------

def test_stale_intelligence_triggers_targeted_refresh(db):
    from app.models import IntelligenceJob
    from app.world import analysis
    session = make_session(db, ELECTRICIAN_CTX)
    age_signals(db, "occupation_unbify_elec", 24 * 30)
    before = db.query(IntelligenceJob).count()
    out = analysis.analyze(db, session, "active_now")
    after = db.query(IntelligenceJob).count()
    assert after > before, "stale data must trigger a targeted refresh"
    assert out["status"] == "refreshing" and out["refreshId"]
    assert out["analysis"]["directions"], "existing evidence must still be returned"


def test_fresh_intelligence_triggers_no_refresh(db):
    from app.models import IntelligenceJob, WIMarketSignal
    from app.world import analysis
    session = make_session(db, ELECTRICIAN_CTX)
    now = datetime.utcnow()
    for sig in db.query(WIMarketSignal).filter_by(occupation_id="occupation_unbify_elec").all():
        sig.updated_at = now
    db.flush()
    before = db.query(IntelligenceJob).count()
    out = analysis.analyze(db, session, "analyze_position")
    assert db.query(IntelligenceJob).count() == before, "fresh data must not cause an Apify run"
    assert out["status"] == "complete"


def test_never_preference_never_refreshes(db):
    from app.models import IntelligenceJob
    from app.world import analysis
    session = make_session(db, ELECTRICIAN_CTX)
    age_signals(db, "occupation_unbify_elec", 24 * 60)
    before = db.query(IntelligenceJob).count()
    analysis.analyze(db, session, "active_now", refresh_preference="never")
    assert db.query(IntelligenceJob).count() == before


# ---------------- §23: per-signal freshness ----------------

def test_freshness_is_per_signal_not_per_profession(db):
    from app.world import analysis, refresh
    session = make_session(db, ELECTRICIAN_CTX)
    out = analysis.analyze(db, session, "explore_opportunities", refresh_preference="never")
    signals_freshness = out["marketFreshness"]["signals"]
    assert len(signals_freshness) >= 2, "several distinct signals must be tracked"
    # different constructs carry different TTLs
    assert refresh.SIGNAL_TTL_HOURS["posting_volume"] < refresh.SIGNAL_TTL_HOURS["occupation_definition"]


# ---------------- §14/§50: computed at request time, versioned ----------------

def test_analysis_is_recomputed_and_versioned(db):
    from app.models import AnalysisVersion
    from app.world import analysis
    session = make_session(db, ELECTRICIAN_CTX)
    first = analysis.analyze(db, session, "explore_opportunities", refresh_preference="never")
    second = analysis.analyze(db, session, "explore_opportunities", refresh_preference="never")
    assert first["analysisId"] != second["analysisId"], "each request computes a new analysis"
    rows = db.query(AnalysisVersion).filter_by(session_id=session.id).all()
    assert len(rows) >= 2, "history must never be overwritten"
    for row in rows:
        assert row.ranker_version and row.scope_hash
    assert second["versions"]["rankerVersion"]


def test_new_evidence_changes_the_recommendation(db):
    """§82 — materially relevant new evidence must move the analysis."""
    from app.world import analysis, ingestion, signals as world_signals
    session = make_session(db, ELECTRICIAN_CTX)
    before = analysis.analyze(db, session, "explore_opportunities", refresh_preference="never")
    before_factors = {d["key"]: d["rankingFactors"].get("market_demand", 0)
                      for d in before["analysis"]["directions"]}
    # new market evidence arrives through the normal ingestion path
    ingestion.ingest_source(db, "src_seed_labor_stats", [
        {"signal_type": "demand_direction", "value": {"level": 0.95},
         "occupation_refs": ["occupation_unbify_solar"], "geography": "*"}])
    world_signals.recompute_signals(db, ["occupation_unbify_solar"])
    from app.models import MaterialObject
    for obj in db.query(MaterialObject).filter_by(session_id=session.id).all():
        db.delete(obj)
    db.flush()
    after = analysis.analyze(db, session, "explore_opportunities", refresh_preference="never")
    after_factors = {d["key"]: d["rankingFactors"].get("market_demand", 0)
                     for d in after["analysis"]["directions"]}
    assert before_factors != after_factors or \
        [d["key"] for d in before["analysis"]["directions"]] != \
        [d["key"] for d in after["analysis"]["directions"]], \
        "materially relevant evidence must change ranking factors"


# ---------------- §44: intent changes candidates ----------------

def test_intent_changes_the_analysis(db):
    from app.world import analysis
    session = make_session(db, ELECTRICIAN_CTX)
    explore = analysis.analyze(db, session, "explore_opportunities", refresh_preference="never")
    independent = analysis.analyze(db, session, "independent_work", refresh_preference="never")
    assert explore["analysis"]["intent"]["kind"] != independent["analysis"]["intent"]["kind"]
    assert explore["analysis"]["marketFreshness"]["signals"].keys() != \
        independent["analysis"]["marketFreshness"]["signals"].keys(), \
        "different intents need different world signals"


# ---------------- §86/§87/§88: breadth, retirement, regulated ----------------

PROFILES = {
    "student": {"current_status": "student", "builds_things": True, "works_with_software": True},
    "electrician": ELECTRICIAN_CTX,
    "plumber": {"current_occupation_title": "plumber", "hands_on_technical": True,
                "commercial_evidence": True},
    "lawyer": {"current_occupation_title": "lawyer", "current_status": "employed"},
    "accountant": {"current_occupation_title": "accountant", "commercial_evidence": True},
    "psychiatrist": {"current_occupation_title": "psychiatrist"},
    "civil engineer": {"current_occupation_title": "civil engineer"},
    "teacher": {"current_occupation_title": "school teacher"},
    "shop owner": {"current_occupation_title": "shop owner", "commercial_evidence": True},
    "retired officer": {"current_occupation_title": "army logistics officer",
                        "people_management_evidence": True, "coordinates_delivery": True},
}


def test_recommendations_do_not_collapse_into_corporate_careers(db):
    from app.world.matching import generate_candidates, rank
    seen = {}
    for label, ctx in PROFILES.items():
        session = make_session(db, ctx)
        gen = generate_candidates(db, session)
        if gen["status"] != "ok":
            continue
        ranked = rank(gen["candidates"], session)[:3]
        seen[label] = tuple(c["occupationId"] for c in ranked)
    assert len(seen) >= 6, "most professions must produce candidates"
    # trades and clinical humans must not be handed the same generic set
    assert seen.get("electrician") != seen.get("lawyer")
    assert seen.get("plumber") != seen.get("student")
    distinct = len(set(seen.values()))
    assert distinct >= max(4, len(seen) // 2), f"candidate sets collapsed: {seen}"


def test_retired_professional_gets_intensity_appropriate_paths(db):
    from app.world.matching import generate_candidates, rank
    session = make_session(db, {**PROFILES["retired officer"], "retired": True})
    gen = generate_candidates(db, session)
    ranked = rank(gen["candidates"], session, "part_time")[:4]
    pathways = {c["pathway"] for c in ranked}
    assert pathways & {"part_time", "advisory", "training", "consulting"}, \
        f"a retired professional wanting light work must see fitting pathways, got {pathways}"


def test_regulated_transition_requires_authoritative_eligibility(db):
    from app.world.matching import generate_candidates
    session = make_session(db, PROFILES["shop owner"])
    gen = generate_candidates(db, session)
    for c in gen.get("candidates", []):
        if c["occupationId"] in ("occupation_unbify_psychiatrist", "occupation_unbify_physician",
                                 "occupation_unbify_lawyer", "occupation_unbify_nurse"):
            assert c["licensing"]["eligible"] or c["pathway"] == "training", \
                "regulated clinical/legal practice must never be offered on market evidence alone"


# ---------------- §53: privacy boundary ----------------

def test_no_personal_data_leaves_in_query_scope(db):
    from app.world import refresh
    session = make_session(db, {**ELECTRICIAN_CTX,
                                "notes": [{"text": "my email is me@example.com and I feel stuck"}],
                                "_facts": {"secret": {"value": "private"}}})
    session.dimensions = {"autonomy": {"estimate": 0.9, "confidence": 0.8, "evidence_count": 4,
                                       "pos_w": 2.0, "neg_w": 0, "variance": 0}}
    scope = refresh.build_query_scope(db, session, "explore_opportunities", "pune")
    blob = " ".join(scope["queryTerms"]).lower()
    assert "@" not in blob and "example.com" not in blob
    assert "stuck" not in blob and "autonomy" not in blob, "psychological state must not leave"
    assert all(len(t) <= 60 for t in scope["queryTerms"])
    assert scope["queryTerms"], "the query must still be useful"


def test_apify_input_strips_identifying_keys(db):
    from app.world.apify_gateway import _clean_input, FORBIDDEN_INPUT_KEYS
    cleaned = _clean_input({"queries": ["electrician"]},
                           {"email": "a@b.com", "sessionId": "abc", "answers": [1],
                            "geography": "pune"})
    assert "geography" in cleaned and "queries" in cleaned
    for key in FORBIDDEN_INPUT_KEYS:
        assert key not in cleaned


# ---------------- §56/§81: no source, no hallucination ----------------

def test_thin_coverage_states_limits_instead_of_inventing(db):
    from app.world import analysis
    session = make_session(db, {"current_occupation_title": "marine electrician"})
    out = analysis.analyze(db, session, "explore_opportunities", refresh_preference="never")
    fresh = out["marketFreshness"]
    assert fresh["state"] in ("INSUFFICIENT", "PARTIAL", "STALE_BUT_USABLE", "CURRENT")
    if fresh["coverage"] < 0.35:
        assert out["analysis"]["worldEvidenceNote"], \
            "thin coverage must be stated, not papered over"


def test_weak_domain_raises_enrichment_priority(db):
    from app.models import DomainEnrichmentRequest
    from app.world import refresh
    scope = {"occupationId": None, "geography": "kochi", "intent": "explore_opportunities",
             "queryTerms": ["marine electrician"], "signals": ["demand_direction"]}
    for _ in range(3):
        refresh.note_domain_demand(db, scope)
    row = (db.query(DomainEnrichmentRequest)
           .filter_by(domain="marine electrician", geography="kochi").first())
    assert row is not None and row.request_count == 3
    assert row.priority < 100, "repeated demand must raise enrichment priority"


# ---------------- §38/§89: provenance ----------------

def test_market_claims_trace_to_source_observations(db):
    from app.models import WIMarketSignal, WISource, WISourceObservation
    for sig in db.query(WIMarketSignal).limit(10).all():
        assert sig.evidence_refs, f"signal {sig.construct} has no observations"
        for ref in sig.evidence_refs[:2]:
            obs = db.get(WISourceObservation, ref)
            assert obs is not None, "signal references a missing observation"
            assert db.get(WISource, obs.source_id) is not None, "observation without a source"


# ---------------- §46/§47: endpoint contract ----------------

def test_analyze_endpoint_contract(client):
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    r = client.post("/v1/discover/actions/analyze",
                    json={"sessionId": sid, "action": "explore_opportunities"})
    assert r.status_code == 409, "analysis must not open before the story completes"
