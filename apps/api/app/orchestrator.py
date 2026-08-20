"""Experience orchestration: STATE -> POLICY -> SAFE ACTION -> CONTENT -> RENDER
-> RESPONSE -> SIGNALS -> STATE. Deterministic systems decide WHAT happens;
the LLM only shapes HOW moments are expressed."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from . import closings, content_build, content_policy, interpretation, knowledge, materialization, statemachine
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
        cache = content_build.fresh((session.practical_context or {}).get("_materialization"))
        if cache:
            return _envelope(session, cache)
        payload = materialization.build(db, session)
        pc = dict(session.practical_context or {})
        pc["_materialization"] = content_build.stamped(payload)
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
    counters["_answers_total"] = counters.get("_answers_total", 0) + 1
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
        counters["_last_change"] = _describe_change(session, counters, changes,
                                                    pre_contradictions, pre_status_known)
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
        # a client may legitimately send null/absent/garbage here; a malformed
        # payload must never 500 the response endpoint
        v = max(-1.0, min(1.0, _as_float(payload.get("value"))))
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


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
                 f"Different questions, same answer underneath: {dim_fragment(a['dim'], a['estimate'])}.",
                 "The same thing has come up across several different questions now."], max_words=18)
            lines = [opener] if opener else []
            lines.append(f"You keep choosing {dim_phrase(a['dim'], a['estimate'])}…")
            lines.append(f"…but never at the cost of {dim_phrase(b['dim'], b['estimate'])}." if b
                         else "…and you don't seem to think twice about it.")
            insight = {"summary": f"leans {a['dim']}" + (f" balanced by {b['dim']}" if b else ""),
                       "dims": [{"dim": t["dim"], "dir": 1 if t["estimate"] >= 0 else -1} for t in tops[:2]]}
        else:
            opener = director.generate(
                db, session, "CREATE_CURIOSITY", {"evidence": "thin", "phase": "early"},
                "gentle honesty",
                ["Nothing obvious yet — except that you keep skipping the obvious answer.",
                 "Early days, but the safe option keeps losing."], max_words=16)
            lines = [opener] if opener else []
            lines.append("Let's keep going — there isn't enough here yet to say anything useful.")
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
        lines.append("Early days — don't take this as settled. The next few answers could change it.")
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
    "energy": "work where you decide how it gets done",
    "cognitive": "work that pays you for how you think",
    "social": "work where dealing with people is the job",
    "execution": "work that pays for finishing, not starting",
    "creative": "work where you make the thing",
    "economic": "work where you see what you earn from it",
    "leverage": "work that builds on what you already know",
    "ai_era": "work where tools do more of the hours",
}


def _abstained_directions(db, session) -> dict:
    """The pre-threshold Alignment screen, read as an audit rather than a form.

    Every field is derived from this person's own answers. Where we genuinely
    do not know something we name the specific missing input — never "n/a",
    which asks the reader to feel a gap they cannot see.
    """
    from .dimensions import DIMENSIONS
    from .signals import thinnest_dims
    ev = knowledge.role_analysis_evidence(session)
    tops = top_dims(session, 6, min_confidence=th.DO_NOT_SURFACE)
    if not tops:
        tops = top_dims(session, 6, min_confidence=0.1)

    grouped: dict[str, list] = {}
    for t in tops:
        grouped.setdefault(DIMENSIONS[t["dim"]]["family"], []).append(t)
    ordered = list(grouped.items())[:3]
    if not ordered:
        # even with almost nothing, the screen must hold something honest
        ordered = [(fam, []) for fam in ("energy", "cognitive", "execution")]

    # total_evidence() sums per-dimension hits — one answer can move four
    # dimensions, so it overstates "answers" by a factor. On a screen whose
    # only asset is credibility, count the actual responses.
    answers = 0
    if db is not None:
        from .models import EvidenceItem
        answers = db.query(EvidenceItem).filter_by(session_id=session.id).count()
    lives = []
    for rank, (fam, dims) in enumerate(ordered):
        lead = dims[0] if dims else None
        support = dims[1] if len(dims) > 1 else None
        n = int(lead.get("evidence_count", 0)) if lead else 0
        conf = sum(d.get("confidence", 0) for d in dims) / len(dims) if dims else 0.2

        if lead:
            # the short fragments carry the recognition; the full phrases carry
            # the argument. Saying both in the same field just sounds repetitive.
            frags = [dim_fragment(d["dim"], d["estimate"]) for d in dims[:2]]
            essence = ("what you keep picking: " + " and ".join(frags))
            why_you = (f"Across {n} answers you chose {dim_phrase(lead['dim'], lead['estimate'])}"
                       if n >= 2 else
                       f"You reached for {dim_phrase(lead['dim'], lead['estimate'])}")
            why_you += (f", and {dim_phrase(support['dim'], support['estimate'])} came with it."
                        if support else " — and you didn't go back on it.")
        else:
            essence = "we don't have enough from you yet to say much here"
            why_you = "Nothing here is earned yet. This is the question, not the answer."

        if not lead:
            why_now = "We didn't pick this from your answers. It's just a broad place to start looking."
        elif rank == 0:
            why_now = "This is the clearest thing you've shown us so far."
        else:
            why_now = "Weaker than the first one, but it keeps showing up."

        # only name what we have genuinely never asked about — claiming a blank
        # where the user already answered is the fastest way to lose them
        blank = [d for d in thinnest_dims(session, [fam], 3)
                 if not (session.dimensions or {}).get(d, {}).get("evidence_count")][:2]
        requires = ("Nothing from you yet. What would help: we still don't know how you feel about "
                    + " or ".join(dim_fragment(d, 1) for d in blank) + "."
                    if blank else "Nothing from you yet — this is exploration, not a plan.")

        # a real tension is the SAME dimension pulling both ways, which the
        # session already tracks. Two different dimensions with opposite signs
        # are not a disagreement — claiming otherwise invents a conflict the
        # reader knows they don't have, and the whole screen loses credibility.
        clash = next((c for c in (session.contradictions or [])
                      if not c.get("explored")
                      and DIMENSIONS.get(c.get("dim"), {}).get("family") == fam), None)
        if not lead:
            friction = ("We don't have a read on this yet. Picking it just tells us where to look next.")
        elif clash:
            friction = (f"Your own evidence argues both ways here: part of it wants "
                        f"{dim_phrase(clash['dim'], 1)}, part wants {dim_phrase(clash['dim'], -1)}. "
                        "We're not averaging that away.")
        elif n and n < th.HYPOTHESIS_MIN_EVIDENCE + 1:
            friction = (f"{n} answers is a hint, not proof. It could just as easily be the situation "
                        f"you were in at the time.")
        elif rank == 0:
            friction = ("We've only seen your instincts, not your situation. Until we know what your "
                        "week actually looks like, this is a direction, not a plan.")
        else:
            friction = ("We've never seen this one under real pressure. Nothing you've answered so far "
                        "cost you anything.")

        lives.append({"key": fam, "name": FAMILY_DIRECTIONS.get(fam, fam),
                      "essence": essence, "whyYou": why_you, "whyNow": why_now,
                      "requires": requires, "friction": friction,
                      "confidence": max(25, min(60, int(conf * 100)))})

    missing = []
    gap_facts = ev["factsNeeded"] - ev["facts"]
    gap_dims = ev["supportedNeeded"] - ev["supported"]
    if gap_facts > 0:
        missing.append(f"{gap_facts} more {'piece' if gap_facts == 1 else 'pieces'} of real-world context "
                       "(what you do now, what you've been paid for, how much time you actually have)")
    if gap_dims > 0:
        missing.append(f"{gap_dims} more {'pattern' if gap_dims == 1 else 'patterns'} solid enough to build a plan on")
    seen = (f"Here's what {answers} answers actually show. " if answers >= 2
            else "Here's everything we can honestly say so far. ")
    supporting = (seen + "We don't yet have enough evidence to rank specific jobs or paths against it — "
                  + ("what's missing: " + "; ".join(missing) + "." if missing else
                     "we still don't know enough about your actual work situation."))

    public = {
        "headline": "What your answers say so far.",
        "supportingText": supporting,
        "lives": lives,
        "ask": "Which of these reads most like you?",
        "options": [*({"id": l["key"], "label": l["name"]} for l in lives),
                    {"id": "none", "label": "None of them, fully"}],
    }
    return public


def _make_possible_lives(db, session) -> dict:
    # PART 59/60: no specific directions without minimum professional evidence —
    # broad direction families first, titles only past the threshold
    allowed, reason = knowledge.role_analysis_allowed(session)
    if not allowed:
        # Abstaining is not an excuse to show a blank form. We cannot rank roles
        # yet, but we can read back the evidence we DO hold — the person has to
        # be able to recognise themselves here, or the honesty reads as evasion.
        emit(db, session.id, "opportunity.abstained", {"reason": reason})
        public = _abstained_directions(db, session)
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
        "headline": "Three ways this could actually go.",
        "supportingText": "Not predictions. Just three real options, worth reading properly.",
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
        return "Your answers point here more than anywhere else."
    names = [k.split(":")[1].replace("_", " ") for k, _ in tops]
    return f"What you're strongest at — {' and '.join(names)} — is exactly what this pays for."


def _factors_to_friction(factors: dict) -> str:
    negs = sorted(((k, v) for k, v in factors.items() if v < -0.05), key=lambda kv: kv[1])[:1]
    if not negs:
        return "Mostly just making yourself start small."
    name = negs[0][0].replace("_", " ").replace("fit:", "")
    return f"The catch: {name}."


# ---------------- opportunity map + activation ----------------

def _story_close_payload(session) -> dict:
    """The story ends here. The product begins after an explicit continue."""
    return {"type": "story_close",
            "lines": ["You came here wanting a direction.",
                      "We didn't find a label to put on you.",
                      "We found a pattern in how you choose — and the parts we still don't know.",
                      "Now let's see what that's actually worth."],
            "cta": "See what this can become →",
            "next": "MATERIALIZATION"}


# Internal machine phases map to a SMALL set of safe user-facing hints. The
# client never sees technical terms, and "changed" is only ever true when a
# real state change occurred — that keeps the words meaningful (§5/§6).
CHANGE_KINDS = {
    "contradiction_appeared": "Two of your answers just disagreed.",
    "hypothesis_revised": "That answer changed something.",
    "correction_taken": "Taking your correction — re-reading the earlier answers.",
    "fact_learned": "Noting that — it changes what's worth asking.",
}


# these words only keep their force if they are rare, so a change hint needs a
# genuinely notable event AND breathing room since the last one (§6)
CHANGE_MIN_GAP_INTERACTIONS = 5


def _describe_change(session, counters: dict, hypothesis_changes: list,
                     pre_contradictions: int, pre_status_known: bool) -> dict:
    """What meaningfully changed while processing this answer.

    Ordinary confidence drift is NOT a change worth announcing — almost every
    early answer moves a hypothesis a little. Only a status transition, a new
    contradiction, an explicit correction, or a newly-learned fact qualifies.
    """
    silent = {"changed": False, "kind": None, "note": None}
    if len(session.contradictions or []) > pre_contradictions:
        kind = "contradiction_appeared"
    elif any(c.get("to", {}).get("status") in ("corrected", "contradicted")
             and c.get("from", {}).get("status") not in ("corrected", "contradicted")
             for c in hypothesis_changes):
        kind = "correction_taken"
    elif not pre_status_known and "current_status" in (session.practical_context or {}):
        kind = "fact_learned"
    elif any(c.get("from", {}).get("status") not in (None, "supported")
             and c.get("to", {}).get("status") == "supported"
             for c in hypothesis_changes):
        kind = "hypothesis_revised"     # a hypothesis actually became supported
    else:
        return silent

    # a session-lifetime counter: chapter_interactions resets at every chapter
    # boundary, which would silently reopen the gate mid-journey
    answered = counters.get("_answers_total", 0)
    last = counters.get("_last_change_at")
    if last is not None and answered - last < CHANGE_MIN_GAP_INTERACTIONS:
        return silent                    # real, but too soon to say again
    if kind == counters.get("_last_change_kind"):
        return silent                    # never the same phrase twice running
    # written into the caller's counters dict: submit_response owns persistence
    counters["_last_change_at"] = answered
    counters["_last_change_kind"] = kind
    return {"changed": True, "kind": kind, "note": CHANGE_KINDS[kind]}


def _envelope(session, interaction: dict) -> dict:
    order = ["PROLOGUE", "SELF_DISCOVERY", "SELF_DISCOVERY_CLOSING", "REFLECTION", "REFLECTION_CLOSING",
             "ALIGNMENT", "ALIGNMENT_CLOSING", "TRANSFORMATION", "TRANSFORMATION_CLOSING",
             "STORY_COMPLETE", "MATERIALIZATION", "DISCOVER_WORKSPACE"]
    idx = order.index(session.journey_status)
    within = min(1.0, (session.counters or {}).get("chapter_interactions", 0) / 8)
    progress = min(0.98, (idx + within) / len(order))
    counters = dict(session.counters or {})
    change = counters.pop("_last_change", None) or {"changed": False, "kind": None, "note": None}
    session.counters = counters          # consumed: never repeat a change hint
    return {"interaction": interaction, "state": session.journey_status,
            "chapter": session.journey_status, "estimatedProgress": round(progress, 3),
            "fragments": _fragments(session), "processing": change}


def new_session_defaults() -> dict:
    return {"counters": {"since_reveal": 0, "reveals_this_chapter": 0, "chapter_interactions": 0},
            "engagement": {"skipped": 0}}
