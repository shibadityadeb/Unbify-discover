"""Perceived-latency contract: the backend must tell the client what actually
changed (rarely, honestly), stay idempotent under retries, and report real
phase timings — so the UI never has to invent a reason for a pause."""
import pytest


def drive(it):
    t = it["type"]
    if t in ("visual_choice", "scenario_choice", "clarification"):
        return {"optionId": it["options"][0]["id"]}
    if t in ("binary_tension", "spectrum"):
        return {"value": 0.8}
    if t in ("forced_rank", "object_sort"):
        return {"optionIds": [o["id"] for o in it["options"][: it.get("maxSelect", 3)]]}
    if t == "micro_reflection":
        return {"text": "I'm an electrician running my own small business."}
    if t == "reveal":
        return {"optionId": it["calibration"][-1]["id"]}   # disagree: a real correction
    return {"done": True}


def run(client, limit=30):
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    data = client.post(f"/v1/discover/sessions/{sid}/advance",
                       json={"to": "SELF_DISCOVERY"}).json()
    notes, answers, last_id = [], 0, None
    for _ in range(limit):
        it = data["interaction"]
        if it["type"] == "workspace":
            break
        if it["type"] in ("chapter_transition", "chapter_closing", "story_close",
                          "materialization"):
            data = client.post(f"/v1/discover/sessions/{sid}/advance",
                               json={"to": it["next"]}).json()
            continue
        last_id = it["id"]
        data = client.post(f"/v1/discover/sessions/{sid}/responses",
                           json={"interactionId": it["id"], "response": drive(it),
                                 "elapsedMs": 2000}).json()
        answers += 1
        p = data.get("processing") or {}
        if p.get("changed"):
            notes.append(p)
    return sid, notes, answers, last_id, data


def test_every_response_reports_a_processing_field(client):
    sid, notes, answers, _, data = run(client, limit=6)
    assert "processing" in data
    assert set(data["processing"]) >= {"changed", "kind", "note"}


def test_change_is_claimed_rarely_and_honestly(client):
    """§6 — 'that changed the picture' only survives if it stays rare."""
    sid, notes, answers, _, _ = run(client)
    assert answers >= 8
    rate = len(notes) / answers
    assert rate <= 0.35, f"claimed a change on {rate:.0%} of answers — the words stop meaning anything"
    for n in notes:
        assert n["kind"] in ("contradiction_appeared", "correction_taken",
                             "fact_learned", "hypothesis_revised")
        assert n["note"] and not n["note"].endswith("...")


def test_same_change_phrase_never_repeats_consecutively(client):
    sid, notes, answers, _, _ = run(client)
    kinds = [n["kind"] for n in notes]
    for a, b in zip(kinds, kinds[1:]):
        assert a != b, f"same change phrase twice running: {kinds}"


def test_change_hint_is_consumed_not_sticky(client):
    """A hint belongs to the answer that caused it — refetching must not repeat it."""
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": "SELF_DISCOVERY"})
    for _ in range(6):
        it = client.get(f"/v1/discover/sessions/{sid}/next").json()["interaction"]
        if it["type"] in ("chapter_transition", "chapter_closing"):
            client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": it["next"]})
            continue
        out = client.post(f"/v1/discover/sessions/{sid}/responses",
                          json={"interactionId": it["id"], "response": drive(it)}).json()
        if (out.get("processing") or {}).get("changed"):
            again = client.get(f"/v1/discover/sessions/{sid}/next").json()
            assert not (again.get("processing") or {}).get("changed"), \
                "a change hint must not persist across fetches"
            return


def test_no_technical_terms_leak_to_the_user(client):
    """§5 — never expose model/query/vector/vendor language."""
    sid, notes, answers, _, _ = run(client)
    banned = ("model", "vector", "inference", "postgres", "sql", "apify", "llm",
              "token", "query", "endpoint", "api")
    for n in notes:
        low = n["note"].lower()
        for word in banned:
            assert word not in low, f"technical term '{word}' in user copy: {n['note']}"


def test_resubmission_is_idempotent(client):
    """§13 — a retried submission must not double-count or advance twice."""
    sid, notes, answers, last_id, data = run(client, limit=8)
    state_before = data["state"]
    from app.db import SessionLocal
    from app.models import Response, SignalEvidence
    with SessionLocal() as db:
        responses_before = db.query(Response).filter_by(session_id=sid).count()
        evidence_before = db.query(SignalEvidence).filter_by(session_id=sid).count()
    replay = client.post(f"/v1/discover/sessions/{sid}/responses",
                         json={"interactionId": last_id, "response": {"value": 0.5}}).json()
    assert replay.get("duplicate") is True
    assert replay["state"] == state_before, "a duplicate must not advance the journey"
    with SessionLocal() as db:
        assert db.query(Response).filter_by(session_id=sid).count() == responses_before
        assert db.query(SignalEvidence).filter_by(session_id=sid).count() == evidence_before


def test_phase_timings_are_measured(client):
    """§16/§25 — latency must be measured per phase, not guessed at."""
    sid, notes, answers, _, data = run(client, limit=5)
    assert "timings" in data, "development responses should carry phase timings"
    assert data["timings"]["phases"], "no phases recorded"
    assert data["timings"]["totalMs"] >= 0
    from app.db import SessionLocal
    from app.models import RequestLatency
    with SessionLocal() as db:
        rows = db.query(RequestLatency).filter_by(session_id=sid).all()
        assert rows, "latency samples must be persisted for percentile monitoring"
        assert all(r.kind == "response" for r in rows)


def test_latency_percentiles_endpoint(client):
    run(client, limit=5)
    out = client.get("/v1/debug/latency").json()
    assert out["response"]["samples"] > 0
    for p in ("p50", "p75", "p95", "p99"):
        assert p in out["response"]["total"]
    assert "budgetsMs" in out


def test_malformed_payloads_never_500(client):
    """A bad or hostile payload must be rejected gracefully, not crash the
    endpoint — a 500 here would strand the user in the retry state."""
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    data = client.post(f"/v1/discover/sessions/{sid}/advance",
                       json={"to": "SELF_DISCOVERY"}).json()
    it = data["interaction"]
    for payload in ({"value": None}, {"value": "abc"}, {"value": []},
                    {"optionId": None}, {}, {"optionIds": None}, {"text": None}):
        r = client.post(f"/v1/discover/sessions/{sid}/responses",
                        json={"interactionId": it["id"], "response": payload})
        assert r.status_code < 500, f"payload {payload} produced {r.status_code}"
