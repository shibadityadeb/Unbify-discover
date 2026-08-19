"""Non-negotiable acceptance tests for the adaptive experience fix."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import DiscoverSession
from app.orchestrator import _eligibility
from app.professional import apply_extracted_facts, heuristic_extract
from app.catalog import INTERACTIONS


def make_session(state="ALIGNMENT", practical=None):
    return DiscoverSession(id="t", anon_id="a", journey_status=state,
                           dimensions={}, contradictions=[], practical_context=practical or {},
                           counters={}, engagement={}, used_definitions=[],
                           recent_interaction_types=[], revealed_insights=[])


def _def(defid):
    return next(d for d in INTERACTIONS if d["id"] == defid)


def test_A_student_never_gets_career_tenure_questions():
    s = make_session(practical={"current_status": "student"})
    assert _eligibility(s, _def("sp_years")) == "incompatible_with_professional_status"
    assert _eligibility(s, _def("sc_biz_stage")) == "incompatible_with_professional_status"
    assert _eligibility(s, _def("sc_own_scope")) == "incompatible_with_professional_status"
    assert _eligibility(s, _def("sc_student_real")) is None  # student space activates


def test_B_rich_answer_eliminates_future_questions():
    s = make_session(practical={})
    facts = heuristic_extract("I'm a CS student and have freelanced building websites for local businesses for one year.")
    changed = apply_extracted_facts(s, facts)
    assert len(changed) >= 3, "one natural answer must close multiple uncertainties"
    assert s.practical_context["current_status"] == "student"
    # the direct status question is now redundant
    assert _eligibility(s, _def("al_status")) == "already_answered_explicitly"
    # and tenure questions are incompatible
    assert _eligibility(s, _def("sp_years")) == "incompatible_with_professional_status"


def test_C_different_answers_change_next_action(client):
    """Two sessions answering the status question differently must diverge."""
    def to_alignment(sid):
        data = client.get(f"/v1/discover/sessions/{sid}/next").json()
        for _ in range(60):
            it = data["interaction"]
            if data["state"] == "ALIGNMENT" and it["type"] == "scenario_choice" \
                    and "professionally" in (it.get("headline") or ""):
                return data
            if it["type"] in ("chapter_transition", "chapter_closing"):
                data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": it["next"]}).json()
                continue
            from tests.test_journey import drive_response
            data = client.post(f"/v1/discover/sessions/{sid}/responses",
                               json={"interactionId": it["id"], "response": drive_response(it)}).json()
        raise AssertionError("never reached the status question")

    def collect_headlines(sid, data, answer_id, n=8):
        it = data["interaction"]
        data = client.post(f"/v1/discover/sessions/{sid}/responses",
                           json={"interactionId": it["id"], "response": {"optionId": answer_id}}).json()
        seen = set()
        from tests.test_journey import drive_response
        for _ in range(n):
            it = data["interaction"]
            if it["type"] in ("chapter_transition", "chapter_closing"):
                data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": it["next"]}).json()
                continue
            if it.get("headline"):
                seen.add(it["headline"])
            data = client.post(f"/v1/discover/sessions/{sid}/responses",
                               json={"interactionId": it["id"], "response": drive_response(it)}).json()
        return seen

    sid1 = client.post("/v1/discover/sessions", json={}).json()["sessionId"]
    sid2 = client.post("/v1/discover/sessions", json={}).json()["sessionId"]
    d1 = to_alignment(sid1)
    d2 = to_alignment(sid2)
    h_founder = collect_headlines(sid1, d1, "founder")
    h_student = collect_headlines(sid2, d2, "student")
    assert h_founder != h_student, "answers must materially influence what comes next"
    assert not any("years" in h.lower() for h in h_student), "students never get tenure questions"


def test_D_no_repeated_bridges(client):
    from tests.test_journey import drive_response
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    bridges = []
    for _ in range(80):
        it = data["interaction"]
        if it.get("bridge"):
            bridges.append(it["bridge"])
        if it["type"] == "workspace":
            break
        if it["type"] in ("chapter_transition", "chapter_closing"):
            data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": it["next"]}).json()
            continue
        if it["type"] in ("story_close", "materialization"):
            data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": it["next"]}).json()
            continue
        data = client.post(f"/v1/discover/sessions/{sid}/responses",
                           json={"interactionId": it["id"], "response": drive_response(it)}).json()
    assert len(bridges) == len(set(bridges)), f"repeated narrative bridges: {bridges}"


def test_E_manual_chapter_progression(client):
    """Chapter closing waits indefinitely; only explicit continue advances."""
    from tests.test_journey import drive_response
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    for _ in range(40):
        it = data["interaction"]
        if it["type"] == "chapter_closing":
            break
        if it["type"] == "chapter_transition":
            data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": it["next"]}).json()
            continue
        data = client.post(f"/v1/discover/sessions/{sid}/responses",
                           json={"interactionId": it["id"], "response": drive_response(it)}).json()
    assert data["state"] == "SELF_DISCOVERY_CLOSING"
    assert data["interaction"]["sections"], "closing must carry readable content"
    assert data["interaction"]["cta"]
    # polling next repeatedly must NOT advance anything (no timers server-side)
    for _ in range(3):
        again = client.get(f"/v1/discover/sessions/{sid}/next").json()
        assert again["state"] == "SELF_DISCOVERY_CLOSING"
        assert again["interaction"]["type"] == "chapter_closing"
    # only the explicit continue moves the story
    adv = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": "REFLECTION"}).json()
    assert adv["state"] == "REFLECTION"


def test_G_no_chapter_script_sent(client):
    data = client.post("/v1/discover/sessions", json={}).json()
    assert isinstance(data["interaction"], dict), "exactly one authoritative interaction"
    assert "interactions" not in data and "questions" not in data
    sid = data["sessionId"]
    data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": "SELF_DISCOVERY"}).json()
    it = data["interaction"]
    assert isinstance(it, dict) and it.get("type") != "list"
    assert "interactions" not in data
