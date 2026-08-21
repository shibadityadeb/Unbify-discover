"""§52-54 QA: Transformation stays evidence-driven and non-prescriptive;
Materialization produces real objects that differ by profession; product
routing only appears with a complete need→evidence→gap→capability chain."""
import pytest

from app.content_policy import validate


def drive(it, reflection):
    t = it["type"]
    if t in ("visual_choice", "scenario_choice", "clarification"):
        return {"optionId": it["options"][0]["id"]}
    if t in ("binary_tension", "spectrum"):
        return {"value": 0.8}
    if t in ("forced_rank", "object_sort"):
        return {"optionIds": [o["id"] for o in it["options"][: it.get("maxSelect", 3)]]}
    if t == "micro_reflection":
        return {"text": reflection}
    if t == "reveal":
        return {"optionId": it["calibration"][0]["id"]}
    if t == "possible_lives":
        return {"optionId": it["options"][0]["id"]}
    if t == "final":
        return {"done": True}
    raise AssertionError(f"unhandled {t}")


def run_to_materialization(client, reflection):
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": "SELF_DISCOVERY"}).json()
    final = None
    for _ in range(90):
        it = data["interaction"]
        if it["type"] == "chapter_closing" and it["layout"] == "reconstruction":
            final = {"beats": [b for b in it["beats"] if b.get("type") != "closing"],
                     "closing": [b["text"] for b in it["beats"] if b.get("type") == "closing"],
                     "cta": it["cta"]}
        if it["type"] == "materialization":
            return sid, final, it
        if it["type"] in ("chapter_transition", "chapter_closing", "story_close"):
            data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": it["next"]}).json()
            continue
        data = client.post(f"/v1/discover/sessions/{sid}/responses",
                           json={"interactionId": it["id"], "response": drive(it, reflection),
                                 "elapsedMs": 2000}).json()
    raise AssertionError("never reached materialization")


ELECTRICIAN = ("I'm an electrician. I run my own small electrical business, do installations "
               "myself, quote the jobs, one apprentice, customers pay me directly.")
STUDENT = ("I'm a computer science student. I build small apps that real people use and "
           "I've been paid by two local businesses.")


# ---------------- §2/§3/§52: Transformation quality ----------------

def test_transformation_has_no_generic_next_step(client):
    sid, final, mat = run_to_materialization(client, ELECTRICIAN)
    assert final is not None
    blob = " ".join(b["text"] for b in final["beats"]).lower()
    assert "nextAction" not in final, "the final mirror must not prescribe activity"
    assert final["closing"], "the story must still close emotionally"
    for banned in ("two focused hours", "two honest hours", "give it two"):
        assert banned not in blob, f"generic next-step advice leaked: {banned}"
    assert final["cta"] == "See what this can become →"


def test_transformation_fills_no_predefined_slots(client):
    sid, final, mat = run_to_materialization(client, ELECTRICIAN)
    labels = {b.get("label") for b in final["beats"]}
    forbidden = {"Your natural energy", "How you create value", "What you protect",
                 "Your unusual edge", "Your current reality", "What may be holding you back"}
    assert not (labels & forbidden), f"mandatory personality slots reappeared: {labels & forbidden}"
    # beat types come from evidence, and are never all present by construction
    types = [b["type"] for b in final["beats"]]
    assert len(types) == len(set(types)) or len(types) <= 6
    # evidence-driven beats only: story beats, plus the material ones
    # (leverage / external example). No personality slots.
    assert all(t in ("survived", "changed", "reality", "have", "unclear", "honest",
                     "leverage", "quote", "same_principle") for t in types)


def test_transformation_is_not_prescriptive(client):
    sid, final, mat = run_to_materialization(client, ELECTRICIAN)
    for b in final["beats"]:
        assert validate(b["text"]), f"content policy violation: {b['text']}"
    for line in final["closing"]:
        assert validate(line)
    closing_text = " ".join(final["closing"]).lower()
    # the disclaimer must be there; its exact wording is free to change
    assert "not a verdict" in closing_text or "isn't a verdict" in closing_text


def test_transformation_surfaces_uncertainty(client):
    sid, final, mat = run_to_materialization(client, ELECTRICIAN)
    types = {b["type"] for b in final["beats"]}
    assert "unclear" in types or "honest" in types, "hiding uncertainty is a QA failure"


# ---------------- §53: Materialization quality ----------------

def test_materialization_has_real_objects(client):
    sid, final, mat = run_to_materialization(client, ELECTRICIAN)
    assert mat["capabilities"], "no capability objects"
    assert mat["leverage"], "no leverage/assets"
    assert mat["gaps"], "no gaps"
    assert mat["directions"], "no direction objects"
    assert mat["position"]["context"] or mat["position"]["evidence"]
    for d in mat["directions"]:
        assert d["whyThisAppeared"] and d["experiment"]["action"], "direction without why/experiment"
        assert d["experiment"]["teaches"], "experiment that teaches nothing"
        assert d["marketEvidence"]
        assert d["rankingFactors"], "recommendation must be explainable"


def test_experiments_are_specific_not_generic(client):
    sid, final, mat = run_to_materialization(client, ELECTRICIAN)
    actions = [d["experiment"]["action"] for d in mat["directions"]]
    assert len(actions) == len(set(actions)), f"experiments repeat across directions: {actions}"
    for a in actions:
        assert "two hours" not in a.lower(), f"generic experiment: {a}"
        assert len(a.split()) >= 6, f"experiment too thin to act on: {a}"


def test_materialization_differs_by_profession(client):
    _, _, elec = run_to_materialization(client, ELECTRICIAN)
    _, _, stud = run_to_materialization(client, STUDENT)
    elec_caps = {c["key"] for c in elec["capabilities"]}
    stud_caps = {c["key"] for c in stud["capabilities"]}
    assert elec_caps != stud_caps, "capability maps identical across professions"
    elec_dirs = {d["key"] for d in elec["directions"]}
    stud_dirs = {d["key"] for d in stud["directions"]}
    assert elec_dirs != stud_dirs, "directions identical across professions"


def test_material_objects_persist_and_save(client):
    sid, final, mat = run_to_materialization(client, ELECTRICIAN)
    key = mat["directions"][0]["key"]
    r = client.post(f"/v1/discover/sessions/{sid}/objects/status",
                    json={"kind": "direction", "key": key, "status": "saved"})
    assert r.status_code == 200 and r.json()["saved"] is True
    saved = client.get(f"/v1/discover/sessions/{sid}/saved").json()["saved"]
    assert any(s["key"] == key for s in saved), "saved objects must persist"


def test_dismissal_is_feedback_not_error(client):
    sid, final, mat = run_to_materialization(client, ELECTRICIAN)
    key = mat["directions"][-1]["key"]
    r = client.post(f"/v1/discover/sessions/{sid}/objects/status",
                    json={"kind": "direction", "key": key, "status": "dismissed",
                          "reason": "not what I want"})
    assert r.status_code == 200
    from app.db import SessionLocal
    from app.models import MaterialObject, NarrativeEvent
    with SessionLocal() as db:
        row = (db.query(MaterialObject)
               .filter_by(session_id=sid, kind="direction", key=key).first())
        assert row.status == "dismissed" and row.dismissal_reason == "not what I want"
        events = [e.type for e in db.query(NarrativeEvent).filter_by(session_id=sid)]
        assert "USER_CORRECTED_SYSTEM" in events, "dismissal must feed ranking feedback"


def test_experiment_outcome_becomes_strong_evidence(client):
    sid, final, mat = run_to_materialization(client, ELECTRICIAN)
    key = mat["directions"][0]["key"]
    started = client.post(f"/v1/discover/sessions/{sid}/experiments/{key}/start", json={}).json()
    assert started["ok"] and started["action"]
    r = client.post(f"/v1/discover/sessions/{sid}/experiments/{started['experimentId']}/outcome",
                    json={"verdict": "promising", "note": "two people said yes", "earned": True})
    assert r.status_code == 200
    from app.db import SessionLocal
    from app.models import EvidenceItem
    with SessionLocal() as db:
        outcomes = db.query(EvidenceItem).filter_by(session_id=sid, kind="outcome").all()
        assert outcomes, "experiment outcomes must enter the evidence ledger"
        assert outcomes[0].reliability >= 0.85, "outcome evidence must outrank inference"


# ---------------- §54: product routing quality ----------------

def test_product_routes_require_full_evidence_chain(client):
    sid, final, mat = run_to_materialization(client, ELECTRICIAN)
    from app.db import SessionLocal
    from app.models import ProductRouteRecord
    with SessionLocal() as db:
        rows = db.query(ProductRouteRecord).filter_by(session_id=sid).all()
        for row in rows:
            assert row.user_need, "route without a user need"
            assert row.gap, "route without a capability/action gap"
            assert row.explanation_evidence_ids, "route without evidence"
            assert row.reason_codes, "route without reason codes"
            assert row.relevance_score >= 0.45
    for r in mat["productRoutes"]:
        assert r["capability"] in ("career", "marketplace", "agency", "suite", "brain")
        # contextual presentation: the need comes before the product
        assert r["because"] and r["gap"] and r["optional"]
        assert not r["because"].lower().startswith("recommended product")


def test_no_products_without_evidence(client):
    """A session with almost nothing must surface no products at all."""
    from app.db import SessionLocal
    from app.models import AnonymousIdentity, DiscoverSession
    from app import products
    with SessionLocal() as db:
        anon = AnonymousIdentity()
        db.add(anon)
        db.flush()
        s = DiscoverSession(anon_id=anon.id, journey_status="MATERIALIZATION",
                            dimensions={}, practical_context={}, counters={})
        db.add(s)
        db.flush()
        routes = products.route(db, s, {"directions": [], "gaps": [], "leverage": [],
                                        "openQuestionCount": 0})
        assert routes == [], "products must never appear without an evidence chain"
        db.rollback()


def test_workspace_still_reachable_and_value_not_gated(client):
    sid, final, mat = run_to_materialization(client, ELECTRICIAN)
    from tests.ownership import claim
    claim(client, sid)
    data = client.post(f"/v1/discover/sessions/{sid}/advance",
                       json={"to": "DISCOVER_WORKSPACE"}).json()
    assert data["state"] == "DISCOVER_WORKSPACE"
    # materialization objects remain available from the workspace
    m2 = client.get(f"/v1/discover/sessions/{sid}/materialization")
    assert m2.status_code == 200 and m2.json()["directions"]


# ---------------- §22/§23/§25: workspace questions and action ranking ----------------

def test_questions_explain_what_they_would_change(client):
    sid, final, mat = run_to_materialization(client, ELECTRICIAN)
    from tests.ownership import claim
    claim(client, sid)
    client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": "DISCOVER_WORKSPACE"})
    ws = client.get(f"/v1/workspace/{sid}").json()
    invite = ws["questions"]["invite"]
    assert invite and "Question" not in invite, "questions must not read like a form"
    assert any(w in invite.lower() for w in ("would change", "useful", "sharpen", "decides",
                                             "worth exploring")), invite


def test_actions_are_ranked_with_a_most_useful(client):
    sid, final, mat = run_to_materialization(client, ELECTRICIAN)
    from tests.ownership import claim
    claim(client, sid)
    client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": "DISCOVER_WORKSPACE"})
    ws = client.get(f"/v1/workspace/{sid}").json()
    actions = ws["actions"]
    assert actions and ws["mostUseful"] == actions[0]["id"]
    assert actions[0].get("mostUsefulNow") is True
    assert "not the only right move" in actions[0]["note"]
    scores = [a["score"] for a in actions]
    assert scores == sorted(scores, reverse=True), "actions must be ranked"
