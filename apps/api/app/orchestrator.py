"""Experience orchestration: STATE -> POLICY -> SAFE ACTION -> CONTENT -> RENDER
-> RESPONSE -> SIGNALS -> STATE. Deterministic systems decide WHAT happens;
the LLM only shapes HOW moments are expressed."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from . import statemachine
from .catalog import INTERACTIONS
from .dimensions import dim_fragment, dim_phrase
from .events import emit
from .llm import gateway
from .models import (CalibrationFeedback, DiscoverSession, InteractionInstance,
                     ProfileVersion, RecommendationItem, RecommendationSet, Response,
                     Reveal, UserCorrection)
from .opportunities import retrieve_candidates
from .policy import ACTION_TO_TYPE, RuleBasedExperiencePolicy, decide
from .ranking import rank_and_persist
from .rewards import CALIBRATION_REWARD, record as record_reward
from .signals import apply_evidence, top_dims, total_evidence

_policy = RuleBasedExperiencePolicy()

# micro-bridges: tiny narrative reasons, used selectively — never under every question
BRIDGES = {
    "contradiction": "Something in your last few choices doesn't completely agree.",
    "probe_thin": "There's one part of your pattern we haven't quite understood yet.",
    "post_reveal": "Let's look at this from another angle.",
    "post_correction": "Got it. Then something else may be creating that pattern.",
    "deepen": "This might seem unrelated for a second.",
    "tension": "There's a tension appearing here.",
}


def _maybe_bridge(session, definition, reason_code: str) -> str | None:
    """Attach a narrative bridge occasionally: definition-supplied first, then
    reason-based, and never two interactions in a row."""
    counters = session.counters or {}
    if definition.get("bridge"):
        return definition["bridge"]
    if counters.get("since_bridge", 9) < 2:
        return None
    if reason_code == "post_correction" and any(
            i.get("answer") == "no" for i in (session.revealed_insights or [])[-1:]):
        return BRIDGES["post_correction"]
    if reason_code in BRIDGES:
        return BRIDGES[reason_code]
    return None


def _fragments(session) -> list[dict]:
    out = []
    for t in top_dims(session, 6, min_confidence=0.18):
        out.append({"t": dim_fragment(t["dim"], t["estimate"]), "s": round(t["confidence"], 2)})
    return out


CHAPTER_CLOSINGS = {
    "REFLECTION": lambda session, tops: [
        "We've collected enough.",
        "Not enough to define you — enough to notice something.",
        (f"So far you've mostly been choosing {dim_phrase(tops[0]['dim'], tops[0]['estimate'])}."
         if tops else "So far you've been choosing instinctively."),
        "Now let's look at the pattern those choices created.",
    ],
    "ALIGNMENT": lambda session, tops: [
        "Understanding the pattern is one thing.",
        "But it doesn't exist in isolation.",
        "You have work. Experience. Things you've already built. Things you can't simply ignore.",
        "Let's put the person we've been discovering back into the real world.",
    ],
    "TRANSFORMATION": lambda session, tops: [
        "We know more now.",
        "Not just what seems natural to you — but what you already have, and where the friction sits.",
        "There's one final thing to do.",
        "Bring it together.",
    ],
}


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

    # chapter states — pending instance is re-served (refresh / two tabs)
    if session.pending_instance_id:
        inst = db.get(InteractionInstance, session.pending_instance_id)
        if inst and inst.status == "pending":
            return _envelope(session, inst.public_content)

    decision = decide(db, session, _policy)
    action = decision.chosen_action

    if action == "transition_chapter":
        nxt = statemachine.TRANSITIONS[state][0]
        closing_fn = CHAPTER_CLOSINGS.get(nxt)
        closing = closing_fn(session, top_dims(session, 1)) if closing_fn else []
        return _envelope(session, {"type": "chapter_transition", "next": nxt, "closing": closing})

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
        payload = _make_final(db, session)
        inst = _instance(db, session, None, "final", payload["server"], payload["public"], decision.id)
        counters = dict(session.counters or {})
        counters["final_shown"] = True
        session.counters = counters
        return _envelope(session, inst.public_content)

    # signal-gathering interaction from the catalog
    itype = ACTION_TO_TYPE[action]
    definition = _pick_definition(session, itype)
    if definition is None:
        definition = _pick_definition(session, None)  # any unused for chapter
    used = list(session.used_definitions or [])
    used.append(definition["id"])
    session.used_definitions = used
    # why are we asking this? (internal intent, occasionally surfaced as a bridge)
    reason_code = ("probe_thin" if any(t in decision.context.get("target_dims", [])
                                       for t in definition.get("targets", [])) else "deepen")
    counters_now = session.counters or {}
    if counters_now.get("since_reveal", 9) == 0 and counters_now.get("reveals_this_chapter", 0) > 0:
        reason_code = "post_reveal"
    intent = {
        "targetDimensions": definition.get("targets", []),
        "reasonCode": reason_code,
        "expectedInformationGain": round(decision.context.get("info_gain", {}).get(action, 0.3), 3),
    }
    content = {**definition["content"], "intent": intent}
    public = _public_content(definition)
    bridge = _maybe_bridge(session, definition, reason_code)
    counters = dict(session.counters or {})
    if bridge:
        public = {**public, "bridge": bridge}
        counters["since_bridge"] = 0
    else:
        counters["since_bridge"] = counters.get("since_bridge", 0) + 1
    session.counters = counters
    inst = _instance(db, session, definition["id"], definition["type"], content, public, decision.id)
    emit(db, session.id, "interaction.impression",
         {"definition": definition["id"], "type": definition["type"], "reason": reason_code})
    return _envelope(session, inst.public_content)


def _pick_definition(session: DiscoverSession, itype: str | None) -> dict | None:
    from .professional import status_allows
    chapter = session.journey_status
    used = set(session.used_definitions or [])
    practical_needed = chapter == "ALIGNMENT"
    pool = [d for d in INTERACTIONS
            if chapter in d["chapters"] and d["id"] not in used
            and status_allows(session, d.get("requires_status"))
            and (itype is None or d["type"] == itype)]
    if practical_needed:
        unanswered_practical = [d for d in pool if d.get("practical_key")
                                and d["practical_key"] not in (session.practical_context or {})]
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
        _apply_typed_response(db, session, inst, response, counters)
    else:
        counters["since_reveal"] = counters.get("since_reveal", 0) + 1
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
            if _definition_field(inst, "extract") == "professional":
                from .professional import extract_profession
                extract_profession(db, session, text)
            else:
                extraction = gateway.generate(db, "micro_reflection_extraction_v1",
                                              {"prompt": c.get("headline"), "text": text})
                if extraction and extraction.get("signals"):
                    clean = [s for s in extraction["signals"][:3] if isinstance(s, dict)]
                    apply_evidence(db, session, clean, "micro_reflection", inst.id, response.id)
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
        # story ends only here — Chapter 4 complete
        statemachine.advance(session, "STORY_COMPLETE")
        _checkpoint_profile(db, session, "story_complete")
        emit(db, session.id, "discover.story_complete", {})


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
    if statemachine.is_chapter(target) and target != "SELF_DISCOVERY":
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
            lines = ["Interesting.", f"You keep choosing {dim_phrase(a['dim'], a['estimate'])}…"]
            lines.append(f"…but never at the cost of {dim_phrase(b['dim'], b['estimate'])}." if b
                         else "…and you don't seem to hesitate about it.")
            insight = {"summary": f"leans {a['dim']}" + (f" balanced by {b['dim']}" if b else ""),
                       "dims": [{"dim": t["dim"], "dir": 1 if t["estimate"] >= 0 else -1} for t in tops[:2]]}
        else:
            lines = ["Interesting.", "You don't reach for the obvious option.", "Let's keep going — something is taking shape."]
        out = gateway.generate(db, "early_reveal_v1", facts)
        if out and isinstance(out.get("lines"), list) and len(out["lines"]) >= 2:
            lines = [str(l)[:140] for l in out["lines"][:4]]
        calibration = [{"id": "yes", "label": "Feels like me"},
                       {"id": "kind_of", "label": "Kind of"},
                       {"id": "no", "label": "Not really"}]
    reveal = Reveal(session_id=session.id, kind="contradiction" if contradiction else "pattern",
                    lines=lines, insight=insight)
    db.add(reveal)
    db.flush()
    emit(db, session.id, "reveal.shown", {"kind": reveal.kind})
    server = {"insight": insight, "reveal_id": reveal.id}
    public = {"lines": lines, "calibration": calibration}
    return {"server": server, "public": public}


def _make_possible_lives(db, session) -> dict:
    pv = _checkpoint_profile(db, session, "alignment_lives")
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


def _make_final(db, session) -> dict:
    tops = top_dims(session, 5, min_confidence=0.15)
    contradiction = (session.contradictions or [None])[0]
    facts = {
        "supportedPatterns": [{"dim": t["dim"], "estimate": round(t["estimate"], 2),
                               "phrase": dim_phrase(t["dim"], t["estimate"]),
                               "confidence": round(t["confidence"], 2)} for t in tops],
        "contradictions": [{"dim": c["dim"], "sideA": dim_phrase(c["dim"], 1), "sideB": dim_phrase(c["dim"], -1)}
                           for c in (session.contradictions or [])[:2]],
        "assets": (session.practical_context or {}).get("assets", []),
        "constraints": {k: v for k, v in (session.practical_context or {}).items()
                        if k in ("hours_per_week", "money_pressure", "risk_appetite", "geography")},
        "resonantLife": (session.practical_context or {}).get("resonant_life"),
    }
    mirror = _deterministic_mirror(session, tops, contradiction)
    opening = ["At the beginning, you answered by instinct.",
               "Later, you corrected the picture yourself.",
               "At first, some of it looked contradictory.", "It isn't."]
    lives = (session.practical_context or {}).get("_lives", [])
    chosen = (session.practical_context or {}).get("resonant_life")
    first_life = next((l for l in lives if l["key"] == chosen), lives[0] if lives else None)
    next_action = {"headline": "One small next step",
                   "text": (f"Take one honest step toward {first_life['name']}: " if first_life else "")
                           + "give it two focused hours this week and notice how it feels.",
                   "note": "Not a life plan. Just the next honest experiment."}
    out = gateway.generate(db, "transformation_v1", facts)
    if out and isinstance(out.get("mirror"), list) and len(out["mirror"]) >= 4:
        opening = [str(l)[:110] for l in (out.get("opening") or opening)[:4]]
        mirror = [{"label": str(m.get("label", ""))[:44], "text": str(m.get("text", ""))[:180]}
                  for m in out["mirror"][:7]]
        if out.get("nextAction", {}).get("text"):
            next_action = {"headline": str(out["nextAction"].get("headline", "One small next step"))[:44],
                           "text": str(out["nextAction"]["text"])[:160],
                           "note": str(out["nextAction"].get("note", next_action["note"]))[:80]}
    server = {"facts": facts}
    public = {"opening": opening, "mirror": mirror, "nextAction": next_action,
              "closing": ["This isn't a verdict.",
                          "It's the clearest picture we can build from what you've shown us so far.",
                          "And it can keep changing with you.",
                          "Your discovery is complete."]}
    return {"server": server, "public": public}


def _deterministic_mirror(session, tops, contradiction) -> list[dict]:
    items = []
    if tops:
        items.append({"label": "Your natural energy",
                      "text": f"You move toward {dim_phrase(tops[0]['dim'], tops[0]['estimate'])} — it shows up in almost everything you chose."})
    if len(tops) > 1:
        items.append({"label": "How you create value",
                      "text": f"Your value concentrates where {dim_phrase(tops[1]['dim'], tops[1]['estimate'])} matters more than speed or polish."})
    protect = top_dims(session, 1, min_confidence=0.15, families=["energy", "economic"])
    items.append({"label": "What you protect",
                  "text": f"When things get real, you protect {dim_phrase(protect[0]['dim'], protect[0]['estimate'])} before anything else."
                  if protect else "You protect optionality — the right to change your mind."})
    lev = top_dims(session, 1, min_confidence=0.15, families=["leverage", "ai_era"])
    items.append({"label": "Your unusual edge",
                  "text": f"You underrate {dim_phrase(lev[0]['dim'], lev[0]['estimate'])} — it appeared quietly and repeatedly."
                  if lev else "Your edge is honesty about what you don't know — rarer than it sounds."})
    items.append({"label": "Your current reality",
                  "text": "Your time and pressure aren't obstacles to the plan. They are the plan's shape."})
    items.append({"label": "What may be holding you back",
                  "text": f"The tug between {dim_phrase(contradiction['dim'], 1)} and {dim_phrase(contradiction['dim'], -1)} — treat it as a constraint to design around, not a flaw."
                  if contradiction else "Waiting for certainty that this kind of choice never provides."})
    return items


# ---------------- opportunity map + activation ----------------

def _story_close_payload(session) -> dict:
    return {"type": "story_close",
            "lines": ["You came here looking for direction.",
                      "We didn't find one label.",
                      "We found a pattern.",
                      "And now we can do something with it."],
            "cta": "Enter your workspace"}


def _envelope(session, interaction: dict) -> dict:
    order = ["PROLOGUE", "SELF_DISCOVERY", "REFLECTION", "ALIGNMENT", "TRANSFORMATION",
             "STORY_COMPLETE", "DISCOVER_WORKSPACE"]
    idx = order.index(session.journey_status)
    within = min(1.0, (session.counters or {}).get("chapter_interactions", 0) / 8)
    progress = min(0.98, (idx + within) / len(order))
    return {"interaction": interaction, "state": session.journey_status,
            "chapter": session.journey_status, "estimatedProgress": round(progress, 3),
            "fragments": _fragments(session)}


def new_session_defaults() -> dict:
    return {"counters": {"since_reveal": 0, "reveals_this_chapter": 0, "chapter_interactions": 0},
            "engagement": {"skipped": 0}}
