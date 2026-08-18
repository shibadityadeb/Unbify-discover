"""Narrative layer with memory. Sentences appear because something actually
changed in state — never on rotation, never twice. The policy provides the
reason; this module provides unrepeated human language for it."""
from __future__ import annotations

from .dimensions import dim_phrase
from .models import DiscoverSession
from .signals import top_dims, thinnest_dims

# pools keyed by REAL state-change events; each phrase is used at most once per
# session, and near-duplicates are rejected by token similarity
BRIDGE_POOLS: dict[str, list[str]] = {
    "contradiction_new": [
        "Those last two answers don't completely agree. That's useful.",
        "Something just pulled in two directions at once.",
        "A tension is appearing here — worth a closer look.",
    ],
    "uncertainty_resolved": [
        "Okay. That part is much clearer now.",
        "That clears up one piece.",
        "That part seems settled — moving on.",
    ],
    "eligibility_changed": [
        "That changes the picture a little.",
        "Good — that reshapes what's worth asking.",
        "That answer just made a few questions unnecessary.",
    ],
    "correction_received": [
        "Got it. Then something else may be creating that pattern.",
        "Noted — we'll read the earlier answers differently.",
    ],
    "probe_new_ground": [
        "There's one part of your pattern we haven't quite understood yet.",
        "One piece is still fuzzy.",
        "This might seem unrelated for a second.",
        "There's one thing I'd rather not guess.",
        "This one matters more than it looks.",
    ],
}


def _memory(session: DiscoverSession) -> dict:
    pc = session.practical_context or {}
    return dict(pc.get("_narrative", {"used": [], "event": None}))


def _save_memory(session: DiscoverSession, mem: dict) -> None:
    pc = dict(session.practical_context or {})
    pc["_narrative"] = mem
    session.practical_context = pc


def _too_similar(a: str, b: str) -> bool:
    """Token-Jaccard near-duplicate check — cheap semantic repetition guard."""
    ta = {w for w in a.lower().split() if len(w) > 2}
    tb = {w for w in b.lower().split() if len(w) > 2}
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) > 0.55


def record_event(session: DiscoverSession, event: str) -> None:
    mem = _memory(session)
    mem["event"] = event
    _save_memory(session, mem)


def take_bridge(session: DiscoverSession, definition_bridge: str | None = None) -> str | None:
    """Return an unrepeated bridge for the pending event (or the definition's own
    bridge), consuming both. No event and no definition bridge -> silence."""
    mem = _memory(session)
    used: list[str] = mem.get("used", [])

    def fresh(phrase: str) -> bool:
        return phrase not in used and not any(_too_similar(phrase, u) for u in used[-8:])

    chosen = None
    if definition_bridge and fresh(definition_bridge):
        chosen = definition_bridge
    else:
        event = mem.get("event")
        if event:
            for phrase in BRIDGE_POOLS.get(event, []):
                if fresh(phrase):
                    chosen = phrase
                    break
    mem["event"] = None
    if chosen:
        mem["used"] = (used + [chosen])[-24:]
    _save_memory(session, mem)
    return chosen


REVEAL_OPENERS = [
    "Okay — here's what keeps showing up.",
    "There's a pattern here.",
    "Something is becoming clearer.",
    "Two things keep appearing together.",
    "Here's what your choices keep saying.",
]


def take_reveal_opener(session: DiscoverSession) -> str:
    mem = _memory(session)
    used = mem.get("used", [])
    for phrase in REVEAL_OPENERS:
        if phrase not in used:
            mem["used"] = (used + [phrase])[-24:]
            _save_memory(session, mem)
            return phrase
    return "Here's where things stand."


# ---------------- dynamic chapter closings (scrollable, user-paced) ----------------

CLOSING_CTA = {
    "REFLECTION": "Continue to Reflection →",
    "ALIGNMENT": "Let's make this real →",
    "TRANSFORMATION": "Bring it together →",
    "STORY_COMPLETE": "Your discovery is complete →",
}

CHAPTER_FOCUS_FAMILIES = {
    "SELF_DISCOVERY_CLOSING": ["energy", "creative", "social", "cognitive"],
    "REFLECTION_CLOSING": ["cognitive", "execution", "social", "energy"],
    "ALIGNMENT_CLOSING": ["economic", "leverage", "ai_era", "execution"],
}


def compose_closing(session: DiscoverSession, closing_state: str, next_state: str) -> dict:
    """Closing content derives from what actually happened: supported insights,
    corrections, contradictions, remaining uncertainty. No fake certainty —
    if evidence is thin, say so honestly."""
    if closing_state == "TRANSFORMATION_CLOSING":
        return {
            "type": "chapter_closing",
            "sections": [
                {"label": None, "text": "This isn't a verdict."},
                {"label": None, "text": "It's the clearest picture we can build from what you've shown us so far."},
                {"label": None, "text": "And it can keep changing with you."},
            ],
            "cta": CLOSING_CTA["STORY_COMPLETE"], "next": "STORY_COMPLETE",
        }

    tops = top_dims(session, 2, min_confidence=0.35)
    confirmed = [i for i in (session.revealed_insights or []) if i.get("answer") in ("yes", "first")]
    corrected = [i for i in (session.revealed_insights or []) if i.get("answer") == "no"]
    contradiction = next((c for c in (session.contradictions or []) if not c.get("explored")), None)
    families = CHAPTER_FOCUS_FAMILIES.get(closing_state, [])
    thin = thinnest_dims(session, families, 1) if families else []

    sections = []
    # closing observation — honest about how much actually formed
    if tops and confirmed:
        sections.append({"label": None,
                         "text": f"The clearest thing so far: you keep choosing {dim_phrase(tops[0]['dim'], tops[0]['estimate'])} — and you confirmed it yourself."})
    elif tops:
        sections.append({"label": None,
                         "text": f"A pattern is forming around {dim_phrase(tops[0]['dim'], tops[0]['estimate'])}. Not settled — but it kept returning."})
    else:
        sections.append({"label": None,
                         "text": "A few things are beginning to form. Nothing I'd call settled yet — and that's fine."})
    # one important thing learned
    if corrected:
        sections.append({"label": "One thing that mattered",
                         "text": "You pushed back on one of our readings. That correction now outweighs everything we merely inferred."})
    elif len(tops) > 1:
        sections.append({"label": "One thing that mattered",
                         "text": f"You never traded away {dim_phrase(tops[1]['dim'], tops[1]['estimate'])} — even when the choices made it tempting."})
    elif contradiction:
        sections.append({"label": "One thing that mattered",
                         "text": f"You want {dim_phrase(contradiction['dim'], 1)} and {dim_phrase(contradiction['dim'], -1)} at once. We're not treating that as noise."})
    # what remains uncertain
    if thin:
        sections.append({"label": "Still open",
                         "text": f"We know little about how you relate to {dim_phrase(thin[0], 1)}. The next chapter can test it."})
    # bridge to next chapter
    bridge_text = {
        "REFLECTION": "So far you've been choosing instinctively. Next, we look at the pattern those choices created.",
        "ALIGNMENT": "The pattern doesn't exist in isolation. You have work, experience, constraints. Let's put the person we've been discovering back into the real world.",
        "TRANSFORMATION": "We know what seems natural to you, what you already have, and where the friction sits. One thing left: bring it together.",
    }.get(next_state)
    if bridge_text:
        sections.append({"label": None, "text": bridge_text})

    return {"type": "chapter_closing", "sections": sections,
            "cta": CLOSING_CTA.get(next_state, "Continue →"), "next": next_state}
