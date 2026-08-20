"""Critical E2E: anonymous user completes all four chapters; the workspace (and
the Opportunity Map inside it) is unreachable before STORY_COMPLETE; the map
carries explainable factors; adaptive Questions work after the story."""


def drive_response(interaction):
    t = interaction["type"]
    if t in ("visual_choice", "scenario_choice"):
        return {"optionId": interaction["options"][0]["id"]}
    if t in ("binary_tension", "spectrum"):
        return {"value": 0.7}
    if t in ("forced_rank", "object_sort"):
        return {"optionIds": [o["id"] for o in interaction["options"][: interaction.get("maxSelect", 3)]]}
    if t == "micro_reflection":
        return {"text": "People bring me their tangled problems."}
    if t == "reveal":
        return {"optionId": interaction["calibration"][0]["id"]}
    if t == "possible_lives":
        return {"optionId": interaction["options"][0]["id"]}
    if t == "final":
        return {"done": True}
    raise AssertionError(f"unhandled type {t}")


def test_full_journey(client):
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    assert data["state"] == "PROLOGUE"

    seen_states = set()
    for _ in range(80):
        it = data["interaction"]
        seen_states.add(data["state"])
        if it["type"] == "workspace":
            break
        if it["type"] in ("chapter_transition", "chapter_closing"):
            data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": it["next"]}).json()
            continue
        if it["type"] in ("story_close", "materialization"):
            data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": it["next"]}).json()
            continue
        resp = drive_response(it)
        data = client.post(f"/v1/discover/sessions/{sid}/responses",
                           json={"interactionId": it["id"], "response": resp, "elapsedMs": 3000}).json()

    assert data["interaction"]["type"] == "workspace"
    for state in ["SELF_DISCOVERY", "SELF_DISCOVERY_CLOSING", "REFLECTION", "REFLECTION_CLOSING",
                  "ALIGNMENT", "ALIGNMENT_CLOSING", "TRANSFORMATION", "TRANSFORMATION_CLOSING",
                  "STORY_COMPLETE", "DISCOVER_WORKSPACE"]:
        assert state in seen_states, f"never reached {state}"

    # the Opportunity Map lives inside ACTIONS
    ws = client.get(f"/v1/workspace/{sid}").json()
    assert ws["clarity"] in ("Early", "Developing", "Strong", "Very strong")
    action_ids = [a["id"] for a in ws["actions"]]
    assert "explore" in action_ids and "next_move" in action_ids
    mp = client.get(f"/v1/workspace/{sid}/actions/explore").json()
    assert mp["kind"] == "map" and len(mp["lives"]) == 3
    assert all(l.get("whyThis") for l in mp["lives"]), "recommendations must be explainable"
    assert len({l["pathway"] for l in mp["lives"]}) >= 2, "map must be diverse"

    # adaptive Questions: one at a time, never a form; answers update the profile
    q = client.post(f"/v1/workspace/{sid}/questions/next").json()
    assert q["interaction"]["type"] in ("micro_reflection", "spectrum", "scenario_choice", "object_sort")
    ans = drive_response(q["interaction"])
    r = client.post(f"/v1/discover/sessions/{sid}/responses",
                    json={"interactionId": q["interaction"]["id"], "response": ans}).json()
    assert r["state"] == "DISCOVER_WORKSPACE"

    # activation records the chosen path without ending the workspace
    r = client.post(f"/v1/discover/sessions/{sid}/activate",
                    json={"action": "start", "opportunityId": mp["lives"][0]["key"]})
    assert r.status_code == 200 and r.json()["state"] == "DISCOVER_WORKSPACE"


def test_workspace_unreachable_early(client):
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    r = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": "DISCOVER_WORKSPACE"})
    assert r.status_code == 409
    r = client.get(f"/v1/workspace/{sid}")
    assert r.status_code == 409
    r = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": "SELF_DISCOVERY"})
    assert r.status_code == 200
    r = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": "TRANSFORMATION"})
    assert r.status_code == 409


def test_stale_response_rejected_safely(client):
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": "SELF_DISCOVERY"}).json()
    it = data["interaction"]
    r1 = client.post(f"/v1/discover/sessions/{sid}/responses",
                     json={"interactionId": it["id"], "response": drive_response(it)}).json()
    r2 = client.post(f"/v1/discover/sessions/{sid}/responses",
                     json={"interactionId": it["id"], "response": drive_response(it)}).json()
    assert r2.get("stale") is True
    assert r2["interaction"]["type"] != "journey_complete"


def test_resume(client):
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    resumed = client.post("/v1/discover/sessions", json={"sessionId": sid}).json()
    assert resumed["sessionId"] == sid


def test_status_branching(client):
    """A founder never gets employee-branch questions and vice versa."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.catalog import INTERACTIONS
    branches = {d["id"]: d.get("requires_status") for d in INTERACTIONS if d.get("requires_status")}
    assert "sc_biz_stage" in branches and branches["sc_biz_stage"] == ["founder"]
    assert branches["sc_own_scope"] == ["employed"]
    assert branches["sc_student_real"] == ["student"]


def test_no_third_party_perception_questions(client):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.catalog import INTERACTIONS
    text = str(INTERACTIONS).lower()
    for phrase in ["people come to you", "friends say", "would your manager", "coworkers say"]:
        assert phrase not in text


def test_every_workspace_action_names_its_own_blocker():
    """A capsule that cannot deliver must say what IS missing, in its own terms.

    One shared "not enough evidence yet" told the person nothing about what they
    had just opened or how to unblock it — the same sentence whether they asked
    to compare paths or to test a direction.
    """
    from app import workspace

    for action_id in ("compare", "explore", "test_direction", "next_move", "build"):
        out = workspace._not_yet(action_id, lives=[{"key": "one"}])
        assert out["headline"] != "Not ready yet", f"{action_id} fell back to the generic message"
        assert out["title"], f"{action_id} did not say what is missing"
        assert out["text"], f"{action_id} did not say how to unblock it"
        # the headline must name the thing the person actually clicked
        assert len(out["headline"]) > 3

    # the count is real, not a placeholder
    compare = workspace._not_yet("compare", lives=[{"key": "only-one"}])
    assert "1" in compare["title"], "the blocker should state how many directions exist"

    # anything unnamed still explains itself rather than going silent
    unknown = workspace._not_yet("no_such_action", lives=[])
    assert unknown["headline"] and unknown["title"] and unknown["text"]


def _rich_session(db):
    from app.models import AnonymousIdentity, DiscoverSession
    anon = AnonymousIdentity()
    db.add(anon)
    db.flush()
    d = lambda e, c, n: {"estimate": e, "confidence": c, "evidence_count": n,
                         "pos_w": 1, "neg_w": 0, "variance": 0}
    session = DiscoverSession(
        anon_id=anon.id, journey_status="DISCOVER_WORKSPACE", counters={},
        dimensions={"ai_leverage": d(.4, .6, 3), "time_availability": d(-.5, .7, 3),
                    "mastery": d(.6, .7, 4), "capital_availability": d(-.3, .6, 2)},
        practical_context={"current_occupation_title": "electrician",
                           "hands_on_technical": True, "builds_things": True,
                           "commercial_evidence": True})
    db.add(session)
    db.flush()
    return session


def test_actions_answer_with_this_persons_evidence_not_advice(client):
    """Capsules used to return lines equally true for anybody. Each must now cite
    something specific to the person or their field."""
    from app import workspace
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        session = _rich_session(db)

        ai = workspace.action_content(db, session, "ai_leverage")
        body = " ".join(ai["items"])
        assert "Electrician" in body, "AI leverage must name the actual field"
        assert "0.15" in body and "0.45" in body, "it must cite the real exposure figures"

        income = workspace.action_content(db, session, "expertise_income")
        assert "55%" in " ".join(income["items"]), "must use the field's own independence rate"

        gaps = workspace.action_content(db, session, "gaps")
        lines = gaps["items"]
        assert len(set(lines)) == len(lines), "gaps must not repeat one sentence"
        for line in lines:
            assert "a few Questions would sharpen this" not in line

        # a constraint is not a preference
        position = workspace.action_content(db, session, "position")
        align = next((i for i in position["items"] if i.startswith("Alignment")), "")
        assert "scraps of time" not in align, "circumstances must not be read as alignment"

        # and the next step has to be an actual step
        nxt = workspace.action_content(db, session, "next_move")
        assert "two honest hours this week" not in " ".join(nxt["items"]), \
            "the generic placeholder step must not survive"
        assert nxt["title"] and len(nxt["title"]) <= 60, "a title is a name, not a paragraph"
    finally:
        db.rollback()
        db.close()
