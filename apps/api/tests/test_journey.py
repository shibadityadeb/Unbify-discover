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
        if it["type"] == "story_close":
            data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": "DISCOVER_WORKSPACE"}).json()
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
