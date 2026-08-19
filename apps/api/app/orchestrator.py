"""Experience orchestration: STATE -> POLICY -> SAFE ACTION -> CONTENT -> RENDER
-> RESPONSE -> SIGNALS -> STATE. Deterministic systems decide WHAT happens;
the LLM only shapes HOW moments are expressed."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from . import closings, content_policy, interpretation, knowledge, materialization, statemachine
from . import narrative_director as director
from . import thresholds as th
from .catalog import INTERACTIONS
from .dimensions import dim_fragment, dim_phrase
from .events import emit
from .llm import gateway
from .models import (CalibrationFeedback, DiscoverSession, Hypothesis, InteractionInstance,
                     ProfileVersion, RecommendationItem, RecommendationSet, Response,
                     Reveal, UserCorrection)
from .opportunities import retrieve_candidates
from .policy import ACTION_TO_TYPE, RuleBasedExperiencePolicy, decide
from .ranking import rank_and_persist
from .rewards import CALIBRATION_REWARD, record as record_reward
from .signals import apply_evidence, top_dims, total_evidence

_policy = RuleBasedExperiencePolicy()


def _fragments(session) -> list[dict]:
    out = []
    for t in top_dims(session, 6, min_confidence=0.18):
        out.append({"t": dim_fragment(t["dim"], t["estimate"]), "s": round(t["confidence"], 2)})
    return out


# ---------------- next experience ----------------

def next_step(db: Session, session: DiscoverSession) -> dict:
    state = session.journey_status

    if state == "PROLOGUE":
        return _envelope(session, {"type": "chapter_transition", "next": "SELF_DISCOVERY"})

    if state == "DISCOVER_WORKSPACE":
        if session.pending_instance_id:
            inst = db.get(InteractionInstance, session.pending_instance_id)
            if inst and inst.status == "pending":
                return _envelope(session, inst.public_content)
        from .workspace import workspace_summary
        return _envelope(session, workspace_summary(db, session))

    if state == "STORY_COMPLETE":
        return _envelope(session, _story_close_payload(session))

    if state == "MATERIALIZATION":
        cache = (session.practical_context or {}).get("_materialization")
        if cache:
            return _envelope(session, cache)
        payload = materialization.build(db, session)
        pc = dict(session.practical_context or {})
        pc["_materialization"] = payload
        session.practical_context = pc
        emit(db, session.id, "materialization.built",
             {"directions": len(payload.get("directions", [])),
              "routes": [r["capability"] for r in payload.get("productRoutes", [])]})
        return _envelope(session, payload)

    if state.endswith("_CLOSING"):
        nxt = statemachine.CLOSING_TO_NEXT[state]
        return _envelope(session, closings.compose_closing(db, session, state, nxt))

    # chapter states — pending instance is re-served (refresh / two tabs)
    if session.pending_instance_id:
        inst = db.get(InteractionInstance, session.pending_instance_id)
        if inst and inst.status == "pending":
            return _envelope(session, inst.public_content)

    decision = decide(db, session, _policy)
    action = decision.chosen_action

    if action == "transition_chapter":
        # chapter objective satisfied -> enter the CLOSING state; the user reads
        # at their own pace and only their explicit continue moves the story
        closing_state = statemachine.TRANSITIONS[state][0]
        statemachine.advance(session, closing_state)
        emit(db, session.id, "chapter.completed", {"chapter": state})
        nxt = statemachine.CLOSING_TO_NEXT[closing_state]
        return _envelope(session, closings.compose_closing(db, session, closing_state, nxt))

    if action == "ask_clarification":
        pending = interpretation.pending_clarification(db, session)
        counters = dict(session.counters or {})
        counters["_clarification_pending"] = False
        session.counters = counters
        if pending:
            definition = pending["definition"]
            content = {**definition["content"], "intent": {
                "reasonCode": "RESOLVE_AMBIGUITY", "targetDimensions": [],
                "purpose": f"resolve ambiguity '{pending['ambiguityKey']}'"}}
            public = _public_content(definition)
            inst = _instance(db, session, definition["id"], "clarification", content, public, decision.id)
            emit(db, session.id, "interaction.impression",
                 {"definition": definition["id"], "type": "clarification", "reason": "RESOLVE_AMBIGUITY"})
            return _envelope(session, inst.public_content)
        # ambiguity resolved itself or lost value — fall through to a normal probe
        decision = decide(db, session, _policy)
        action = decision.chosen_action

    if action in ("show_reveal", "explore_contradiction"):
        payload = _make_reveal(db, session, contradiction=(action == "explore_contradiction"))
        inst = _instance(db, session, None, "reveal", payload["server"], payload["public"], decision.id)
        return _envelope(session, inst.public_content)

    if action == "generate_possible_lives":
        payload = _make_possible_lives(db, session)
        inst = _instance(db, session, None, "possible_lives", payload["server"], payload["public"], decision.id)
        counters = dict(session.counters or {})
        counters["lives_generated"] = True
        session.counters = counters
        return _envelope(session, inst.public_content)

    if action == "close_story":
        # the Final Mirror IS the Transformation closing — the story does not
        # end twice, and nothing auto-advances past it
        counters = dict(session.counters or {})
        counters["final_shown"] = True
        session.counters = counters
        statemachine.advance(session, "TRANSFORMATION_CLOSING")
        emit(db, session.id, "chapter.completed", {"chapter": "TRANSFORMATION"})
        return _envelope(session, closings.compose_closing(
            db, session, "TRANSFORMATION_CLOSING", "STORY_COMPLETE"))

    # signal-gathering interaction from the catalog
    itype = ACTION_TO_TYPE[action]
    definition = _pick_definition(session, itype)
    if definition is None:
        definition = _pick_definition(session, None)  # any unused for chapter
    if definition is None:
        # nothing left worth asking this chapter — that IS the chapter objective:
        # close rather than repeat or pad (bounded journeys)
        closing_state = statemachine.TRANSITIONS[state][0]
        statemachine.advance(session, closing_state)
        emit(db, session.id, "chapter.completed", {"chapter": state, "reason": "pool_exhausted"})
        knowledge.emit_event(db, session, "CHAPTER_OBJECTIVE_REACHED",
                             {"chapter": state, "reason": "no_informative_questions_left"}, importance=0.4)
        nxt = statemachine.CLOSING_TO_NEXT[closing_state]
        return _envelope(session, closings.compose_closing(db, session, closing_state, nxt))
    used = list(session.used_definitions or [])
    used.append(definition["id"])
    session.used_definitions = used
    # machine-readable purpose (decision inspector + learning; never shown raw)
    reason_code = ("HIGH_VALUE_UNCERTAINTY" if any(t in decision.context.get("target_dims", [])
                                                   for t in definition.get("targets", [])) else "COVERAGE")
    intent = {
        "targetDimensions": definition.get("targets", []),
        "reasonCode": reason_code,
        "purpose": f"reduce uncertainty on {', '.join(definition.get('targets', [])[:2]) or 'coverage'}",
        "expectedInformationGain": round(decision.context.get("info_gain", {}).get(action, 0.3), 3),
    }
    content = {**definition["content"], "intent": intent}
    public = _public_content(definition)
    # bridges exist only because something actually changed; the Narrative
    # Director generates them from the event and rejects anything that repeats
    bridge = director.bridge(db, session)
    if not bridge and definition.get("bridge"):
        bridge = director.accept(db, session, definition["bridge"], "CREATE_CURIOSITY")
    if bridge:
        public = {**public, "bridge": bridge}
    inst = _instance(db, session, definition["id"], definition["type"], content, public, decision.id)
    emit(db, session.id, "interaction.impression",
         {"definition": definition["id"], "type": definition["type"], "reason": reason_code})
    return _envelope(session, inst.public_content)


def _eligibility(session: DiscoverSession, d: dict) -> str | None:
    """Deterministic relevance gate. Returns a rejection reason or None."""
    from .professional import status_allows
    chapter = session.journey_status
    pc = session.practical_context or {}
    dims = session.dimensions or {}
    if chapter not in d["chapters"]:
        return "wrong_chapter"
    if d["id"] in (session.used_definitions or []):
        return "already_asked"
    if not status_allows(session, d.get("requires_status")):
        return "incompatible_with_professional_status"
    if d.get("practical_key") and d["practical_key"] in pc:
        return "already_answered_explicitly"
    targets = d.get("targets", [])
    if targets and all(dims.get(t, {}).get("confidence", 0) > 0.72 for t in targets):
        return "low_information_value"
    return None


def _pick_definition(session: DiscoverSession, itype: str | None) -> dict | None:
    rejected: dict[str, str] = {}
    pool = []
    for d in INTERACTIONS:
        if itype is not None and d["type"] != itype:
            continue
        reason = _eligibility(session, d)
        if reason:
            if reason not in ("wrong_chapter", "already_asked"):
                rejected[d["id"]] = reason
            continue
        pool.append(d)
    # keep rejection reasons for the decision inspector
    counters = dict(session.counters or {})
    counters["_last_rejected"] = rejected
    session.counters = counters
    if session.journey_status == "ALIGNMENT":
        unanswered_practical = [d for d in pool if d.get("practical_key")]
        if unanswered_practical:
            return unanswered_practical[0]
    return pool[0] if pool else None


def _instance(db, session, definition_id, itype, content, public, decision_id) -> InteractionInstance:
    inst = InteractionInstance(
        session_id=session.id, definition_id=definition_id, type=itype,
        chapter=session.journey_status, content=content,
        public_content={"id": "", **public}, policy_decision_id=decision_id,
    )
    db.add(inst)
    db.flush()
    inst.public_content = {**inst.public_content, "id": inst.id, "type": itype}
    session.pending_instance_id = inst.id
    return inst


def _public_content(definition: dict) -> dict:
    c = definition["content"]
    pub = {"headline": c.get("headline"), "supportingText": c.get("supportingText")}
    if "options" in c:
        pub["options"] = [{"id": o["id"], "label": o["label"], **({"motif": o["motif"]} if "motif" in o else {})}
                          for o in c["options"]]
    for k in ("left", "right"):
        if k in c:
            pub[k] = {"label": c[k]["label"]}
    for k in ("maxSelect", "minSelect", "placeholder", "help"):
        if k in c:
            pub[k] = c[k]
    return pub


# ---------------- responses ----------------

def submit_response(db: Session, session: DiscoverSession, instance_id: str,
                    payload: dict, latency_ms: int | None) -> dict:
    inst = db.get(InteractionInstance, instance_id)
    if not inst or inst.session_id != session.id:
        return {"ok": False, "error": "unknown interaction"}
    if inst.status != "pending" or session.pending_instance_id != inst.id:
        return {"ok": False, "error": "stale interaction"}  # duplicate/tab race: safely rejected

    response = Response(session_id=session.id, instance_id=inst.id,
                        payload=payload, latency_ms=latency_ms)
    db.add(response)
    db.flush()
    inst.status = "skipped" if payload.get("skipped") else "answered"
    session.pending_instance_id = None

    counters = dict(session.counters or {})
    counters["chapter_interactions"] = counters.get("chapter_interactions", 0) + 1
    recent = list(session.recent_interaction_types or [])
    recent.append(inst.type)
    session.recent_interaction_types = recent[-10:]
    engagement = dict(session.engagement or {})
    if payload.get("skipped"):
        engagement["skipped"] = engagement.get("skipped", 0) + 1
    if payload.get("helpUsed"):
        engagement["help_count"] = engagement.get("help_count", 0) + 1
    if latency_ms:
        engagement["recent_latency"] = ((engagement.get("recent_latency") or []) + [min(60000, latency_ms)])[-5:]
    session.engagement = engagement
    emit(db, session.id, "interaction.responded",
         {"type": inst.type, "definition": inst.definition_id, "skipped": bool(payload.get("skipped"))})
    record_reward(db, inst.policy_decision_id,
                  {"completed": 0.0 if payload.get("skipped") else 1.0,
                   "latency_ms": latency_ms or 0})

    if not payload.get("skipped"):
        pre_contradictions = len(session.contradictions or [])
        pre_status_known = "current_status" in (session.practical_context or {})
        targets = [t for t in ((inst.content or {}).get("intent", {}).get("targetDimensions", []))]
        pre_conf = {t: (session.dimensions or {}).get(t, {}).get("confidence", 0) for t in targets}
        _apply_typed_response(db, session, inst, response, counters)
        # the Narrative Director observes the ACTUAL state change, with its
        # specifics — copy is later derived from this, never from rotation
        if len(session.contradictions or []) > pre_contradictions:
            new_c = (session.contradictions or [])[-1]
            director.observe(db, session, {"kind": "contradiction_new", "dim": new_c.get("dim")})
        elif not pre_status_known and "current_status" in (session.practical_context or {}):
            status = (session.practical_context or {}).get("current_status", "")
            director.observe(db, session, {"kind": "eligibility_changed",
                                           "fact": f"where you are right now ({str(status).replace('_', ' ')})"})
        else:
            resolved = next((t for t in targets
                             if (session.dimensions or {}).get(t, {}).get("confidence", 0) >= 0.6 > pre_conf.get(t, 0)), None)
            last_insight = (session.revealed_insights or [])[-1:]
            if resolved:
                director.observe(db, session, {"kind": "uncertainty_resolved", "dim": resolved,
                                               "value": (session.dimensions or {}).get(resolved, {}).get("estimate", 1)})
            elif last_insight and last_insight[0].get("answer") == "no":
                director.observe(db, session, {"kind": "correction_received",
                                               "summary": last_insight[0].get("summary", "that reading")})
            elif targets and (session.counters or {}).get("chapter_interactions", 0) % 3 == 2:
                low = min(targets, key=lambda t: (session.dimensions or {}).get(t, {}).get("confidence", 0))
                director.observe(db, session, {"kind": "probe_new_ground", "dim": low})
        # PROCESS RESPONSE → UPDATE FACTS → EVIDENCE → HYPOTHESES → …
        changes = knowledge.sync_hypotheses(db, session, trigger=f"response:{inst.type}")
        counters["_last_hypothesis_changes"] = changes[-6:]
    else:
        counters["since_reveal"] = counters.get("since_reveal", 0) + 1
    pending = interpretation.pending_clarification(db, session)
    counters["_clarification_pending"] = bool(pending)
    session.counters = counters
    return {"ok": True}


def _apply_typed_response(db, session, inst, response, counters):
    c = inst.content
    payload = response.payload
    itype = inst.type

    if itype in ("visual_choice", "scenario_choice"):
        opt = next((o for o in c.get("options", []) if o["id"] == payload.get("optionId")), None)
        if opt:
            apply_evidence(db, session, opt.get("signals", []), itype, inst.id, response.id, response.latency_ms)
        key = _practical_key(inst)
        if key:
            pc = dict(session.practical_context or {})
            pc[key] = payload.get("optionId")
            session.practical_context = pc
        counters["since_reveal"] = counters.get("since_reveal", 0) + 1

    elif itype in ("binary_tension", "spectrum"):
        v = max(-1.0, min(1.0, float(payload.get("value", 0))))
        ev = []
        left, right = c.get("left", {}), c.get("right", {})
        if left.get("dim"):
            ev.append({"dim": left["dim"], "delta": -v * left.get("dir", 1), "weight": 0.55 * abs(v) + 0.1})
        if right.get("dim") and right.get("dim") != left.get("dim"):
            ev.append({"dim": right["dim"], "delta": v * right.get("dir", 1), "weight": 0.55 * abs(v) + 0.1})
        apply_evidence(db, session, ev, itype, inst.id, response.id, response.latency_ms)
        key = _practical_key(inst)
        if key:
            pc = dict(session.practical_context or {})
            pc[key] = round(v, 2)
            session.practical_context = pc
        counters["since_reveal"] = counters.get("since_reveal", 0) + 1

    elif itype in ("forced_rank", "object_sort"):
        chosen = payload.get("optionIds", [])[: c.get("maxSelect", 4)]
        for o in c.get("options", []):
            if o["id"] in chosen:
                apply_evidence(db, session, o.get("signals", []), itype, inst.id, response.id)
            else:
                released = [{**s, "delta": -s["delta"] * 0.35, "weight": min(0.25, s["weight"] * 0.5)}
                            for s in o.get("signals", [])]
                apply_evidence(db, session, released, f"{itype}_released", inst.id, response.id)
        key = _practical_key(inst)
        if key:
            pc = dict(session.practical_context or {})
            pc[key] = chosen
            session.practical_context = pc
        counters["since_reveal"] = counters.get("since_reveal", 0) + 1

    elif itype == "micro_reflection":
        text = str(payload.get("text", ""))[:300]
        counters["reflections"] = counters.get("reflections", 0) + 1
        if text.strip():
            pc = dict(session.practical_context or {})
            pc["notes"] = (pc.get("notes", []) + [{"prompt": c.get("headline"), "text": text}])[-6:]
            session.practical_context = pc
            key = _practical_key(inst)
            if key:
                pc = dict(session.practical_context or {})
                pc[key] = text
                session.practical_context = pc
            # free text is free text: the conservative two-pass interpreter
            # runs on every typed answer (facts + ambiguities, never leaps)
            interpretation.interpret_free_text(db, session, text, inst.id)
            if _definition_field(inst, "extract") == "professional":
                from .professional import extract_profession
                changed = extract_profession(db, session, text)
                if "builds_things" in changed or "commercial_evidence" in changed:
                    # a professional fact just made an early instinct retrospectively
                    # meaningful — a real callback, drawn from actual history (§36)
                    from .surprise import earliest_evidence
                    first = earliest_evidence(db, session, ["experimentation", "implementation_affinity", "initiative"])
                    if first:
                        director.observe(db, session, {
                            "kind": "callback", "dim": first["dim"], "value": 1,
                            "earlier": first.get("headline") or "one of your first choices",
                            "now": "what you just told us about your work"})
                    else:
                        director.observe(db, session, {"kind": "eligibility_changed",
                                                       "fact": "what you actually do"})
                elif changed:
                    director.observe(db, session, {"kind": "eligibility_changed",
                                                   "fact": "what you told us about your work"})
            else:
                extraction = gateway.generate(db, "micro_reflection_extraction_v1",
                                              {"prompt": c.get("headline"), "text": text})
                if extraction and extraction.get("signals"):
                    clean = [s for s in extraction["signals"][:3] if isinstance(s, dict)]
                    apply_evidence(db, session, clean, "micro_reflection", inst.id, response.id)
        counters["since_reveal"] = counters.get("since_reveal", 0) + 1

    elif itype == "clarification":
        key = (c or {}).get("ambiguityKey")
        if key and payload.get("optionId"):
            changed = interpretation.apply_clarification(db, session, key, payload["optionId"])
            if changed:
                from .professional import set_position
                if "hands_on_technical" in changed or "builds_things" in changed:
                    set_position(session, {"domain": "software"})
        counters["since_reveal"] = counters.get("since_reveal", 0) + 1

    elif itype == "reveal":
        insight = c.get("insight", {})
        answer = payload.get("optionId", "")
        db.add(CalibrationFeedback(session_id=session.id, reveal_id=c.get("reveal_id"), answer=answer))
        emit(db, session.id, "reveal.calibrated", {"answer": answer})
        record_reward(db, inst.policy_decision_id, {"calibration": CALIBRATION_REWARD.get(answer, 0.4)})
        dims = insight.get("dims", [])
        if answer in ("yes", "first"):
            apply_evidence(db, session, [{"dim": d["dim"], "delta": 0.5 * d["dir"], "weight": 1.0} for d in dims], "calibration_agree", inst.id)
        elif answer in ("kind_of", "depends"):
            apply_evidence(db, session, [{"dim": d["dim"], "delta": 0.2 * d["dir"], "weight": 0.35} for d in dims], "calibration_partial", inst.id)
        elif answer in ("no", "second"):
            db.add(UserCorrection(session_id=session.id, insight_summary=insight.get("summary", ""), dims=dims))
            apply_evidence(db, session, [{"dim": d["dim"], "delta": -0.6 * d["dir"], "weight": 1.4} for d in dims], "calibration_correction", inst.id)
            for d in dims:
                knowledge.record_correction(db, session, d["dim"], "not_really",
                                            {"insight": insight.get("summary", "")},
                                            policy_version=_policy.version)
        insights = list(session.revealed_insights or [])
        insights.append({"summary": insight.get("summary"), "answer": answer})
        session.revealed_insights = insights[-8:]
        if insight.get("contradiction"):
            contradictions = [dict(x) for x in (session.contradictions or [])]
            for x in contradictions:
                if x["dim"] == insight["contradiction"]:
                    x["explored"] = True
            session.contradictions = contradictions
        counters["since_reveal"] = 0
        counters["reveals_this_chapter"] = counters.get("reveals_this_chapter", 0) + 1

    elif itype == "possible_lives":
        pc = dict(session.practical_context or {})
        pc["resonant_life"] = None if payload.get("optionId") == "none" else payload.get("optionId")
        session.practical_context = pc
        counters["life_resonance_recorded"] = True
        emit(db, session.id, "opportunity.resonance", {"choice": payload.get("optionId")})

    elif itype == "final":
        statemachine.advance(session, "TRANSFORMATION_CLOSING")
        emit(db, session.id, "chapter.completed", {"chapter": "TRANSFORMATION"})


def _definition_field(inst, field: str):
    for d in INTERACTIONS:
        if d["id"] == inst.definition_id:
            return d.get(field)
    return None


def _practical_key(inst) -> str | None:
    for d in INTERACTIONS:
        if d["id"] == inst.definition_id:
            return d.get("practical_key")
    from .workspace import QUESTIONS
    for q in QUESTIONS:
        if q["id"] == inst.definition_id:
            return q.get("practical_key")
    return None


# ---------------- chapter transitions ----------------

def acknowledge_transition(db: Session, session: DiscoverSession, target: str) -> dict:
    statemachine.advance(session, target)  # raises on invalid jumps
    counters = dict(session.counters or {})
    counters.update({"since_reveal": 0, "reveals_this_chapter": 0, "chapter_interactions": 0})
    session.counters = counters
    emit(db, session.id, "chapter.started" if statemachine.is_chapter(target) else f"stage.{target.lower()}", {"state": target})
    if target == "STORY_COMPLETE":
        _checkpoint_profile(db, session, "story_complete")
        emit(db, session.id, "discover.story_complete", {})
    elif target == "MATERIALIZATION":
        # the profile keeps evolving after the story — new versions, not edits
        _checkpoint_profile(db, session, "materialization")
        emit(db, session.id, "materialization.entered", {})
    elif target == "DISCOVER_WORKSPACE":
        emit(db, session.id, "workspace.entered", {})
    elif statemachine.is_chapter(target) and target != "SELF_DISCOVERY":
        _checkpoint_profile(db, session, f"chapter_start:{target}")
    return {"ok": True}


def _checkpoint_profile(db, session, checkpoint: str) -> ProfileVersion:
    pv = ProfileVersion(
        session_id=session.id, checkpoint=checkpoint,
        dimensions=session.dimensions or {}, contradictions=session.contradictions or [],
        corrections=[{"summary": c.insight_summary} for c in
                     db.query(UserCorrection).filter_by(session_id=session.id).all()],
        practical_context=session.practical_context or {},
        evidence_count=total_evidence(session),
    )
    db.add(pv)
    db.flush()
    emit(db, session.id, "profile.version_created", {"checkpoint": checkpoint, "id": pv.id})
    return pv


# ---------------- syntheses (facts first, LLM expression second) ----------------

def _make_reveal(db, session, contradiction: bool) -> dict:
    tops = top_dims(session, 3)
    facts = {"topDimensions": [{"dim": t["dim"], "estimate": round(t["estimate"], 2),
                                "phrase": dim_phrase(t["dim"], t["estimate"])} for t in tops],
             "corrections": [i for i in (session.revealed_insights or []) if i.get("answer") == "no"]}
    insight: dict = {"summary": "", "dims": []}
    lines: list[str]
    if contradiction:
        c = next((x for x in (session.contradictions or []) if not x.get("explored")), None)
        dim = c["dim"] if c else (tops[0]["dim"] if tops else "autonomy")
        est = (session.dimensions or {}).get(dim, {}).get("estimate", 0)
        facts["contradiction"] = {"dim": dim, "sideA": dim_phrase(dim, 1), "sideB": dim_phrase(dim, -1)}
        lines = ["There are two versions of you showing up.",
                 f"One keeps choosing {dim_phrase(dim, 1)}.",
                 f"The other quietly protects {dim_phrase(dim, -1)}.",
                 "That's not noise. That's usually where the interesting part lives."]
        out = gateway.generate(db, "reflection_synthesis_v1", facts)
        if out and isinstance(out.get("lines"), list) and len(out["lines"]) >= 2:
            lines = [str(l)[:140] for l in out["lines"][:4]]
        insight = {"summary": f"mixed signals on {dim}", "dims": [{"dim": dim, "dir": 1 if est >= 0 else -1}],
                   "contradiction": dim}
        calibration = [{"id": "first", "label": "The first, mostly"},
                       {"id": "second", "label": "The second, mostly"},
                       {"id": "depends", "label": "Depends on the situation"}]
    else:
        if tops:
            a = tops[0]
            b = tops[1] if len(tops) > 1 else None
            opener = director.generate(
                db, session, "CONNECT_PREVIOUS_ANSWERS",
                {"strongest": dim_phrase(a["dim"], a["estimate"]),
                 "evidenceCount": a.get("evidence_count", 0)},
                "recognition, slightly surprising",
                [f"{a.get('evidence_count', 2)} answers in, one thing keeps returning.",
                 f"Across very different questions, the same pull: {dim_fragment(a['dim'], a['estimate'])}.",
                 "A pattern has outlived several different questions now."], max_words=18)
            lines = [opener] if opener else []
            lines.append(f"You keep choosing {dim_phrase(a['dim'], a['estimate'])}…")
            lines.append(f"…but never at the cost of {dim_phrase(b['dim'], b['estimate'])}." if b
                         else "…and you don't seem to hesitate about it.")
            insight = {"summary": f"leans {a['dim']}" + (f" balanced by {b['dim']}" if b else ""),
                       "dims": [{"dim": t["dim"], "dir": 1 if t["estimate"] >= 0 else -1} for t in tops[:2]]}
        else:
            opener = director.generate(
                db, session, "CREATE_CURIOSITY", {"evidence": "thin", "phase": "early"},
                "gentle honesty",
                ["Nothing loud yet — but you don't reach for the obvious option.",
                 "Early days: the obvious answers keep losing to less obvious ones."], max_words=16)
            lines = [opener] if opener else []
            lines.append("Let's keep going — the shape isn't settled yet.")
        out = gateway.generate(db, "early_reveal_v1", facts)
        if out and isinstance(out.get("lines"), list) and len(out["lines"]) >= 2:
            lines = [str(l)[:140] for l in out["lines"][:4]]
        calibration = [{"id": "yes", "label": "Feels like me"},
                       {"id": "kind_of", "label": "Kind of"},
                       {"id": "no", "label": "Not really"}]
    # abstention + overinterpretation guard (PART 15/23): a claim must not be
    # stronger than its evidence; below the observation band, say so honestly
    top_conf = tops[0]["confidence"] if tops else 0.0
    risk = knowledge.overinterpretation_risk(0.7, top_conf)
    if not contradiction and tops and top_conf < th.MAY_TEST:
        lines = [l for l in lines]
        lines.append("Early read — hold it loosely; the next answers can still overturn it.")
    lines = [l for l in lines if content_policy.validate(l)]
    facts["overinterpretationRisk"] = risk
    reveal = Reveal(session_id=session.id, kind="contradiction" if contradiction else "pattern",
                    lines=lines, insight=insight)
    db.add(reveal)
    db.flush()
    emit(db, session.id, "reveal.shown", {"kind": reveal.kind})
    server = {"insight": insight, "reveal_id": reveal.id}
    public = {"lines": lines, "calibration": calibration}
    return {"server": server, "public": public}


FAMILY_DIRECTIONS = {
    "energy": "work with more room to move than you have now",
    "cognitive": "work that leans on how you actually think",
    "social": "work where the people layer is the work",
    "execution": "work rewarded for finishing, not just starting",
    "creative": "work where making something is the point",
    "economic": "work with a more direct line to what it earns",
    "leverage": "work that compounds what you already know",
    "ai_era": "work that multiplies through tools instead of hours",
}


def _make_possible_lives(db, session) -> dict:
    # PART 59/60: no specific directions without minimum professional evidence —
    # broad direction families first, titles only past the threshold
    allowed, reason = knowledge.role_analysis_allowed(session)
    if not allowed:
        from .dimensions import DIMENSIONS
        tops = top_dims(session, 3, min_confidence=th.DO_NOT_SURFACE)
        if not tops:
            tops = top_dims(session, 3, min_confidence=0.1)
        families = []
        for t in tops:
            fam = DIMENSIONS[t["dim"]]["family"]
            if fam not in [f["id"] for f in families]:
                families.append({"id": fam, "label": FAMILY_DIRECTIONS.get(fam, fam)})
        if not families:
            # even with almost nothing, the screen must hold something honest
            families = [{"id": fam, "label": FAMILY_DIRECTIONS[fam]}
                        for fam in ("energy", "cognitive", "execution")]
        emit(db, session.id, "opportunity.abstained", {"reason": reason})
        public = {
            "headline": "Broad directions — not verdicts.",
            "supportingText": "We can explore directions, but we don't yet have enough evidence "
                              "to rank specific paths responsibly. These are families, not roles.",
            "lives": [{"key": f["id"], "name": f["label"],
                       "essence": "a direction worth examining, not a recommendation",
                       "whyYou": "your strongest evidence so far points this way",
                       "whyNow": "more professional context would sharpen this",
                       "uses": "the pattern of your supported signals",
                       "requires": "nothing yet — this is exploration",
                       "friction": "unknown — we haven't earned that analysis",
                       "risk": "n/a", "timeToValue": "n/a", "confidence": 35}
                      for f in families[:3]],
            "ask": "Which direction pulls at you?",
            "options": [*({"id": f["id"], "label": f["label"]} for f in families[:3]),
                        {"id": "none", "label": "None of them, fully"}],
        }
        pc = dict(session.practical_context or {})
        pc["_lives"] = public["lives"]
        session.practical_context = pc
        return {"server": {"abstained": reason}, "public": public}

    pv = _checkpoint_profile(db, session, "alignment_lives")
    from .config import settings as _settings
    rec_set = None
    if _settings.world_intelligence_enabled:
        # the living graph, not the seed catalog: capability overlap ×
        # market evidence × eligibility, materialized + snapshotted
        from .world.matching import recommend as world_recommend
        rec_set = world_recommend(db, session, profile_version_id=pv.id)
    if rec_set is None:
        candidates = retrieve_candidates(db, session)
        rec_set = rank_and_persist(db, session, candidates, pv.id)
    items = db.query(RecommendationItem).filter_by(set_id=rec_set.id).order_by(RecommendationItem.rank).all()
    lives = []
    from .models import Opportunity
    for item in items:
        opp = db.get(Opportunity, item.opportunity_id)
        narrative = gateway.generate(db, "opportunity_explanation_v1", {
            "opportunity": {"title": opp.title, "essence": opp.value_proposition},
            "factors": item.factor_contributions,
        }) or {}
        item.narrative = narrative
        lives.append({
            "key": opp.id, "name": opp.title, "essence": opp.value_proposition,
            "whyYou": narrative.get("whyYou") or _factors_to_why(item.factor_contributions),
            "whyNow": narrative.get("whyNow") or opp.description,
            "uses": ", ".join(f"{k.split(':')[1].replace('_', ' ')}" for k in item.factor_contributions if k.startswith("fit:") and item.factor_contributions[k] > 0) or "the pattern of your strongest signals",
            "requires": ", ".join(opp.skill_gaps) or "focused first steps",
            "friction": narrative.get("friction") or _factors_to_friction(item.factor_contributions),
            "risk": opp.risk_profile, "timeToValue": opp.time_to_first_value,
            "confidence": max(35, min(85, int(50 + item.score * 40))),
        })
    emit(db, session.id, "opportunity.generated_set", {"set": rec_set.id})
    session._lives_cache = None  # noqa - transient
    server = {"rec_set": rec_set.id, "lives": lives}
    public = {
        "headline": "Three lives you could actually live.",
        "supportingText": "Not predictions. Possibilities — read them slowly.",
        "lives": lives, "ask": "Which one pulls at you?",
        "options": [*({"id": l["key"], "label": l["name"]} for l in lives), {"id": "none", "label": "None of them, fully"}],
    }
    pc = dict(session.practical_context or {})
    pc["_lives"] = lives
    session.practical_context = pc
    return {"server": server, "public": public}


def _factors_to_why(factors: dict) -> str:
    tops = sorted(((k, v) for k, v in factors.items() if k.startswith("fit:") and v > 0),
                  key=lambda kv: kv[1], reverse=True)[:2]
    if not tops:
        return "The shape of your evidence points here more than anywhere else."
    names = [k.split(":")[1].replace("_", " ") for k, _ in tops]
    return f"Your strongest signals — {' and '.join(names)} — concentrate exactly where this path pays."


def _factors_to_friction(factors: dict) -> str:
    negs = sorted(((k, v) for k, v in factors.items() if v < -0.05), key=lambda kv: kv[1])[:1]
    if not negs:
        return "Mostly the discipline of starting small."
    name = negs[0][0].replace("_", " ").replace("fit:", "")
    return f"The honest tension: {name}."


# ---------------- opportunity map + activation ----------------

def _story_close_payload(session) -> dict:
    """The story ends here. The product begins after an explicit continue."""
    return {"type": "story_close",
            "lines": ["You came here looking for direction.",
                      "We didn't find one label.",
                      "We found a pattern — and the parts that are still open.",
                      "Now let's see what it can actually do."],
            "cta": "See what this can become →",
            "next": "MATERIALIZATION"}


def _envelope(session, interaction: dict) -> dict:
    order = ["PROLOGUE", "SELF_DISCOVERY", "SELF_DISCOVERY_CLOSING", "REFLECTION", "REFLECTION_CLOSING",
             "ALIGNMENT", "ALIGNMENT_CLOSING", "TRANSFORMATION", "TRANSFORMATION_CLOSING",
             "STORY_COMPLETE", "MATERIALIZATION", "DISCOVER_WORKSPACE"]
    idx = order.index(session.journey_status)
    within = min(1.0, (session.counters or {}).get("chapter_interactions", 0) / 8)
    progress = min(0.98, (idx + within) / len(order))
    return {"interaction": interaction, "state": session.journey_status,
            "chapter": session.journey_status, "estimatedProgress": round(progress, 3),
            "fragments": _fragments(session)}


def new_session_defaults() -> dict:
    return {"counters": {"since_reveal": 0, "reveals_this_chapter": 0, "chapter_interactions": 0},
            "engagement": {"skipped": 0}}
