"""§47 — FULL JOURNEY NOVELTY. A complete journey must never repeat a bridge,
must use a different closing structure per chapter, must not develop verbal
tics, and must vary the resonance presentation chapter to chapter."""
from app.repetition import normalize, opening_of, similarity


def drive_response(interaction):
    t = interaction["type"]
    if t in ("visual_choice", "scenario_choice"):
        return {"optionId": interaction["options"][0]["id"]}
    if t in ("binary_tension", "spectrum"):
        return {"value": 0.7}
    if t in ("forced_rank", "object_sort"):
        return {"optionIds": [o["id"] for o in interaction["options"][: interaction.get("maxSelect", 3)]]}
    if t == "micro_reflection":
        return {"text": "I am a computer science student and I build small apps that real people use."}
    if t == "clarification":
        return {"optionId": interaction["options"][0]["id"]}
    if t == "reveal":
        return {"optionId": interaction["calibration"][0]["id"]}
    if t == "possible_lives":
        return {"optionId": interaction["options"][0]["id"]}
    if t == "final":
        return {"done": True}
    raise AssertionError(f"unhandled type {t}")


def run_journey(client):
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    bridges, closings, copy_lines = [], [], []
    for _ in range(90):
        it = data["interaction"]
        if it["type"] == "workspace":
            break
        if it.get("bridge"):
            bridges.append(it["bridge"])
        if it["type"] == "chapter_closing":
            closings.append(it)
            for sec in it.get("beats", it.get("sections", [])):
                if sec.get("text"):
                    copy_lines.append(sec["text"])
        if it["type"] in ("chapter_transition", "chapter_closing"):
            data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": it["next"]}).json()
            continue
        if it["type"] in ("story_close", "materialization"):
            data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": it["next"]}).json()
            continue
        if it["type"] == "reveal":
            copy_lines.extend(it.get("lines", []))
        data = client.post(f"/v1/discover/sessions/{sid}/responses",
                           json={"interactionId": it["id"], "response": drive_response(it), "elapsedMs": 2500}).json()
    return sid, bridges, closings, copy_lines


def test_no_bridge_repeats_and_no_tics(client):
    sid, bridges, closings, copy_lines = run_journey(client)
    # same bridge never appears twice — exactly or normalized
    norm = [normalize(b) for b in bridges]
    assert len(norm) == len(set(norm)), f"duplicate bridge: {bridges}"
    # no highly-similar transition pair
    for i, a in enumerate(bridges):
        for b in bridges[i + 1:]:
            assert similarity(a, b) < 0.6, f"near-duplicate bridges: {a!r} / {b!r}"
    # 'Interesting' must not recur as an opener anywhere in the narration
    all_copy = bridges + copy_lines
    interesting = [c for c in all_copy if normalize(c).startswith("interesting")]
    assert len(interesting) <= 1, f"'Interesting' tic: {interesting}"
    # no single opening dominates
    openings = {}
    for c in all_copy:
        o = opening_of(c)
        openings[o] = openings.get(o, 0) + 1
    for o, n in openings.items():
        assert n <= 3, f"opening '{o}' dominates ({n} uses)"


def test_every_chapter_closes_differently(client):
    sid, bridges, closings, copy_lines = run_journey(client)
    assert len(closings) == 4, f"expected 4 chapter closings, saw {len(closings)}"
    layouts = [c["layout"] for c in closings]
    # planner guarantee: no closing architecture repeats in consecutive chapters
    for a, b in zip(layouts, layouts[1:]):
        assert a != b, f"consecutive closings reused structure: {layouts}"
    assert layouts[-1] == "reconstruction", "Transformation must reconstruct, not summarize"
    # every closing has beats, a manual CTA, and a next state — never auto-advance
    for c in closings:
        assert c.get("beats"), "closing without beats"
        assert c.get("cta") and c.get("next")
    # closing copy never repeats verbatim across chapters
    texts = [normalize(s["text"]) for c in closings for s in c["beats"] if s.get("text")]
    assert len(texts) == len(set(texts)), "closing copy repeated across chapters"


def test_closings_have_recorded_purpose(client):
    """PART 84: a closing that cannot answer 'why / what changed' is generic."""
    sid, bridges, closings, copy_lines = run_journey(client)
    from app.db import SessionLocal
    from app.models import ChapterClosingPlan
    with SessionLocal() as db:
        plans = db.query(ChapterClosingPlan).filter_by(session_id=sid).all()
        assert len(plans) >= 4
        for p in plans:
            assert p.selected_structure and p.why_this_closing and p.available_events


def test_resonance_when_present_is_evidence_backed(client):
    """PART 39/41: resonance is optional — but when shown, every match must
    trace to documented evidence with a stored source."""
    sid, bridges, closings, copy_lines = run_journey(client)
    res_sections = [s for c in closings for s in c["beats"] if s["kind"] == "resonance"]
    for s in res_sections:
        for m in s.get("matches", []):
            assert m["overlap"] and m["yourEvidence"] and m["theirEvidence"]
            assert m["strength"] in ("Weak echo", "Emerging", "Strong overlap")
            assert m.get("source", {}).get("title"), "match without a stored source"


def test_story_inspector_available_in_dev(client):
    sid, *_ = run_journey(client)
    out = client.get(f"/v1/debug/sessions/{sid}/story").json()
    assert out["narrativeState"]["closingStyleHistory"], "closing history not tracked"
    assert "repetitionScores" in out and "recentCopy" in out


def run_journey_with(client, chooser, reflection_text):
    """Drive a journey with a custom option chooser — for divergence tests."""
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    closings = []
    for _ in range(90):
        it = data["interaction"]
        if it["type"] == "workspace":
            break
        if it["type"] == "chapter_closing":
            closings.append(it)
        if it["type"] in ("chapter_transition", "chapter_closing"):
            data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": it["next"]}).json()
            continue
        if it["type"] in ("story_close", "materialization"):
            data = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": it["next"]}).json()
            continue
        t = it["type"]
        if t in ("visual_choice", "scenario_choice", "clarification"):
            resp = {"optionId": chooser(it["options"])}
        elif t in ("binary_tension", "spectrum"):
            resp = {"value": chooser(None)}
        elif t in ("forced_rank", "object_sort"):
            opts = it["options"]
            picked = [chooser(opts)] + [o["id"] for o in opts if o["id"] != chooser(opts)]
            resp = {"optionIds": picked[: it.get("maxSelect", 3)]}
        elif t == "micro_reflection":
            resp = {"text": reflection_text}
        elif t == "reveal":
            resp = {"optionId": it["calibration"][0]["id"]}
        elif t == "possible_lives":
            resp = {"optionId": it["options"][0]["id"]}
        elif t == "final":
            resp = {"done": True}
        else:
            raise AssertionError(f"unhandled {t}")
        data = client.post(f"/v1/discover/sessions/{sid}/responses",
                           json={"interactionId": it["id"], "response": resp, "elapsedMs": 2000}).json()
    return sid, closings


def test_different_users_diverge_meaningfully(client):
    """PART 71/72: different answers must diverge in facts, hypotheses and
    story — not merely wording."""
    sid_a, closings_a = run_journey_with(
        client, lambda opts: (opts[0]["id"] if opts else 0.9),
        "I'm a computer science student, I build small apps that real people use.")
    sid_b, closings_b = run_journey_with(
        client, lambda opts: (opts[-1]["id"] if opts else -0.9),
        "I run operations for a logistics company and lead a team of twelve.")

    from app.db import SessionLocal
    from app.models import DiscoverSession, Hypothesis
    with SessionLocal() as db:
        sa = db.get(DiscoverSession, sid_a)
        sb = db.get(DiscoverSession, sid_b)
        facts_a = {k for k in (sa.practical_context or {}) if not k.startswith("_")}
        facts_b = {k for k in (sb.practical_context or {}) if not k.startswith("_")}
        assert facts_a != facts_b, "different lives must produce different facts"
        hyps_a = {(h.construct, h.direction) for h in db.query(Hypothesis).filter_by(session_id=sid_a)
                  if h.confidence >= 0.4}
        hyps_b = {(h.construct, h.direction) for h in db.query(Hypothesis).filter_by(session_id=sid_b)
                  if h.confidence >= 0.4}
        assert hyps_a != hyps_b, "different answers must produce different hypotheses"
    # the closing ritual lines are deliberately shared; divergence is about insight
    texts_a = {s["text"] for c in closings_a for s in c["beats"]
               if s.get("text") and s.get("type") != "closing"}
    texts_b = {s["text"] for c in closings_b for s in c["beats"]
               if s.get("text") and s.get("type") != "closing"}
    overlap = texts_a & texts_b
    assert len(overlap) <= max(1, len(texts_a) // 3), f"journeys share too much copy: {overlap}"
