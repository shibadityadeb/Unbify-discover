"""World Intelligence tests: diverse ontology, entity resolution, compliant
ingestion, signal aggregation, capability-based matching for NON-tech humans,
regulated eligibility, intent-aware ranking, privacy, and abstention."""
import pytest


@pytest.fixture()
def db(client):
    from app.db import SessionLocal
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


def make_session(db, practical=None, dims=None):
    from app.models import AnonymousIdentity, DiscoverSession
    anon = AnonymousIdentity()
    db.add(anon)
    db.flush()
    session = DiscoverSession(anon_id=anon.id, journey_status="DISCOVER_WORKSPACE",
                              dimensions=dims or {}, practical_context=practical or {},
                              counters={})
    db.add(session)
    db.flush()
    return session


# ---------------- ontology diversity + resolution ----------------

def test_ontology_is_not_white_collar_only(db):
    from app.models import WIOccupation
    occs = {o.id: o for o in db.query(WIOccupation).all()}
    assert len(occs) >= 20
    classes = {o.work_class for o in occs.values()}
    assert {"trade", "clinical", "knowledge", "operational", "service", "field"} <= classes
    # trades are modeled properly, not as an afterthought
    elec = occs["occupation_unbify_elec"]
    assert "contracting" in elec.pathway_potentials
    assert "business_ownership" in elec.pathway_potentials
    assert elec.physical_environment


def test_entity_resolution_aliases_but_keeps_distinctions(db):
    from app.world.ontology import resolve_title
    r = resolve_title(db, "electrical technician")
    assert r["status"] == "resolved"
    assert r["candidates"][0]["occupationId"] == "occupation_unbify_elec"
    # industrial electrician stays its own occupation, not merged
    r2 = resolve_title(db, "industrial maintenance electrician")
    assert r2["candidates"][0]["occupationId"] == "occupation_unbify_elec_ind"
    # unknown profession does not get rejected or force-fit with high confidence
    r3 = resolve_title(db, "quantum basket weaver")
    assert r3["status"] in ("unknown", "ambiguous")


def test_external_mappings_are_not_the_canonical_ids(db):
    from app.models import WIOccupationExternalMapping
    rows = db.query(WIOccupationExternalMapping).filter_by(scheme="onet").all()
    assert rows, "external taxonomy mappings must exist"
    for r in rows:
        assert r.occupation_id.startswith("occupation_unbify_"), "canonical ids are UNBIFY's own"


# ---------------- compliance + ingestion ----------------

def test_noncompliant_source_is_rejected(db):
    from app.world.ingestion import ingest_source
    run = ingest_source(db, "src_apify_job_postings",
                        [{"signal_type": "demand_direction", "value": {"level": 0.9},
                          "occupation_refs": ["occupation_unbify_software"]}])
    assert run.status == "failed"
    assert "disabled" in run.error or "compliance" in run.error


def test_linkedin_adapter_boundary_is_disabled(db):
    from app.models import WISource
    src = db.get(WISource, "src_linkedin_authorized")
    assert src is not None and src.enabled is False
    assert src.allowed_uses == []


def test_ingestion_dedupes_and_tracks_quality(db):
    from app.world.ingestion import ingest_source
    rec = {"signal_type": "demand_direction", "value": {"level": 0.5},
           "occupation_refs": ["occupation_unbify_welder"], "geography": "testland"}
    run = ingest_source(db, "src_seed_labor_stats", [rec, rec, {"signal_type": None, "value": {}}])
    assert run.status == "completed"
    assert run.deduplicated_count == 1
    assert run.validation_failures == 1
    assert run.quality["valid_pct"] < 1.0


def test_source_failure_keeps_previous_signals(db):
    from app.models import WIMarketSignal
    from app.world.ingestion import ingest_source
    before = db.query(WIMarketSignal).count()
    run = ingest_source(db, "does_not_exist", [])
    assert run.status == "failed"
    assert db.query(WIMarketSignal).count() == before, "failure must never wipe intelligence"


# ---------------- market signals ----------------

def test_community_posts_alone_are_not_market_evidence(db):
    from app.models import WISource, WIMarketSignal
    from app.world.ingestion import ingest_source
    from app.world.signals import recompute_signals
    src = db.get(WISource, "src_community_signals")
    src.enabled = True
    src.compliance = {"terms_reviewed": True, "license_known": True,
                      "storage_permitted": True, "usage_known": True}
    ingest_source(db, "src_community_signals",
                  [{"signal_type": "demand_direction", "value": {"level": 0.95},
                    "occupation_refs": ["occupation_unbify_carpenter"], "geography": "communityville",
                    "external_id": "post1"}])
    recompute_signals(db, ["occupation_unbify_carpenter"])
    sig = (db.query(WIMarketSignal)
           .filter_by(occupation_id="occupation_unbify_carpenter", geography="communityville").first())
    assert sig is None, "one community post must never become a market signal"


def test_source_conflicts_are_retained_not_resolved(db):
    from app.models import WISource, WIMarketSignal
    from app.world.ingestion import ingest_source
    from app.world.signals import recompute_signals
    gov = db.get(WISource, "src_seed_labor_stats")
    ingest_source(db, gov.id, [{"signal_type": "demand_direction", "value": {"level": 0.8},
                                "occupation_refs": ["occupation_unbify_mecheng"], "geography": "conflictia"}])
    # a second, disagreeing source class
    from app.models import WISource as S
    if not db.get(S, "src_test_jobboard"):
        db.add(S(id="src_test_jobboard", name="test job board", type="job_board",
                 country_coverage=["*"], access_method="api", refresh_policy="daily",
                 ttl_hours=72, allowed_uses=["market_signals"], trust_score=0.7, enabled=True,
                 compliance={"terms_reviewed": True, "license_known": True,
                             "storage_permitted": True, "usage_known": True}))
        db.flush()
    ingest_source(db, "src_test_jobboard",
                  [{"signal_type": "demand_direction", "value": {"level": 0.1},
                    "occupation_refs": ["occupation_unbify_mecheng"], "geography": "conflictia"}])
    recompute_signals(db, ["occupation_unbify_mecheng"])
    sig = (db.query(WIMarketSignal)
           .filter_by(occupation_id="occupation_unbify_mecheng", geography="conflictia").first())
    assert sig is not None and sig.conflicts, "disagreeing source classes must be kept, not averaged silently"


# ---------------- matching: real, diverse humans ----------------

def electrician_session(db):
    return make_session(db, practical={
        "current_occupation_title": "electrician", "current_status": "employed",
        "hands_on_technical": True, "builds_things": True, "commercial_evidence": True,
        "professional": {"domain": "electrician"},
    })


def test_electrician_gets_trade_paths_not_software(db):
    from app.world.matching import generate_candidates, rank
    session = electrician_session(db)
    gen = generate_candidates(db, session)
    assert gen["status"] == "ok"
    ranked = rank(gen["candidates"], session)
    labels = [c["label"] for c in ranked]
    top_ids = [c["occupationId"] for c in ranked[:4]]
    trade_targets = {"occupation_unbify_elec", "occupation_unbify_elec_ind",
                     "occupation_unbify_solar", "occupation_unbify_facilities",
                     "occupation_unbify_trainer", "occupation_unbify_plumber"}
    assert any(t in top_ids for t in trade_targets), f"electrician should see trade paths, got {labels}"
    assert "occupation_unbify_software" not in top_ids[:2], "no forced digital transition"
    pathways = {c["pathway"] for c in ranked}
    assert len(pathways) >= 2, "pathway diversity beyond employment"


def test_military_logistics_transfers_to_supply_chain(db):
    from app.world.matching import generate_candidates
    session = make_session(db, practical={
        "current_occupation_title": "army logistics officer",
        "people_management_evidence": True, "coordinates_delivery": True,
    })
    gen = generate_candidates(db, session)
    assert gen["status"] == "ok"
    sc = next((c for c in gen["candidates"]
               if c["occupationId"] == "occupation_unbify_supplychain"), None)
    assert sc is not None, "capability overlap must surface the supply-chain transition"
    assert sc["isKnownTransition"]
    assert "logistics_planning" in sc["transfers"] or "procurement" in sc["transfers"]


def test_regulated_practice_needs_eligibility(db):
    from app.world.matching import generate_candidates
    session = make_session(db, practical={
        "current_occupation_title": "shop owner", "commercial_evidence": True,
        "people_management_evidence": True})
    gen = generate_candidates(db, session)
    for c in gen.get("candidates", []):
        if c["occupationId"] in ("occupation_unbify_physician", "occupation_unbify_psychiatrist",
                                 "occupation_unbify_lawyer"):
            assert c["pathway"] == "training" or c["licensing"]["eligible"], \
                "regulated practice must never be offered without eligibility"


def test_intent_changes_ranking(db):
    from app.world.matching import generate_candidates, rank
    session = electrician_session(db)
    gen = generate_candidates(db, session)
    income = [f"{c['occupationId']}:{c['pathway']}" for c in rank(gen["candidates"], session, "max_income")[:4]]
    part_time = [f"{c['occupationId']}:{c['pathway']}" for c in rank(gen["candidates"], session, "part_time")[:4]]
    build = [f"{c['occupationId']}:{c['pathway']}" for c in rank(gen["candidates"], session, "build")[:4]]
    assert len({tuple(income), tuple(part_time), tuple(build)}) >= 2, \
        "different objectives must produce different rankings"


def test_recommendation_is_snapshotted_and_honest_about_timing(db):
    from app.world.matching import recommend
    from app.models import RecommendationItem, WIOpportunitySnapshot
    session = electrician_session(db)
    rec_set = recommend(db, session)
    assert rec_set is not None
    items = db.query(RecommendationItem).filter_by(set_id=rec_set.id).all()
    assert len(items) >= 2
    for item in items:
        n = item.narrative
        assert n["whyYou"] and n["friction"] and n["confidenceLabel"] in ("grounded", "emerging", "uncertain")
        # PART 37: whyNow is evidence or an honest absence — never AI hype filler
        assert n["whyNow"].startswith(("current market evidence", "documented problem",
                                       "No strong timing signal"))
        assert item.factor_contributions, "ranking must be explainable"
    snap = (db.query(WIOpportunitySnapshot)
            .filter_by(recommendation_set_id=rec_set.id).first())
    assert snap is not None and snap.ranking_model_version and snap.candidates


def test_abstention_when_no_capability_evidence(db):
    from app.world.matching import generate_candidates
    session = make_session(db, practical={})
    gen = generate_candidates(db, session)
    assert gen["status"] == "insufficient_world_evidence", "no evidence → abstain, never fabricate"


def test_targeted_refresh_is_privacy_scrubbed(db):
    from app.world.signals import request_targeted_refresh
    from app.models import WITargetedRefreshRequest
    request_targeted_refresh(db, None,
                             ["industrial electrical maintenance", "john.smith@example.com",
                              "x" * 80, "Pune region"], "IN", reason="stale")
    row = (db.query(WITargetedRefreshRequest)
           .order_by(WITargetedRefreshRequest.created_at.desc()).first())
    assert "john.smith@example.com" not in row.query_terms
    assert all(len(t) < 60 for t in row.query_terms)
    assert "industrial electrical maintenance" in row.query_terms


def test_market_data_never_alters_human_profile(db):
    """PART 75: world intelligence and human intelligence stay separate."""
    from app.world.matching import recommend
    session = electrician_session(db)
    dims_before = dict(session.dimensions or {})
    pc_keys_before = {k for k in session.practical_context if not k.startswith("_")}
    recommend(db, session)
    assert dict(session.dimensions or {}) == dims_before
    assert {k for k in session.practical_context if not k.startswith("_")} == pc_keys_before


def test_generic_head_noun_never_resolves_an_occupation(db):
    """A single shared generic noun is not evidence.

    "chief vibe officer" used to resolve to Military Logistics Officer (shared
    token: "officer") and "yoga teacher" to School Teacher. Both then carried
    real market signals for the wrong occupation, stated as fact.
    """
    from app.world.ontology import resolve_title
    for junk in ("chief vibe officer", "yoga teacher", "head of growth"):
        assert resolve_title(db, junk)["status"] == "unknown", \
            f"{junk!r} must not resolve on a generic head noun alone"
    # ...while real titles still resolve, including partial ones
    for good, expected in (("electrician", "Electrician"),
                           ("industrial electrician", "Industrial Electrician"),
                           ("nurse", "Registered Nurse")):
        res = resolve_title(db, good)
        assert res["status"] == "resolved", f"{good!r} must still resolve"
        assert res["candidates"][0]["label"] == expected


def test_operator_gets_no_employed_role_directions(db):
    """A founder is not a job-seeker. Employed roles must not lead for someone
    who told us they already run the business."""
    from app.world.matching import rank
    session = make_session(db)
    session.practical_context = {"current_status": "founder"}
    base = {"capabilityFit": 0.6, "isCurrentField": False, "isKnownTransition": False,
            "market": {"demand": 0.5, "confidence": 0.5}, "missing": [],
            "licensing": {"eligible": True}, "selfEmployment": 0.4,
            "ai": {"augmentationPotential": 0.5, "automationExposure": 0.2}}
    cands = [{**base, "occupationId": "o1", "pathway": "employment", "label": "A"},
             {**base, "occupationId": "o2", "pathway": "business_ownership", "label": "B"}]
    ranked = rank(cands, session)
    assert ranked[0]["pathway"] != "employment", \
        "an employed role must not outrank ownership for someone already operating"
    employed = next(c for c in ranked if c["pathway"] == "employment")
    assert employed["factors"].get("already_operating", 0) < 0


def test_venture_market_standing_refuses_single_source_claims(db):
    """The seeded baseline is one source. It must never become a stated fact."""
    from app import venture
    session = make_session(db)
    session.practical_context = {"current_status": "founder",
                                 "current_occupation_title": "electrician"}
    out = venture.market_standing(db, session)
    assert out["status"] == "insufficient_market_evidence"
    assert all(r["usable"] is False and r["reading"] is None for r in out["readings"]), \
        "a single-source reading must never be phrased as a claim"
    assert out["readings"], "the underlying numbers stay visible even when unusable"


def test_venture_surfaces_are_all_prelaunch_and_reasoned(db):
    from app import venture
    session = make_session(db)
    session.practical_context = {"current_status": "founder"}
    answers = {"shape": "solo", "solo_load": "delivery",
               "funding": "bootstrapped", "friction": "knowledge"}
    surfaces = venture.surfaces_for(db, session, answers, [])
    assert surfaces
    for s in surfaces:
        assert s["status"] == "coming_soon" and s["url"] is None, \
            "nothing ships as available until it actually is"
        assert s["because"], "a surface with no stated reason must not appear"
    assert not venture.surfaces_for(db, session, {}, []), \
        "no answers, no product recommendations"
