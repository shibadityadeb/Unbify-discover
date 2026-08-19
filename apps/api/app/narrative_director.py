"""The Narrative Director.

The Experience Policy decides WHAT is useful; this module decides HOW that
useful moment becomes part of the story. It owns per-session narrative state
(threads, beats, rolling copy memory), generates copy from the ACTUAL EVENT
that just happened, attaches an internal intent to every sentence, and rejects
anything that repeats the session's own narration — exactly, semantically, or
stylistically. It is storytelling state only, never psychology.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from . import repetition
from .dimensions import dim_fragment, dim_phrase
from .llm import gateway
from .models import DiscoverSession, NarrativeSessionState

# every rendered story sentence carries one of these
INTENTS = {
    "CONNECT_PREVIOUS_ANSWERS", "INTRODUCE_CONTRADICTION", "ACKNOWLEDGE_EXPLICIT_FACT",
    "CREATE_CURIOSITY", "SHOW_PROGRESS", "OPEN_PROFESSIONAL_CONTEXT", "CLOSE_CHAPTER",
    "INTRODUCE_RESONANCE", "REOPEN_UNCERTAINTY", "SETUP_NEXT_CHAPTER", "CALLBACK",
    "FORESHADOW",
}

CHAPTER_PHASE = {
    "SELF_DISCOVERY": "curiosity", "SELF_DISCOVERY_CLOSING": "curiosity",
    "REFLECTION": "recognition", "REFLECTION_CLOSING": "recognition",
    "ALIGNMENT": "grounding", "ALIGNMENT_CLOSING": "grounding",
    "TRANSFORMATION": "synthesis", "TRANSFORMATION_CLOSING": "synthesis",
}


def get_state(db: Session, session: DiscoverSession) -> NarrativeSessionState:
    st = db.get(NarrativeSessionState, session.id)
    if not st:
        st = NarrativeSessionState(session_id=session.id)
        db.add(st)
        db.flush()
    st.chapter = session.journey_status
    st.emotional_phase = CHAPTER_PHASE.get(session.journey_status, st.emotional_phase or "curiosity")
    return st


def _memory_view(st: NarrativeSessionState) -> dict:
    return {"recent_copy": list(st.recent_copy or []),
            "openings": dict(st.sentence_openings_used or {}),
            "shapes": dict(st.sentence_shapes_used or {}),
            "metaphors": list(st.metaphors_used or []),
            "tics": dict(st.tics_used or {})}


def _commit_copy(st: NarrativeSessionState, text: str, intent: str, chapter: str) -> None:
    mem = repetition.commit(text, _memory_view(st))
    st.recent_copy = mem["recent_copy"]
    st.sentence_openings_used = mem["openings"]
    st.sentence_shapes_used = mem["shapes"]
    st.metaphors_used = mem["metaphors"]
    st.tics_used = mem["tics"]
    st.story_beats_shown = ((st.story_beats_shown or []) + [{"intent": intent, "text": text, "chapter": chapter}])[-60:]


def validate(st: NarrativeSessionState, text: str) -> repetition.RepetitionVerdict:
    return repetition.check(text, _memory_view(st))


def accept(db: Session, session: DiscoverSession, text: str, intent: str) -> str | None:
    """Validation pipeline for one candidate sentence: repetition + style checks;
    commit into rolling memory on acceptance, log rejection otherwise."""
    if not text or intent not in INTENTS:
        return None
    from . import content_policy
    if not content_policy.validate(text):
        st = get_state(db, session)
        st.rejected_copy_log = ((st.rejected_copy_log or [])
                                + [{"text": text[:160], "reasons": ["content_policy"]}])[-30:]
        return None
    st = get_state(db, session)
    verdict = validate(st, text)
    if not verdict:
        st.rejected_copy_log = ((st.rejected_copy_log or []) + [{"text": text[:160], "reasons": verdict.reasons}])[-30:]
        return None
    _commit_copy(st, text, intent, session.journey_status)
    return text


def accept_first(db: Session, session: DiscoverSession, candidates: list[str], intent: str) -> str | None:
    for c in candidates:
        out = accept(db, session, c, intent)
        if out:
            return out
    return None


# ---------------- events ----------------

def observe(db: Session, session: DiscoverSession, event: dict) -> None:
    """Record the actual state change that just happened. Contradictions and
    deliberately-parked answers open narrative threads that MUST return later."""
    st = get_state(db, session)
    st.pending_event = event
    kind = event.get("kind")
    if kind == "contradiction_new" and event.get("dim"):
        open_thread(st, statement=f"tension between {dim_phrase(event['dim'], 1)} and {dim_phrase(event['dim'], -1)}",
                    evidence=[event["dim"]], kind="contradiction")
    if kind == "answer_parked" and event.get("dim"):
        open_thread(st, statement=f"an answer about {dim_fragment(event['dim'], event.get('value', 1))} we left alone on purpose",
                    evidence=[event["dim"]], kind="foreshadow")


def consume_event(db: Session, session: DiscoverSession) -> dict | None:
    st = get_state(db, session)
    ev = st.pending_event
    st.pending_event = None
    return ev


# ---------------- narrative threads (§35) ----------------

def open_thread(st: NarrativeSessionState, statement: str, evidence: list[str], kind: str = "pattern") -> dict:
    threads = list(st.threads or [])
    if any(t["statement"] == statement and t["status"] in ("opened", "developing") for t in threads):
        return next(t for t in threads if t["statement"] == statement)
    thread = {"id": uuid.uuid4().hex[:12], "statement": statement, "kind": kind,
              "relatedEvidenceIds": evidence, "status": "opened", "confidence": 0.4,
              "openedInChapter": st.chapter, "resolvedInChapter": None}
    st.threads = threads + [thread]
    return thread


def update_thread(st: NarrativeSessionState, thread_id: str, status: str, confidence: float | None = None) -> None:
    threads = [dict(t) for t in (st.threads or [])]
    for t in threads:
        if t["id"] == thread_id:
            t["status"] = status
            if confidence is not None:
                t["confidence"] = confidence
            if status in ("resolved", "contradicted"):
                t["resolvedInChapter"] = st.chapter
    st.threads = threads


def unresolved_threads(st: NarrativeSessionState) -> list[dict]:
    return [t for t in (st.threads or []) if t["status"] in ("opened", "developing")]


# ---------------- copy generation (event -> validated language) ----------------

def _llm_moment(db: Session, session: DiscoverSession, st: NarrativeSessionState,
                intent: str, facts: dict, desired_emotion: str, max_words: int = 28) -> str | None:
    """Story copy generation contract (§41): the model sees what changed, why it
    matters, what has already been said, and what to avoid. Structured output."""
    payload = {
        "chapter": session.journey_status,
        "narrativeIntent": intent,
        "whatChanged": facts,
        "unresolvedThreads": [t["statement"] for t in unresolved_threads(st)][:4],
        "recentNarrative": (st.recent_copy or [])[-10:],
        "phrasesToAvoid": (st.recent_copy or [])[-16:],
        "sentenceOpeningsToAvoid": [o for o, n in (st.sentence_openings_used or {}).items() if n >= 1][:16],
        "metaphorsToAvoid": (st.metaphors_used or [])[:10],
        "desiredEmotion": desired_emotion,
        "maxWords": max_words,
    }
    out = gateway.generate(db, "narrative_moment_v1", payload)
    if out and isinstance(out.get("text"), str):
        text = out["text"].strip()
        if 0 < len(text.split()) <= max_words + 8:
            return text
    return None


def generate(db: Session, session: DiscoverSession, intent: str, facts: dict,
             desired_emotion: str, fallbacks: list[str], max_words: int = 28) -> str | None:
    """LLM first (with novelty constraints), then context-specific deterministic
    fallbacks composed from the actual event. Everything passes the same
    validation pipeline; if nothing survives, the moment is silence."""
    st = get_state(db, session)
    candidate = _llm_moment(db, session, st, intent, facts, desired_emotion, max_words)
    if candidate:
        out = accept(db, session, candidate, intent)
        if out:
            return out
        # one regeneration with explicit novelty pressure (avoid list has grown)
        candidate = _llm_moment(db, session, st, intent, facts, desired_emotion + " — say it a completely different way", max_words)
        if candidate:
            out = accept(db, session, candidate, intent)
            if out:
                return out
    return accept_first(db, session, fallbacks, intent)


def bridge(db: Session, session: DiscoverSession) -> str | None:
    """A bridge exists only because something actually changed. The copy is
    derived from that change; no rotation pools, and silence is a valid
    outcome when nothing new can be said freshly."""
    event = consume_event(db, session)
    if not event:
        return None
    kind = event.get("kind")
    dim = event.get("dim")
    # Chapter 1 grammar: LIGHT / FAST / UNPREDICTABLE — mostly observe, explain
    # almost nothing; minor events pass in silence
    if session.journey_status == "SELF_DISCOVERY" and kind in ("uncertainty_resolved", "probe_new_ground"):
        return None
    if kind == "contradiction_new" and dim:
        a, b = dim_fragment(dim, 1), dim_fragment(dim, -1)
        return generate(db, session, "INTRODUCE_CONTRADICTION",
                        {"event": "a contradiction appeared", "sideA": dim_phrase(dim, 1), "sideB": dim_phrase(dim, -1)},
                        "intrigued, not judged",
                        [f"You've now argued for {a} and for {b}. Both looked sincere.",
                         f"{a.capitalize()} won earlier. This time {b} did. Keeping both.",
                         f"Two answers, two directions — {a}, then {b}. Neither cancels the other."])
    if kind == "uncertainty_resolved" and dim:
        frag = dim_fragment(dim, event.get("value", 1))
        return generate(db, session, "SHOW_PROGRESS",
                        {"event": "a dimension became clear", "what": dim_phrase(dim, event.get("value", 1))},
                        "quiet satisfaction",
                        [f"The question of {frag} just stopped being a question.",
                         f"That settles {frag} — three separate answers agree now.",
                         f"{frag.capitalize()}: no longer a guess."])
    if kind == "eligibility_changed":
        fact = event.get("fact", "what you told us")
        return generate(db, session, "ACKNOWLEDGE_EXPLICIT_FACT",
                        {"event": "an explicit fact reshaped what is worth asking", "fact": fact},
                        "grounded",
                        [f"Because of {fact}, several questions just became unnecessary.",
                         f"{str(fact).capitalize()} — that redraws which questions are worth your time.",
                         f"Knowing about {fact} changes what we ask next."])
    if kind == "correction_received":
        summary = event.get("summary", "that reading")
        return generate(db, session, "REOPEN_UNCERTAINTY",
                        {"event": "the user corrected an inference", "corrected": summary},
                        "respectful recalibration",
                        [f"You pushed back on {summary}. Your word beats our inference — recalibrating.",
                         f"We had {summary} wrong, then. The earlier answers get re-read in that light.",
                         f"Correction taken: {summary} isn't you. Something else made it look that way."])
    if kind == "callback" and dim:
        return generate(db, session, "CALLBACK",
                        {"event": "an earlier answer became relevant again",
                         "earlier": event.get("earlier", ""), "now": event.get("now", "")},
                        "recognition",
                        [f"{str(event.get('earlier', 'An early answer')).capitalize()} — it just came back, and this time it fits a pattern.",
                         f"Remember choosing {dim_fragment(dim, event.get('value', 1))}? That wasn't isolated after all."])
    if kind == "probe_new_ground" and dim:
        frag = dim_fragment(dim, 1)
        return generate(db, session, "CREATE_CURIOSITY",
                        {"event": "moving to an unmeasured area", "area": dim_phrase(dim, 1)},
                        "light anticipation",
                        [f"We know almost nothing yet about you and {frag}. Next answer starts that map." .replace(" map", " picture"),
                         f"One blind spot left in this area: {frag}.",
                         f"{frag.capitalize()} — the one part of this chapter still dark."])
    return None
