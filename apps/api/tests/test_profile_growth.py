"""Profile Growth Intelligence: capability penetration is arithmetic over
stored postings, growth types are classified deterministically, the score is
reproducible, percentage points never masquerade as relative percent, and no
profile is forced toward software engineering."""
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


def make_session(db, practical=None):
    from app.models import AnonymousIdentity, DiscoverSession
    anon = AnonymousIdentity()
    db.add(anon)
    db.flush()
    s = DiscoverSession(anon_id=anon.id, journey_status="DISCOVER_WORKSPACE",
                        dimensions={}, practical_context=practical or {}, counters={})
    db.add(s)
    db.flush()
    return s


PSYCHIATRIST = {"current_occupation_title": "psychiatrist", "current_status": "employed_good",
                "professional": {"domain": "psychiatry", "industry": "healthcare",
                                 "activities": ["clinical assessment", "therapy"]}}
CARPENTER = {"current_occupation_title": "carpenter", "current_status": "employed_good",
             "hands_on_technical": True, "builds_things": True,
             "professional": {"domain": "carpentry", "industry": "construction",
                              "activities": ["framing", "estimation"]}}


def seed_postings(db, spec, query="growth-test"):
    """spec: list of (title, skills, description, days_ago) — synthetic
    observations the arithmetic is checked against."""
    from app.intelligence import market
    now = datetime.utcnow()
    items = [{"title": t, "organization": f"Org{i}", "url": f"https://x.io/{query}/{i}",
              "ai_key_skills": sk, "description_text": desc,
              "date_posted": (now - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%S")}
             for i, (t, sk, desc, d) in enumerate(spec)]
    return market.store_postings(db, items, query, "*")


# ---------------- arithmetic ----------------

def test_pp_and_relative_change_are_distinct_and_correct():
    from app.intelligence import growth
    out = growth.penetration_change(571, 4200, 312, 4200)
    assert out["state"] == "ok"
    assert out["currentSharePct"] == 13.6 and out["previousSharePct"] == 7.4
    assert out["ppChange"] == 6.2 and out["ppChangeUnit"] == "percentage_points"
    # 83.0 from unrounded shares — (571−312)/312; rounding shares first would
    # give 83.8, which is the less accurate figure
    assert abs(out["relativeChangePct"] - 83.0) < 0.2
    assert out["relativeChangeUnit"] == "relative_percent"


def test_penetration_needs_a_real_sample():
    from app.intelligence import growth
    assert growth.penetration_change(3, 5, 1, 4)["state"] == "insufficient"
    out = growth.penetration_change(5, 20, 0, 20)
    assert out["state"] == "ok" and out["relativeChangePct"] is None
    assert "baseline" in out["relativeNote"]


def test_capability_mentions_count_across_title_skills_description(db):
    from app.intelligence import market, profile_growth
    n = 14
    spec = []
    # current 30d: 12 postings, 6 mention ai automation; previous 30d: 12, 2 mention
    for i in range(12):
        spec.append(("Operations Manager", ["excel"],
                     "designs ai automation workflows" if i < 6 else "manages the team", 5 + i % 20))
    for i in range(12):
        spec.append(("Operations Manager", ["excel"],
                     "ai automation pilot" if i < 2 else "keeps operations running", 35 + i % 20))
    assert seed_postings(db, spec, query="ops-growth") == 24
    postings = market.recent_postings(db)
    read = profile_growth.measure_capability(postings, "ai automation", ["ai automation"])
    w30 = read["penetration"]["30d"]
    assert w30["currentMentions"] == 6 and w30["previousMentions"] == 2
    assert read["growthSignal"] in ("ACCELERATING_GROWTH", "STRUCTURAL_GROWTH", "EMERGING")
    assert read["evidence"], "a measured capability must carry its observations"
    ev = read["evidence"][0]
    assert ev["ppChangeUnit"] == "percentage_points"
    assert ev["relativeChangeUnit"] == "relative_percent"


def test_growth_classification_types(db):
    from app.intelligence import profile_growth
    ok = lambda pp, pp30=None: {"state": "ok", "ppChange": pp,
                                "currentTotal": 50, "previousTotal": 50,
                                "currentSharePct": 10 + pp, "previousSharePct": 10}
    insufficient = {"state": "insufficient"}
    pen = {"90d": {"currentMentions": 0, "currentTotal": 0},
           "12m": {"previousTotal": 50}}
    assert profile_growth.classify_growth(
        {"90d": {"currentMentions": 0, "currentTotal": 0}, "12m": {"previousTotal": 0}},
        {"30d": insufficient, "90d": insufficient, "12m": insufficient}) == "INSUFFICIENT_DATA"
    # dense recent presence, no measurable history → EMERGING
    assert profile_growth.classify_growth(
        {"90d": {"currentMentions": 10, "currentTotal": 20}, "12m": {"previousTotal": 0}},
        {"30d": insufficient, "90d": insufficient, "12m": insufficient}) == "EMERGING"
    assert profile_growth.classify_growth(pen, {"30d": ok(1.0), "90d": ok(1.0), "12m": ok(3.0)}) \
        == "STRUCTURAL_GROWTH"
    assert profile_growth.classify_growth(pen, {"30d": ok(8.0), "90d": ok(4.0), "12m": ok(3.0)}) \
        == "ACCELERATING_GROWTH"
    assert profile_growth.classify_growth(pen, {"30d": ok(-2.0), "90d": ok(-3.0), "12m": ok(-2.5)}) \
        == "DECLINING"
    assert profile_growth.classify_growth(pen, {"30d": ok(0.2), "90d": ok(0.1), "12m": ok(0.5)}) \
        == "STABLE"


# ---------------- the analyzer ----------------

def test_analyzer_produces_full_honest_payload(db):
    from app.intelligence import profile_growth
    s = make_session(db, dict(PSYCHIATRIST))
    out = profile_growth.analyze(db, s)
    assert out["trajectory"] in ("ACCELERATING", "STABLE", "AT_RISK", "EMERGING",
                                 "INSUFFICIENT_DATA")
    assert out["confidence"] in ("HIGH", "MODERATE", "LIMITED", "INSUFFICIENT")
    for c in out["capabilities"]:
        assert c["growthSignal"] in profile_growth.GROWTH_SIGNALS
        if not c["evidence"]:
            assert c["growth"] is None, "no evidence must mean no growth number"
    sc = out["profileGrowthScore"]
    assert sc["weights"] == profile_growth.SCORE_WEIGHTS
    recomputed = round(sum(profile_growth.SCORE_WEIGHTS[k] * sc["breakdown"][k] / 100
                           for k in profile_growth.SCORE_WEIGHTS) * 100)
    assert abs(recomputed - sc["score"]) <= 1, "score must be reproducible from its breakdown"
    ex = out["explanation"]
    assert ex["trajectoryReading"] and ex["whatIsBecomingValuable"]


def test_plans_differ_and_carpenter_is_not_sent_to_software(db):
    from app.intelligence import profile_growth
    a = profile_growth.analyze(db, make_session(db, dict(PSYCHIATRIST)))
    b = profile_growth.analyze(db, make_session(db, dict(CARPENTER)))
    qa = " ".join(q["query"].lower() for q in a["plan"]["queries"])
    qb = " ".join(q["query"].lower() for q in b["plan"]["queries"])
    assert qa != qb, "different profiles must research different things"
    assert "software engineer" not in qb and "coding" not in qb
    assert any(w in qb for w in ("carpentry", "construction", "craft", "installation",
                                 "physical", "estimat", "wood")), qb


def test_cached_until_profile_changes(db):
    from app.intelligence import profile_growth
    s = make_session(db, dict(CARPENTER))
    first = profile_growth.analyze(db, s)
    assert profile_growth.analyze(db, s)["cache"]["hit"] is True
    pc = dict(s.practical_context)
    pc["commercial_evidence"] = True
    s.practical_context = pc
    db.flush()
    assert profile_growth.analyze(db, s)["cache"]["hit"] is False


def test_no_invented_numbers_in_fallback_explanation(db):
    """The fallback explanation may only surface numbers the measurement layer
    produced; with an empty market it must contain no growth figures at all."""
    import re
    from app.intelligence import profile_growth
    out = profile_growth.analyze(db, make_session(db, dict(PSYCHIATRIST)))
    if all(not c["evidence"] for c in out["capabilities"]):
        text = " ".join(str(out["explanation"].get(k, "")) for k in
                        ("whatIsBecomingValuable", "trajectoryReading"))
        assert not re.search(r"[+-]?\d+(\.\d+)?\s*%", text), \
            f"growth percentage with no evidence behind it: {text}"


def test_endpoint_gated(client):
    sid = client.post("/v1/discover/sessions", json={}).json()["sessionId"]
    assert client.get(f"/v1/discover/sessions/{sid}/intelligence/growth").status_code == 409
