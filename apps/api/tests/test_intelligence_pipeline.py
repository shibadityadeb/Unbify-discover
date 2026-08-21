"""The opportunity intelligence pipeline: no predefined occupation required,
profiles produce materially different discoveries, growth is arithmetic over
real observations, evidence travels with every claim, and the Apify token
never appears in anything a client could see."""
import json
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


def run_pipeline(db, practical, dims=None):
    from app.intelligence import pipeline
    return pipeline.run(db, make_session(db, practical=practical, dims=dims))


def titles(out):
    return " | ".join(r["title"].lower() for r in out["recommendations"])


PROFILES = {
    "doctor": {"current_occupation_title": "physician", "current_status": "employed_good",
               "professional": {"domain": "medicine", "industry": "healthcare",
                                "activities": ["diagnosis", "patient care"]}},
    "psychiatrist_founder": {"current_occupation_title": "psychiatrist",
                             "current_status": "employed_stale", "commercial_evidence": True,
                             "independent_projects": True,
                             "professional": {"domain": "psychiatry", "industry": "healthcare",
                                              "activities": ["clinical assessment", "counseling"]}},
    "carpenter": {"current_occupation_title": "carpenter", "current_status": "employed_good",
                  "hands_on_technical": True, "builds_things": True,
                  "professional": {"domain": "carpentry", "industry": "construction",
                                   "activities": ["framing", "finish work"]}},
    "founder": {"current_occupation_title": "startup founder", "current_status": "founder",
                "commercial_evidence": True, "builds_things": True,
                "professional": {"domain": "software", "industry": "software",
                                 "activities": ["sales", "product"]}},
    "student": {"current_status": "student", "studies_field": "engineering",
                "works_with_software": True, "independent_projects": True,
                "professional": {"domain": "engineering", "activities": ["python projects"]}},
    "teacher": {"current_occupation_title": "school teacher", "current_status": "employed_good",
                "professional": {"domain": "teaching", "industry": "education",
                                 "activities": ["lesson planning", "instruction"]}},
    "no_occupation": {"current_status": "between",
                      "professional": {"activities": ["organizing community events"]}},
}


def test_profiles_differ_materially(db):
    """The key test: change the questionnaire, change the discovered set."""
    outs = {name: run_pipeline(db, ctx) for name, ctx in PROFILES.items()}
    for name, out in outs.items():
        assert out["recommendations"], f"{name} must get recommendations"
        assert out["profile"]["basis"] in ("llm", "deterministic_fallback")
    title_sets = {name: {r["title"] for r in out["recommendations"]}
                  for name, out in outs.items()}
    pairs = [("doctor", "carpenter"), ("doctor", "founder"), ("carpenter", "teacher"),
             ("psychiatrist_founder", "student")]
    for a, b in pairs:
        shared = title_sets[a] & title_sets[b]
        assert len(shared) < min(len(title_sets[a]), len(title_sets[b])), \
            f"{a} and {b} received essentially the same recommendations"


def test_doctor_gets_healthcare_ai_not_generic_software(db):
    out = run_pipeline(db, PROFILES["doctor"])
    t = titles(out)
    assert any(w in t for w in ("healthcare", "medicine", "clinical", "medical")), t
    assert "ai" in t
    # not mostly generic software jobs
    generic = sum(1 for r in out["recommendations"]
                  if "software engineer" in r["title"].lower())
    assert generic <= len(out["recommendations"]) // 2


def test_carpenter_stays_in_their_world(db):
    out = run_pipeline(db, PROFILES["carpenter"])
    t = titles(out)
    assert any(w in t for w in ("construction", "carpentry", "craft", "trade",
                                "estimation", "fabrication")), t
    assert "software engineer —" not in t


def test_founder_gets_business_opportunities(db):
    out = run_pipeline(db, PROFILES["founder"])
    assert any(r["type"] == "business" for r in out["recommendations"]), \
        "an operating founder must see business opportunities, not only jobs"


def test_psychiatrist_with_intent_gets_business_and_domain(db):
    out = run_pipeline(db, PROFILES["psychiatrist_founder"])
    types = {r["type"] for r in out["recommendations"]}
    assert "business" in types
    t = titles(out)
    assert any(w in t for w in ("psychiatry", "mental", "health", "clinical")), t


def test_no_occupation_still_gets_grounded_output(db):
    out = run_pipeline(db, PROFILES["no_occupation"])
    assert out["recommendations"], "no formal occupation must not mean no output"
    for r in out["recommendations"]:
        assert r["skillOverlap"]["overall"] >= 0
        assert r["evidenceState"] in ("HIGH_CONFIDENCE", "MODERATE_CONFIDENCE",
                                      "LIMITED_EVIDENCE", "INSUFFICIENT_DATA")


def test_teacher_and_student_paths(db):
    t_teacher = titles(run_pipeline(db, PROFILES["teacher"]))
    assert any(w in t_teacher for w in ("education", "teaching", "learning", "instruction")), t_teacher
    t_student = titles(run_pipeline(db, PROFILES["student"]))
    assert "ai" in t_student


# ---------------- honesty and arithmetic ----------------

def test_every_recommendation_carries_score_breakdown_and_state(db):
    out = run_pipeline(db, PROFILES["doctor"])
    from app.intelligence import ranker
    for r in out["recommendations"]:
        bd = r["scoreBreakdown"]
        assert bd["weights"] == ranker.WEIGHTS
        # reproducible: recomputing from the shipped components gives the score
        recomputed = round(sum(ranker.WEIGHTS[k] * float(bd["components"][k] or 0)
                               for k in ranker.WEIGHTS) * 100)
        assert recomputed == r["score"]
        # separate metrics, never conflated
        assert {"aiLeverage", "automationRisk", "humanAdvantage"} <= set(r["impact"])
        if not r["evidence"]:
            assert r["evidenceState"] == "INSUFFICIENT_DATA"
        if r["demand"]["direction"] == "unknown":
            assert r["demand"]["note"], "unknown demand must say so"


def test_growth_is_arithmetic_never_invented():
    from app.intelligence import growth
    assert growth.pct_change(150, 100)["pct"] == 50.0
    assert growth.pct_change(100, None)["state"] == "insufficient"
    assert growth.pct_change(100, 0)["state"] == "insufficient"
    yoy = growth.yoy_from_periods([{"year": 2024, "value": 18420},
                                   {"year": 2025, "value": 27140},
                                   {"year": 2026, "value": 38920}])
    assert yoy["state"] == "ok"
    assert yoy["yoy"]["2025"] == 47.3 or abs(yoy["yoy"]["2025"] - 47.3) < 0.2
    assert growth.yoy_from_periods([{"year": 2026, "value": 10}])["state"] == "insufficient"


def test_posting_normalization_and_windows(db):
    """Live evidence arithmetic over stored postings: dedupe, clustering,
    rolling windows, and no growth claim without a baseline period."""
    from app.intelligence import market
    now = datetime.utcnow()
    items = []
    for i, (title, days_ago) in enumerate([
            ("Agentic AI Engineer", 5), ("AI Agent Engineer", 10),
            ("Senior LLM Agent Engineer", 20), ("AI Agent Engineer", 40),
            ("Agentic AI Engineer", 50)]):
        items.append({"title": title, "organization": f"Co{i}",
                      "locations_derived": ["Austin, Texas, United States"],
                      "url": f"https://example.com/job/{i}",
                      "date_posted": (now - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S"),
                      "ai_key_skills": ["python", "llm"]})
    stored = market.store_postings(db, items, "agentic ai", "*")
    assert stored == 5
    # duplicate content is not stored twice
    assert market.store_postings(db, items, "agentic ai", "*") == 0
    # the three title variants cluster together
    assert market.cluster_key("Agentic AI Engineer") == market.cluster_key("AI Agent Engineer")
    w = market.window_counts(db, query="agentic ai")
    assert w["30d"]["current"] == 3 and w["30d"]["previous"] == 2
    from app.intelligence import growth
    cmp = growth.window_comparison(w)
    assert cmp["30d"]["state"] == "ok" and cmp["30d"]["pct"] == 50.0
    stats = market.query_stats(db, "agentic ai")
    assert stats["postings"] == 5 and stats["companies"] == 5
    assert stats["sampleUrls"], "posting URLs must be retained"


def test_emerging_cluster_detection(db):
    from app.intelligence import market
    now = datetime.utcnow()
    items = [{"title": t, "organization": f"Emp{i}", "url": f"https://x.io/{i}",
              "date_posted": (now - timedelta(days=3 + i)).strftime("%Y-%m-%d")}
             for i, t in enumerate(["AI Workflow Engineer", "Senior AI Workflow Engineer",
                                    "AI Workflow Engineer", "Workflow AI Engineer",
                                    "AI Workflow Engineer", "Workflow AI Engineer"])]
    market.store_postings(db, items, "ai workflow", "*")
    clusters = market.emerging_clusters(db, min_postings=4, min_companies=3)
    assert any("workflow" in c["cluster"] for c in clusters), clusters


def test_live_market_never_runs_in_tests_and_token_never_leaks(db):
    from app.intelligence import market, pipeline
    ok, why = market.live_available(db)
    assert not ok and "test" in why
    out = run_pipeline(db, PROFILES["founder"])
    blob = json.dumps(out)
    import os
    token = os.environ.get("APIFY_TOKEN")
    if token:
        assert token not in blob
    assert "apify_token" not in blob.lower().replace(" ", "")


def test_recommendations_cached_until_profile_changes(db):
    from app.intelligence import pipeline
    s = make_session(db, practical=dict(PROFILES["teacher"]))
    first = pipeline.run(db, s)
    again = pipeline.run(db, s)
    assert again["cache"]["hit"] is True
    # answering more questions changes the profile hash → recompute
    pc = dict(s.practical_context)
    pc["commercial_evidence"] = True
    s.practical_context = pc
    db.flush()
    third = pipeline.run(db, s)
    assert third["cache"]["hit"] is False


def test_api_endpoint_gated_and_shaped(client):
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    r = client.get(f"/v1/discover/sessions/{sid}/intelligence/recommendations")
    assert r.status_code == 409, "the pipeline opens only after the story completes"
