"""Chapter closings, composed from a planner-selected story architecture.

CHAPTER COMPLETE → CLOSING PLANNER → STRUCTURE → ACTUAL EVIDENCE →
CALLBACK / SURPRISE → ONLY THEN WORDING.  Copy is secondary (PART 34).
Beats derive from real state change; resonance is optional, not a ritual;
quality beats length; nothing auto-advances.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import closing_planner, knowledge
from . import narrative_director as director
from . import resonance, surprise
from . import thresholds as th
from .dimensions import CHAPTER_FOCUS, dim_fragment, dim_phrase
from . import content_policy
from .models import DiscoverSession, EvidenceItem
from .signals import thinnest_dims, top_dims

CLOSING_CTA = {
    "SELF_DISCOVERY_CLOSING": "See the pattern →",
    "REFLECTION_CLOSING": "Put this into the real world →",
    "ALIGNMENT_CLOSING": "Bring it together →",
    "TRANSFORMATION_CLOSING": "See what this can become →",
}


def _beat(type_: str, text: str | None, label: str | None = None, kind: str = "beat") -> dict | None:
    if not text:
        return None
    out = {"type": type_, "kind": kind, "text": text}
    if label:
        out["label"] = label
    return out


def _strongest(session: DiscoverSession, n: int = 1):
    return top_dims(session, n, min_confidence=th.DO_NOT_SURFACE)


def _evidence_claims(db: Session, session: DiscoverSession, dim: str, limit: int = 2) -> list[str]:
    rows = (db.query(EvidenceItem).filter_by(session_id=session.id)
            .order_by(EvidenceItem.created_at.asc()).all())
    claims = []
    for r in rows:
        if any(d.get("dim") == dim and d.get("delta", 0) != 0 for d in (r.dims or [])):
            claims.append(r.claim)
    return claims[-limit:]


# ---------------- structure composers ----------------

def _fragment_reassembly(db, session, st, plan) -> list[dict]:
    """Ch1 default: the system is collecting fragments, not building theories."""
    beats = []
    frags = [dim_fragment(t["dim"], t["estimate"]) for t in
             top_dims(session, 4, min_confidence=0.25)]
    answered = (session.counters or {}).get("chapter_interactions", 0)
    opening = director.generate(
        db, session, "SHOW_PROGRESS",
        {"answered": answered, "fragments": len(frags)},
        "light, unpolished, collecting",
        [f"We started with almost nothing — {answered} quick choices. A few fragments are worth carrying forward.",
         f"No biography, just {answered} instincts. Some of them already point somewhere."], max_words=30)
    beats.append(_beat("opening", opening))
    if frags:
        beats.append({"type": "fragments", "kind": "fragments", "items": frags})
        note = director.generate(
            db, session, "CREATE_CURIOSITY", {"fragments": frags},
            "deliberately unresolved",
            ["None of these is a theory about you yet. They're pieces — the next chapter tests whether they belong together.",
             f"Whether {frags[0]} and {frags[-1]} are related is exactly what we don't know yet."], max_words=30)
        beats.append(_beat("restraint", note))
    return [b for b in beats if b]


def _evidence_strengthening(db, session, st, plan) -> list[dict]:
    beats = []
    tops = _strongest(session, 1)
    if not tops:
        return _fragment_reassembly(db, session, st, plan)
    t = tops[0]
    claims = _evidence_claims(db, session, t["dim"])
    text = director.generate(
        db, session, "CONNECT_PREVIOUS_ANSWERS",
        {"pattern": dim_phrase(t["dim"], t["estimate"]),
         "evidenceCount": t.get("evidence_count", 0), "recentEvidence": claims},
        "quiet accumulation",
        [f"One thing kept returning — {dim_fragment(t['dim'], t['estimate'])}, across {t.get('evidence_count', 2)} separate answers that had nothing else in common.",
         f"{t.get('evidence_count', 2)} unrelated questions, one repeated pull: {dim_fragment(t['dim'], t['estimate'])}."],
        max_words=32)
    beats.append(_beat("pattern", text))
    if claims:
        beats.append({"type": "evidence_trail", "kind": "evidence",
                      "heading": "Where it showed up",
                      "rows": [{"label": f"answer {i+1}", "value": c[:80]} for i, c in enumerate(claims)]})
    return [b for b in beats if b]


def _open_question(db, session, st, plan) -> list[dict]:
    beats = []
    focus = CHAPTER_FOCUS.get(st.chapter.replace("_CLOSING", ""), [])
    thin = thinnest_dims(session, focus or ["energy", "cognitive"], 1)
    tops = _strongest(session, 1)
    if tops:
        beats.append(_beat("observation",
                           f"So far, {dim_fragment(tops[0]['dim'], tops[0]['estimate'])} has done most of the talking."))
    if thin:
        text = director.generate(
            db, session, "CREATE_CURIOSITY", {"unknown": dim_phrase(thin[0], 1)},
            "an honest open question",
            [f"The loudest silence is around {dim_fragment(thin[0], 1)} — nothing you've answered has touched it yet.",
             f"We can't yet see you and {dim_fragment(thin[0], 1)} in the same frame. That's the next experiment."],
            max_words=28)
        beats.append(_beat("open_question", text))
    return [b for b in beats if b]


def _callback_resolution(db, session, st, plan) -> list[dict]:
    payload = plan["drivingEvent"]["payload"]
    dim = payload.get("dim")
    if not dim:
        return _evidence_strengthening(db, session, st, plan)
    state = (session.dimensions or {}).get(dim, {})
    ref = f'"{payload["headline"]}"' if payload.get("headline") else "one of your first choices"
    beats = [
        _beat("callback",
              f"At the start — {ref} — you chose {dim_fragment(dim, 1)} almost instantly. We left it alone.",
              label="An early answer, revisited"),
        _beat("resolution", director.generate(
            db, session, "CALLBACK",
            {"dim": dim_phrase(dim, 1), "laterEvidence": state.get("evidence_count", 0)},
            "recognition earned by evidence",
            [f"{state.get('evidence_count', 3)} later answers now make that first instinct meaningful — it wasn't a one-off.",
             f"Since then the same pull has returned {max(2, state.get('evidence_count', 2) - 1)} times. First instincts sometimes carry weight."],
            max_words=30)),
    ]
    return [b for b in beats if b]


def _belief_revision(db, session, st, plan) -> list[dict]:
    """PART 35: the system showing it changed its mind — the credibility beat."""
    payload = plan["drivingEvent"]["payload"]
    construct = payload.get("construct")
    if not construct:
        return _evidence_strengthening(db, session, st, plan)
    direction = payload.get("direction", 1)
    was_correction = plan["drivingEvent"]["type"] == "USER_CORRECTED_SYSTEM"
    prev_phrase = dim_phrase(construct, direction)
    beats = [
        _beat("previous_belief",
              f"Earlier, the evidence pointed toward {prev_phrase}." if not was_correction else
              f"Earlier, we read you as leaning toward {prev_phrase}.",
              label="What we first thought"),
        _beat("new_evidence",
              "You told us directly that reading was wrong — and a correction outweighs everything we merely inferred."
              if was_correction else
              f"Later answers stopped supporting it. The confidence dropped from {payload.get('from', 0.5)} territory to genuinely unclear.",
              label="What changed"),
        _beat("revision", director.generate(
            db, session, "REOPEN_UNCERTAINTY",
            {"construct": prev_phrase, "corrected": was_correction},
            "humble, more plausible now",
            [f"Revised reading: the question isn't {dim_fragment(construct, direction)} at all — something nearby is doing the real work. We're keeping it open.",
             f"So we changed our mind. {dim_fragment(construct, direction).capitalize()} is back on the table as unknown — which is more honest than pretending."],
            max_words=36), label="Where that leaves us"),
    ]
    return [b for b in beats if b]


def _contradiction(db, session, st, plan) -> list[dict]:
    c = next((x for x in (session.contradictions or []) if not x.get("explored")), None)
    if not c:
        return _evidence_strengthening(db, session, st, plan)
    dim = c["dim"]
    beats = [
        _beat("side_a", f"Part of your evidence argues for {dim_phrase(dim, 1)}."),
        _beat("side_b", f"Another part, just as sincere, argues for {dim_phrase(dim, -1)}."),
        _beat("honor", director.generate(
            db, session, "INTRODUCE_CONTRADICTION",
            {"sideA": dim_phrase(dim, 1), "sideB": dim_phrase(dim, -1)},
            "treating tension as information",
            ["We're not averaging those away. The answer is probably situational — and finding the situation is the interesting part.",
             "Both are real until proven otherwise. Contradictions like this usually mark where the actual story lives."],
            max_words=30)),
    ]
    return [b for b in beats if b]


def _unexpected_absence(db, session, st, plan) -> list[dict]:
    payload = plan["drivingEvent"]["payload"]
    beats = [
        _beat("expectation", f"Something we expected to see hasn't appeared strongly.",
              label="An absence"),
        _beat("absence",
              f"{payload.get('context', 'Your experience is real').capitalize()}. "
              f"But {payload.get('expected', 'the expected pattern')} hasn't been the thing consistently driving your choices."),
        _beat("restraint",
              "Too early to interpret that. It could mean several different things — worth carrying forward, not concluding on."),
    ]
    return [b for b in beats if b]


def _professional_grounding(db, session, st, plan) -> list[dict]:
    beats = []
    pc = session.practical_context or {}
    label_map = {"current_status": "where you are", "works_with_software": "you work with software",
                 "builds_things": "you build things", "hands_on_technical": "you're hands-on technical",
                 "commercial_evidence": "you've been paid for your work",
                 "people_management_evidence": "you've led people",
                 "coordinates_delivery": "you coordinate delivery",
                 "technical_decision_authority": "you own technical decisions",
                 "freelance_experience": "you've worked independently",
                 "years_mentioned": "years of experience"}
    rows = [{"label": lbl, "value": pc[k] if isinstance(pc.get(k), str) else ("yes" if pc.get(k) is True else str(pc.get(k)))}
            for k, lbl in label_map.items() if k in pc and not str(k).startswith("_")]
    if rows:
        beats.append({"type": "reality", "kind": "evidence", "heading": "What reality adds", "rows": rows[:6]})
    tops = _strongest(session, 1)
    grounding_facts = {"factCount": len(rows)}
    if tops:
        grounding_facts["pattern"] = dim_phrase(tops[0]["dim"], tops[0]["estimate"])
    text = director.generate(
        db, session, "OPEN_PROFESSIONAL_CONTEXT", grounding_facts,
        "grounded, adult",
        ["Until now we watched instinct. This chapter added what instinct lives inside — your actual situation. Some earlier readings just got heavier; others got lighter.",
         "Facts change interpretation. The same choices read differently now that we know what you actually do."],
        max_words=34)
    beats.append(_beat("grounding", text))
    return [b for b in beats if b]


def _resonance_shift(db, session, st, plan) -> list[dict]:
    beats = []
    result = resonance.compute_matches(db, session, st.chapter)
    matches, movement = result["matches"], result["movement"]
    if not matches:
        return _professional_grounding(db, session, st, plan)
    mv_bits = []
    if movement.get("disappeared"):
        mv_bits.append(f"{movement['disappeared'][0]} dropped out")
    if movement.get("strengthened"):
        mv_bits.append(f"{movement['strengthened'][0]} got stronger")
    if movement.get("appeared"):
        mv_bits.append(f"{movement['appeared'][0]} is new")
    if mv_bits:
        beats.append(_beat("shift", f"The echoes moved: {', '.join(mv_bits)} — because the evidence moved.",
                           label="The matches moved"))
    cards = []
    for m in matches:
        their = m["theirEvidence"][0] if m["theirEvidence"] else {}
        cards.append({"figureId": m["figureId"], "figure": m["figure"], "patternId": m["patternId"],
                      "construct": m["construct"].replace("_", " "), "overlap": m["description"],
                      "yourEvidence": m["userEvidence"], "theirEvidence": their.get("claim", ""),
                      "source": their.get("source", {}), "strength": m["strength"]})
    beats.append({"type": "resonance", "kind": "resonance",
                  "heading": "Documented patterns, one overlap each", "matches": cards, "empty": False,
                  "disclaimer": "One narrow professional pattern per person. Different lives, different circumstances."})
    st.public_figure_matches_shown = list({*(st.public_figure_matches_shown or []),
                                           *[m["figureId"] for m in matches]})
    return [b for b in beats if b]


def _prediction_test(db, session, st, plan) -> list[dict]:
    tops = _strongest(session, 1)
    if not tops:
        return _open_question(db, session, st, plan)
    t = tops[0]
    frag = dim_fragment(t["dim"], t["estimate"])
    beats = [
        _beat("hypothesis", f"Working hypothesis: {dim_phrase(t['dim'], t['estimate'])} matters to you more than average.",
              label="A small bet"),
        _beat("test", director.generate(
            db, session, "SETUP_NEXT_CHAPTER", {"prediction": frag},
            "a falsifiable promise",
            [f"If that's real, {frag} should survive contact with your actual work next chapter. If it doesn't — the hypothesis was wrong, and we'll say so.",
             f"Next chapter can break this: when reality enters, {frag} either holds or it doesn't. Either answer is progress."],
            max_words=34)),
    ]
    return [b for b in beats if b]


def _reconstruction(db, session, st, plan) -> list[dict]:
    """THE FINAL MIRROR. Evidence decides which beats exist — there are no
    mandatory personality slots, no prescribed career and no next-step advice.
    What the journey could not establish is stated, not filled in."""
    from . import knowledge
    from .models import Hypothesis
    beats: list[dict] = []
    history = knowledge.hypothesis_history(db, session)
    hyps = {h.construct: h for h in db.query(Hypothesis).filter_by(session_id=session.id).all()}
    pc = session.practical_context or {}

    # WHAT SURVIVED
    survived = [h for h in hyps.values()
                if h.status == "supported" and h.confidence >= th.MAY_TEST]
    survived.sort(key=lambda h: -h.confidence)
    for h in survived[:2]:
        beats.append({"type": "survived", "kind": "beat", "label": "What survived",
                      "text": f"Across four chapters and {len(h.supporting_evidence_ids or [])} separate "
                              f"moments, one reading kept holding: you move toward "
                              f"{dim_phrase(h.construct, h.direction)}."})

    # WHAT CHANGED — real belief revision from version history
    chapter_names = {"SELF_DISCOVERY": "the first chapter", "REFLECTION": "Reflection",
                     "ALIGNMENT": "Alignment", "TRANSFORMATION": "the last chapter"}
    for key, versions in history.items():
        if len(versions) < 2:
            continue
        construct, direction = key.rsplit(":", 1)
        first, last = versions[0], versions[-1]
        if (last["status"] in ("corrected", "contradicted")
                or last["confidence"] < first["confidence"] - 0.15):
            where = chapter_names.get(str(first.get("chapter", "")).replace("_CLOSING", ""), "early on")
            beats.append({"type": "changed", "kind": "beat", "label": "What we changed our mind about",
                          "text": f"Early on, your choices read as {dim_phrase(construct, int(direction))}. "
                                  f"Later answers stopped supporting that, so we let it go — what looked "
                                  f"settled in {where} didn't survive contact with the rest."})
            break

    # WHAT YOUR REAL LIFE ADDED
    title = pc.get("current_occupation_title")
    concrete = []
    if pc.get("builds_things"):
        concrete.append("you've already built things")
    if pc.get("commercial_evidence"):
        concrete.append("people have already paid you")
    if pc.get("people_management_evidence"):
        concrete.append("you've already carried responsibility for others")
    if concrete:
        beats.append({"type": "reality", "kind": "beat", "label": "What your real life added",
                      "text": (f"Your work as {title} made the pattern concrete. " if title else "")
                              + f"This isn't only preference — {', and '.join(concrete[:2])}."})

    # WHAT YOU ALREADY HAVE
    from . import materialization
    lev = materialization.leverage_map(db, session)
    if lev:
        beats.append({"type": "have", "kind": "beat", "label": "What you already have",
                      "text": "You're not starting from zero: "
                              + ", ".join(l["label"].lower() for l in lev[:3]) + "."})

    # WHAT WE STILL WOULD NOT CLAIM
    unclear = []
    for dim in ("sales_comfort", "revenue_ambition", "leadership", "risk_tolerance"):
        state = (session.dimensions or {}).get(dim, {})
        if state.get("confidence", 0) < th.WEAK_INTERNAL:
            unclear.append(dim_fragment(dim, 1))
    if unclear:
        beats.append({"type": "unclear", "kind": "beat", "label": "What we still would not claim",
                      "text": f"We don't know where you land on {' or '.join(unclear[:2])}. "
                              "Guessing there would cost you more than admitting it."})

    if not beats:
        beats.append({"type": "honest", "kind": "beat", "label": "What we can say",
                      "text": "You gave us less to work with than most, and we'd rather hand you a "
                              "small honest picture than a large invented one."})

    # the model may only re-express beats it was given — never add one
    from .llm import gateway
    out = gateway.generate(db, "final_mirror_v1",
                           {"beats": [{"type": b["type"], "text": b["text"]} for b in beats]})
    if out and isinstance(out.get("beats"), list) and len(out["beats"]) == len(beats):
        for i, b in enumerate(out["beats"][:len(beats)]):
            text = str(b.get("text", ""))[:220]
            if text and content_policy.validate(text):
                beats[i]["text"] = text
    beats = [b for b in beats if content_policy.validate(b["text"])]

    for line in ["This is not a verdict.",
                 "It's the clearest picture we can build from what you've shown us so far.",
                 "Some parts are strong. Some are still unfinished. That's useful.",
                 "Because now we can stop trying to describe you — and start testing what this could become.",
                 "Discovery complete."]:
        beats.append({"type": "closing", "kind": "beat", "text": line})
    return beats


COMPOSERS = {
    "fragment_reassembly": _fragment_reassembly,
    "evidence_strengthening": _evidence_strengthening,
    "open_question": _open_question,
    "callback_resolution": _callback_resolution,
    "belief_revision": _belief_revision,
    "contradiction": _contradiction,
    "unexpected_absence": _unexpected_absence,
    "professional_grounding": _professional_grounding,
    "resonance_shift": _resonance_shift,
    "prediction_test": _prediction_test,
    "reconstruction": _reconstruction,
}


def _tease(db, session, st, next_state: str) -> dict | None:
    contradiction = next((c for c in (session.contradictions or []) if not c.get("explored")), None)
    next_name = {"REFLECTION": "Reflection", "ALIGNMENT": "Alignment",
                 "TRANSFORMATION": "Transformation", "STORY_COMPLETE": "the close"}.get(next_state, "next")
    if contradiction and next_state != "STORY_COMPLETE":
        dim = contradiction["dim"]
        text = director.generate(
            db, session, "SETUP_NEXT_CHAPTER",
            {"unresolved": f"{dim_phrase(dim, 1)} vs {dim_phrase(dim, -1)}", "next": next_state},
            "anticipation from real uncertainty",
            [f"Still unresolved: you reach for {dim_fragment(dim, 1)} until stakes rise — then {dim_fragment(dim, -1)} wins. {next_name} is where we find out why.",
             f"One open question travels with us: {dim_fragment(dim, 1)} or {dim_fragment(dim, -1)}? The evidence refuses to pick."], max_words=42)
        if text:
            return {"type": "next_thread", "kind": "thread", "text": text}
    threads = director.unresolved_threads(st)
    if threads and next_state != "STORY_COMPLETE":
        t = threads[0]
        text = director.generate(
            db, session, "FORESHADOW", {"thread": t["statement"]}, "quiet promise",
            [f"We're leaving one thing deliberately alone — {t['statement']}. It comes back.",
             f"Still open, on purpose: {t['statement']}."], max_words=30)
        if text:
            director.update_thread(st, t["id"], "developing")
            return {"type": "next_thread", "kind": "thread", "text": text}
    return None


def compose_closing(db: Session, session: DiscoverSession, closing_state: str, next_state: str) -> dict:
    st = director.get_state(db, session)
    cache = (session.practical_context or {}).get("_closing_cache", {})
    if cache.get("state") == closing_state:
        return cache["payload"]
    the_plan = closing_planner.plan(db, session, st, closing_state, next_state)
    beats = COMPOSERS[the_plan["structure"]](db, session, st, the_plan)
    tease = _tease(db, session, st, next_state)
    if tease:
        beats.append(tease)
    st.chapter_closing_style_history = ((st.chapter_closing_style_history or [])
                                        + [the_plan["structure"]])
    payload = {"type": "chapter_closing", "layout": the_plan["structure"],
               "beats": beats, "sections": beats,   # sections: renderer compatibility alias
               "cta": CLOSING_CTA[closing_state], "next": next_state}
    pc = dict(session.practical_context or {})
    pc["_closing_cache"] = {"state": closing_state, "payload": payload}
    session.practical_context = pc
    return payload
