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
            if it["type"] == "materialization":
                from tests.ownership import claim
                claim(client, sid)
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


def test_decision_help_is_a_scene_and_never_needs_the_llm(client):
    """Stalling gets real help, not encouragement — and it must work offline.

    The old assist offered "Skip this" beside a one-line platitude. Skipping
    produces the worst evidence there is (an answer given to dismiss a prompt),
    so the skip is gone and the help has to actually earn its place.
    """
    from app import decision_help
    from app.catalog import INTERACTIONS
    from app.db import SessionLocal
    from app.llm import gateway
    from app.models import AnonymousIdentity, DiscoverSession, InteractionInstance
    from app.orchestrator import _public_content

    db = SessionLocal()
    try:
        anon = AnonymousIdentity()
        db.add(anon)
        db.flush()
        session = DiscoverSession(anon_id=anon.id, journey_status="SELF_DISCOVERY",
                                  dimensions={}, practical_context={}, counters={})
        db.add(session)
        db.flush()

        original = gateway.generate
        gateway.generate = lambda *a, **k: None          # LLM unavailable
        try:
            for defn in INTERACTIONS:
                if defn["type"] not in ("binary_tension", "scenario_choice"):
                    continue
                inst = InteractionInstance(session_id=session.id, type=defn["type"],
                                           chapter="SELF_DISCOVERY", content=defn["content"],
                                           public_content=_public_content(defn))
                db.add(inst)
                db.flush()
                help_ = decision_help.build(db, session, inst)
                assert help_["moment"], f"{defn['id']} produced no scene"
                assert help_["options"], f"{defn['id']} produced no option guidance"
                for opt in help_["options"]:
                    assert opt["means"], f"{defn['id']}: option {opt['label']!r} has no meaning"
                # every option the user can see must be covered, none invented
                shown = {o["label"] for o in (inst.public_content.get("options") or [])}
                shown |= {inst.public_content[s]["label"] for s in ("left", "right")
                          if isinstance(inst.public_content.get(s), dict)}
                assert {o["label"] for o in help_["options"]} == shown
        finally:
            gateway.generate = original
    finally:
        db.rollback()
        db.close()


def test_stall_prompt_offers_help_not_an_exit():
    """The stall prompt must not let someone leave a choice unmade.

    Scoped to the assist deliberately: "Rather not say" still exists on
    free-text questions, and should. Declining to type something personal is a
    privacy decision; ducking a multiple-choice because it is hard is not, and
    the answer it produces is noise in the evidence.
    """
    from pathlib import Path
    js = Path(__file__).resolve().parents[3] / "apps" / "web" / "discover.js"
    source = js.read_text()
    start = source.index("function showAssist(")
    assist = source[start:source.index("function showHelpScene(")]
    assert "Skip this" not in assist, "the stall prompt must not offer a way out of deciding"
    assert "skipped" not in assist, "skipping must not be reachable from the stall prompt"
    assert "/help" in assist, "the assist must ask the server for real help"
    # the free-text opt-out survives, on purpose
    assert "Rather not say" in source


def test_chapter_transitions_acknowledge_and_survive_a_fast_open():
    """Two defects made chapter changes feel broken rather than slow.

    The advance CTAs awaited the network with no acknowledgement and no error
    path, so a click did nothing visible until the response landed — and a
    failure left a dead button. And close() scheduled a stage wipe 1s later with
    no way to cancel it, so opening the next chapter inside that window blanked
    a scene that had already rendered.
    """
    from pathlib import Path
    js = (Path(__file__).resolve().parents[3] / "apps" / "web" / "discover.js").read_text()

    assert "function commitAdvance(" in js
    # every advance CTA must go through it rather than a bare await
    assert js.count("commitAdvance(") >= 4, "each transition CTA must acknowledge the click"
    assert "startThinking()" in js.split("function commitAdvance(")[1][:900], \
        "the transition must show the thinking indicator it already has"

    # the deferred stage wipe must be cancellable, and open() must cancel it
    close_fn = js.split("function close() {")[1].split("}")[0]
    assert "closeTimer" in close_fn, "the stage wipe must be tracked so it can be cancelled"
    open_fn = js.split("async function open(chapter")[1][:400]
    assert "clearTimeout(closeTimer)" in open_fn, \
        "opening a chapter must cancel a pending wipe or it can blank the new scene"


def test_narrative_retry_is_time_bounded():
    """A novelty regeneration must not double a transition's wait."""
    from app import narrative_director
    assert hasattr(narrative_director, "NOVELTY_RETRY_BUDGET_S")
    assert 0 < narrative_director.NOVELTY_RETRY_BUDGET_S <= 5
    src = __import__("inspect").getsource(narrative_director.generate)
    assert "NOVELTY_RETRY_BUDGET_S" in src, "the retry must consult the budget"


def test_memory_fragments_cannot_overlap():
    """Fragments used to be positioned by a raw hash of their own text.

    Nothing stopped two of them landing on the same spot, and when they did they
    rendered as overlapping glyphs in the corner — unreadable, and it looked
    like a rendering fault rather than atmosphere. Measured at ~19% of
    six-fragment layouts. They now go into fixed, separated slots.
    """
    import re
    from pathlib import Path
    js = (Path(__file__).resolve().parents[3] / "apps" / "web" / "discover.js").read_text()

    assert "FRAG_SLOTS" in js, "fragments must be placed into fixed slots"
    assert "8 + (h % 80)" not in js, "the colliding raw-hash placement must not come back"

    block = js.split("const FRAG_SLOTS = [")[1].split("];")[0]
    slots = [(int(a), int(b)) for a, b in re.findall(r"\[(\d+),\s*(\d+)\]", block)]
    assert len(slots) >= 8, "too few slots to hold a typical field"
    assert len(set(slots)) == len(slots), "duplicate slot positions defeat the fix"

    # every pair must be far enough apart that short italic text cannot collide
    for i, a in enumerate(slots):
        for b in slots[i + 1:]:
            assert abs(a[0] - b[0]) >= 8 or abs(a[1] - b[1]) >= 8, \
                f"slots {a} and {b} are close enough to overlap"

    # and the centre column stays clear for the question itself
    for x, _ in slots:
        assert x <= 25 or x >= 75, f"slot at x={x}% sits over the question text"


def test_idle_means_not_working_on_the_answer():
    """Idle is defined by the answer controls, not by the mouse.

    The countdown first watched the whole page, so drift, a stray scroll, or a
    hand resting on the mouse kept resetting it and the offer of help never
    arrived for someone sitting and thinking. It now resets only while the
    person is actually working on the answer: dragging the slider, typing in the
    field, or picking through the options.
    """
    from pathlib import Path
    js = (Path(__file__).resolve().parents[3] / "apps" / "web" / "discover.js").read_text()

    assert "ANSWER_CONTROLS" in js, "activity must be scoped to the answer controls"
    controls = js.split("const ANSWER_CONTROLS =")[1].split(";")[0]
    for needed in (".dx-handle", ".dx-input", ".dx-opt", ".dx-chip"):
        assert needed in controls, f"{needed} is an answer control and must count as activity"

    activity = js.split("const ACTIVITY = [")[1].split("]")[0]
    assert "pointermove" not in activity, \
        "a moving cursor is not someone answering — it must not reset the countdown"
    assert "wheel" not in activity, "scrolling is not answering"
    for needed in ("pointerdown", "keydown", "input"):
        assert needed in activity, f"{needed} is real interaction and must reset it"

    # an in-progress drag has to hold it off between pointerdown and pointerup
    assert "onDrag" in js and "e.buttons > 0" in js, \
        "a held drag must keep the prompt away even with no other events"


def test_only_one_retry_block_can_exist():
    """Every failed submit appended another retry block, so a few attempts left
    a stack of identical "That didn't go through / Try again" pairs with no way
    to tell which button was live."""
    from pathlib import Path
    js = (Path(__file__).resolve().parents[3] / "apps" / "web" / "discover.js").read_text()
    fn = js.split("function showRetry(")[1].split("\n  }")[0]
    assert 'querySelectorAll(".dx-retry")' in fn and "remove()" in fn, \
        "showRetry must clear any existing retry before adding one"
    # and it must still preserve the answer rather than making them redo it
    assert "respondMain(interactionId, response, chosenEl)" in fn


def test_workspace_action_clicks_are_acknowledged():
    """A workspace action can take tens of seconds — the first one in a session
    runs the whole recommendation pipeline. The click used to await it in
    silence with no error path, so a slow action and a broken one looked
    identical: nothing happened, and nothing ever would."""
    from pathlib import Path
    js = (Path(__file__).resolve().parents[3] / "apps" / "web" / "discover.js").read_text()
    handler = js.split('row.addEventListener("click"')[1].split("list.appendChild(row)")[0]
    assert "withBusy" in handler, "the wait must be visible"
    assert "catch" in handler, "a failed action must not vanish silently"
    assert "retry" in handler.lower(), "the person needs a way to try again"
    assert 'dataset.busy' in handler, "a second click must not start a second request"
