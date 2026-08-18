"""Critical E2E: anonymous user completes all four chapters; the Opportunity Map
is unreachable before STORY_COMPLETE; final map carries explainable factors."""


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
    map_payload = None
    for _ in range(80):
        it = data["interaction"]
        seen_states.add(data["state"])
        if it["type"] == "journey_complete":
            break
        if it["type"] == "chapter_transition":
            data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": it["next"]}).json()
            continue
        if it["type"] == "story_close":
            data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": "OPPORTUNITY_MAP"}).json()
            continue
        if it["type"] == "opportunity_map":
            map_payload = it
            assert data["state"] == "OPPORTUNITY_MAP"
            r = client.post(f"/v1/discover/sessions/{sid}/activate",
                            json={"action": "start", "opportunityId": it["lives"][0]["key"]})
            assert r.status_code == 200
            data = client.get(f"/v1/discover/sessions/{sid}/next").json()
            continue
        resp = drive_response(it)
        data = client.post(f"/v1/discover/sessions/{sid}/responses",
                           json={"interactionId": it["id"], "response": resp, "elapsedMs": 3000}).json()

    assert data["interaction"]["type"] == "journey_complete"
    for state in ["SELF_DISCOVERY", "REFLECTION", "ALIGNMENT", "TRANSFORMATION",
                  "STORY_COMPLETE", "OPPORTUNITY_MAP"]:
        assert state in seen_states, f"never reached {state}"
    assert map_payload and len(map_payload["lives"]) == 3
    assert all(l.get("whyThis") for l in map_payload["lives"]), "recommendations must be explainable"
    pathways = {l["key"].split("_")[0] for l in map_payload["lives"]}
    assert len(pathways) >= 2, "map must be diverse"


def test_map_unreachable_early(client):
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    r = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": "OPPORTUNITY_MAP"})
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
