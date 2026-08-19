"""ChapterClosingPlanner — story structure is chosen BEFORE any copy exists.

Flow: chapter complete → gather ACTUAL story events → select a closing
architecture the events support (never repeating the previous chapter's) →
record why → only then generate wording. Chapter identity constrains the
possibilities; it does not dictate one fixed closing (PART 49).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import knowledge
from . import thresholds as th
from .models import (ChapterClosingPlan, DiscoverSession, NarrativeEvent,
                     NarrativeSessionState)
from .signals import top_dims

STRUCTURES = [
    "callback_resolution", "belief_revision", "contradiction", "unexpected_absence",
    "professional_grounding", "resonance_shift", "prediction_test",
    "fragment_reassembly", "open_question", "evidence_strengthening", "reconstruction",
]

CHAPTER_ALLOWED = {
    "SELF_DISCOVERY_CLOSING": ["fragment_reassembly", "evidence_strengthening",
                               "open_question", "callback_resolution"],
    "REFLECTION_CLOSING": ["belief_revision", "contradiction", "callback_resolution",
                           "prediction_test", "evidence_strengthening"],
    "ALIGNMENT_CLOSING": ["professional_grounding", "belief_revision",
                          "unexpected_absence", "resonance_shift"],
    "TRANSFORMATION_CLOSING": ["reconstruction"],
}

EVENT_TO_STRUCTURES = {
    "HYPOTHESIS_COLLAPSED": ["belief_revision"],
    "USER_CORRECTED_SYSTEM": ["belief_revision"],
    "CONTRADICTION_APPEARED": ["contradiction"],
    "OLD_ANSWER_BECAME_RELEVANT": ["callback_resolution"],
    "PROFESSIONAL_CONTEXT_CHANGED_PICTURE": ["professional_grounding"],
    "NEW_FACT_CHANGED_MODEL": ["professional_grounding", "evidence_strengthening"],
    "EXPECTED_PATTERN_DID_NOT_APPEAR": ["unexpected_absence"],
    "PUBLIC_RESONANCE_CHANGED": ["resonance_shift"],
    "HYPOTHESIS_STRENGTHENED": ["evidence_strengthening", "prediction_test"],
    "CHAPTER_OBJECTIVE_REACHED": ["fragment_reassembly", "open_question"],
}


def _detect_absence(db: Session, session: DiscoverSession) -> dict | None:
    """PART 36: what did NOT appear can be the story. If the user verifiably
    works with software but technical-depth signals never firmed up, that
    absence is interesting — and deliberately uninterpreted."""
    pc = session.practical_context or {}
    if not (pc.get("works_with_software") or pc.get("builds_things")
            or (pc.get("professional", {}) or {}).get("domain") == "software"):
        return None
    tech = [(d, s) for d, s in (session.dimensions or {}).items()
            if d in ("mastery", "analytical", "systems_thinking", "abstraction")]
    answered = [s for _, s in tech if s.get("evidence_count", 0) >= 1]
    strong = [s for _, s in tech if s.get("confidence", 0) >= th.WEAK_INTERNAL
              and s.get("estimate", 0) > 0.2]
    if len(answered) >= 2 and not strong:
        return {"expected": "technical depth driving choices",
                "context": "software experience is real", "found": "not consistently"}
    return None


def gather_events(db: Session, session: DiscoverSession) -> list[dict]:
    events: list[dict] = []
    rows = (db.query(NarrativeEvent)
            .filter_by(session_id=session.id, consumed_by_closing=None)
            .order_by(NarrativeEvent.importance.desc()).all())
    for r in rows:
        events.append({"id": r.id, "type": r.type, "importance": r.importance,
                       "payload": r.payload})
    absence = _detect_absence(db, session)
    if absence:
        events.append({"id": None, "type": "EXPECTED_PATTERN_DID_NOT_APPEAR",
                       "importance": 0.65, "payload": absence})
    from .surprise import earliest_evidence
    first = earliest_evidence(db, session, ["experimentation", "implementation_affinity",
                                            "initiative", "autonomy"])
    if first:
        # a callback is only a story event when later evidence made it meaningful
        state = (session.dimensions or {}).get(first["dim"], {})
        if state.get("evidence_count", 0) >= 3:
            events.append({"id": None, "type": "OLD_ANSWER_BECAME_RELEVANT",
                           "importance": 0.6, "payload": first})
    if not events:
        events.append({"id": None, "type": "CHAPTER_OBJECTIVE_REACHED",
                       "importance": 0.3, "payload": {}})
    return events


def plan(db: Session, session: DiscoverSession, st: NarrativeSessionState,
         chapter: str, next_state: str) -> dict:
    events = gather_events(db, session)
    allowed = CHAPTER_ALLOWED[chapter]
    previous = (st.chapter_closing_style_history or [])[-1:]

    scores: dict[str, float] = {}
    driver: dict[str, dict] = {}
    for ev in events:
        for structure in EVENT_TO_STRUCTURES.get(ev["type"], []):
            if structure not in allowed:
                continue
            if scores.get(structure, 0) < ev["importance"]:
                scores[structure] = ev["importance"]
                driver[structure] = ev
    for structure in allowed:                      # every allowed structure stays possible
        scores.setdefault(structure, 0.15)
    for structure in previous:                     # never the same architecture twice running
        scores.pop(structure, None)

    selected = max(scores, key=scores.get) if scores else allowed[0]
    ev = driver.get(selected, events[0])

    tops = top_dims(session, 2, min_confidence=0.3)
    plan_row = ChapterClosingPlan(
        session_id=session.id, chapter=chapter, selected_structure=selected,
        available_events=[{"type": e["type"], "importance": e["importance"]} for e in events],
        why_this_closing=f"driven by {ev['type']} (importance {ev['importance']})",
        what_changed=str(ev["payload"])[:400],
        evidence_ids=[i for hyp in [
            (session.dimensions or {}).get(t["dim"], {}) for t in tops] for i in []],
        open_thread="",
    )
    db.add(plan_row)
    db.flush()
    # mark persisted events consumed so the same change never closes two chapters
    for e in events:
        if e["id"]:
            row = db.get(NarrativeEvent, e["id"])
            if row:
                row.consumed_by_closing = plan_row.id
    return {"structure": selected, "drivingEvent": ev, "events": events, "planId": plan_row.id}
