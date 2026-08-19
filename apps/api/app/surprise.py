"""Story Surprise Engine.

Public-figure resonance is ONE surprise mechanism, not the only one. Each
chapter close may carry one additional surprise beat, chosen from formats the
session's ACTUAL state supports, never repeating a format already used.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .dimensions import dim_fragment, dim_phrase
from .models import DiscoverSession, NarrativeSessionState, SignalEvidence, InteractionInstance
from .signals import top_dims


def earliest_evidence(db: Session, session: DiscoverSession, dims: list[str]) -> dict | None:
    """Real user history for callbacks — never fake memories."""
    rows = (db.query(SignalEvidence).filter_by(session_id=session.id)
            .order_by(SignalEvidence.created_at.asc()).all())
    for row in rows:
        hit = next((d for d in (row.construct_updates or {}) if d in dims and row.construct_updates[d] > 0), None)
        if not hit:
            continue
        headline = None
        if row.instance_id:
            inst = db.get(InteractionInstance, row.instance_id)
            if inst:
                headline = (inst.content or {}).get("headline")
        return {"dim": hit, "headline": headline, "source": row.source}
    return None


def choose(db: Session, session: DiscoverSession, st: NarrativeSessionState,
           chapter: str, has_resonance: bool) -> dict | None:
    """Pick one supported surprise format not yet used this session. Resonance
    is composed separately by the closings; this adds a second, varied beat."""
    used = set(st.surprises_shown or [])
    contradiction = next((c for c in (session.contradictions or []) if not c.get("explored")), None)

    def take(fmt: str, payload: dict) -> dict:
        st.surprises_shown = list(used | {fmt})
        return {"format": fmt, **payload}

    if contradiction and "contradiction_reveal" not in used and chapter != "SELF_DISCOVERY_CLOSING":
        dim = contradiction["dim"]
        return take("contradiction_reveal", {
            "heading": "One thing that refuses to sit still",
            "text": f"You've pulled toward {dim_phrase(dim, 1)} and toward {dim_phrase(dim, -1)} in the same hour. "
                    "We're keeping both on the table — the answer is probably situational, and worth finding.",
        })
    if chapter in ("ALIGNMENT_CLOSING", "TRANSFORMATION_CLOSING") and "previous_answer_return" not in used:
        first = earliest_evidence(db, session, ["experimentation", "implementation_affinity", "initiative"])
        if first:
            frag = dim_fragment(first["dim"], 1)
            ref = f'"{first["headline"]}"' if first.get("headline") else "one of your very first choices"
            return take("previous_answer_return", {
                "heading": "Something from the beginning",
                "text": f"Back at {ref}, you leaned toward {frag} before we knew anything else about you. "
                        "It has repeated ever since — that first instinct was load-bearing.",
            })
    if chapter == "REFLECTION_CLOSING" and "prediction_test" not in used:
        tops = top_dims(session, 1, min_confidence=0.4)
        if tops:
            frag = dim_fragment(tops[0]["dim"], tops[0]["estimate"])
            return take("prediction_test", {
                "heading": "A small bet",
                "text": f"If the pattern is real, {frag} should show up again when work enters the picture next chapter. "
                        "If it doesn't, the pattern was wrong — and that would be worth knowing too.",
            })
    if chapter == "TRANSFORMATION_CLOSING" and "hidden_connection" not in used:
        tops = top_dims(session, 3, min_confidence=0.35)
        if len(tops) >= 2:
            a, b = dim_fragment(tops[0]["dim"], tops[0]["estimate"]), dim_fragment(tops[1]["dim"], tops[1]["estimate"])
            return take("hidden_connection", {
                "heading": "Two answers that were secretly one",
                "text": f"{a.capitalize()} and {b} looked like separate preferences. "
                        "Put together, they describe a single way of working — that combination is the finding.",
            })
    return None
