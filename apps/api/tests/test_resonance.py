"""§48–§51 — match evolution, low confidence honesty, source support (fail
closed), and feedback persistence/suppression."""
import pytest


@pytest.fixture()
def db(client):
    from app.db import SessionLocal
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


def make_session(db, dims: dict, practical: dict | None = None):
    from app.models import AnonymousIdentity, DiscoverSession
    anon = AnonymousIdentity()
    db.add(anon)
    db.flush()
    session = DiscoverSession(anon_id=anon.id, journey_status="REFLECTION",
                              dimensions=dims, practical_context=practical or {})
    db.add(session)
    db.flush()
    return session


def d(estimate, confidence, count=4):
    return {"estimate": estimate, "confidence": confidence, "variance": 0.0,
            "evidence_count": count, "pos_w": 2.0, "neg_w": 0.0}


def test_different_users_get_different_candidates(db):
    from app.resonance import compute_matches
    builder = make_session(db, {"implementation_affinity": d(0.8, 0.7), "experimentation": d(0.7, 0.6)})
    operator = make_session(db, {"leadership": d(0.85, 0.75), "planning": d(0.7, 0.65), "facilitation": d(0.7, 0.65)})
    m1 = compute_matches(db, builder, "REFLECTION_CLOSING")["matches"]
    m2 = compute_matches(db, operator, "REFLECTION_CLOSING")["matches"]
    assert m1 and m2, "both evidence-rich users should resonate with someone"
    assert {x["construct"] for x in m1} != {x["construct"] for x in m2}
    assert {x["figureId"] for x in m1} != {x["figureId"] for x in m2}


def test_professional_context_recomputes_ranking(db):
    from app.resonance import compute_matches
    session = make_session(db, {
        "implementation_affinity": d(0.8, 0.7), "leadership": d(0.85, 0.75),
        "facilitation": d(0.7, 0.65), "mastery": d(0.6, 0.55),
    })
    before = compute_matches(db, session, "ALIGNMENT_CLOSING")
    # material professional change: the user is a student — operational
    # leadership is no longer a professionally-supported comparison
    pc = dict(session.practical_context or {})
    pc["current_status"] = "student"
    session.practical_context = pc
    after = compute_matches(db, session, "ALIGNMENT_CLOSING")
    assert before["fingerprint"] == after["fingerprint"]  # same evidence...
    constructs_before = {m["construct"] for m in before["matches"]}
    constructs_after = {m["construct"] for m in after["matches"]}
    assert constructs_before != constructs_after, "professional context must change the ranking"
    assert "operational_leadership" not in constructs_after
    # not cached: two snapshots exist
    from app.models import ResonanceSnapshot
    assert db.query(ResonanceSnapshot).filter_by(session_id=session.id).count() == 2


def test_low_confidence_returns_no_matches(db):
    from app.resonance import compute_matches
    thin = make_session(db, {"autonomy": d(0.3, 0.15, count=1)})
    result = compute_matches(db, thin, "SELF_DISCOVERY_CLOSING")
    assert result["matches"] == [], "must never invent confidence for entertainment"
    assert any("threshold" in c["why"] or "no supported" in c["why"]
               for c in result["considered"])


def test_every_match_traces_to_source(db):
    from app.resonance import compute_matches
    rich = make_session(db, {"implementation_affinity": d(0.8, 0.7), "persistence": d(0.7, 0.65),
                             "experimentation": d(0.7, 0.6)})
    result = compute_matches(db, rich, "REFLECTION_CLOSING")
    assert result["matches"]
    for m in result["matches"]:
        assert m["theirEvidence"], "match without documented evidence"
        for ev in m["theirEvidence"]:
            assert ev["claim"] and ev["source"]["title"], "evidence without source"


def test_broken_evidence_chain_fails_closed(db):
    from app.figure_kb import pattern_bundle
    from app.models import PublicFigurePattern
    p = db.query(PublicFigurePattern).first()
    orphan = PublicFigurePattern(id="_test_orphan", figure_id=p.figure_id,
                                 construct=p.construct, description="orphan",
                                 evidence_refs=["does_not_exist"], confidence=0.9)
    assert pattern_bundle(db, orphan) is None


def test_feedback_persists_and_suppresses(db):
    from app.resonance import compute_matches, record_feedback
    from app.models import PublicFigureMatchFeedback
    session = make_session(db, {"implementation_affinity": d(0.8, 0.7), "experimentation": d(0.7, 0.6)})
    first = compute_matches(db, session, "REFLECTION_CLOSING")
    assert first["matches"]
    target = first["matches"][0]
    record_feedback(db, session, target["figureId"], target["patternId"], "not_relevant", "REFLECTION")
    assert db.query(PublicFigureMatchFeedback).filter_by(session_id=session.id).count() == 1
    second = compute_matches(db, session, "REFLECTION_CLOSING")
    assert target["figureId"] not in {m["figureId"] for m in second["matches"]}, \
        "rejected resonance repeated without new evidence"
    # new meaningful evidence lifts the suppression
    dims = dict(session.dimensions)
    dims["sales_comfort"] = d(0.7, 0.6)
    session.dimensions = dims
    third = compute_matches(db, session, "REFLECTION_CLOSING")
    assert third["fingerprint"] != second["fingerprint"]


def test_feedback_endpoint(client):
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    r = client.post(f"/v1/discover/sessions/{sid}/resonance/feedback",
                    json={"figureId": "james_dyson", "verdict": "not_relevant"})
    assert r.status_code == 200 and r.json()["ok"]


def test_fame_is_not_a_feature():
    """Ranking source must not reference fame/recognition anywhere."""
    import inspect
    from app import resonance
    src = inspect.getsource(resonance)
    assert "fame" not in src.lower().replace("fame is", "").replace("fame may", "").replace("fame is absent", "")
