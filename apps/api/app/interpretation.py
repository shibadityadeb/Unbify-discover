"""Two-pass free-text interpretation.

PASS A extracts only what is clearly supported and names the ambiguities —
it never resolves them. PASS B decides whether resolving an ambiguity is
worth the user's effort; most are left open. Ambiguous language is NEVER
psychological signal (PART 62), and imperfect grammar never changes meaning
(PART 63). "I manage codes and softwares" yields works_with_software plus an
open ambiguity — not a management preference, not a role.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from . import knowledge
from . import thresholds as th
from .llm import gateway
from .models import AmbiguityRecord, DiscoverSession

# fact keys the extractor may ever set (LLM output outside this is discarded)
ALLOWED_FACT_KEYS = {
    "current_status", "freelance_experience", "builds_things", "commercial_evidence",
    "years_mentioned", "works_with_software", "people_management_evidence",
    "hands_on_technical", "coordinates_delivery", "technical_decision_authority",
    "client_exposure", "independent_projects", "studies_field",
}

SOFTWARE_WORDS = ("software", "code", "codes", "coding", "app", "apps", "application",
                  "website", "websites", "program", "programs", "system", "systems")
HANDS_ON_MARKERS = ("i write", "i code", "i build", "i built", "i develop", "i program",
                    "i ship", "i shipped", "writing code", "building")
PEOPLE_MGMT_MARKERS = ("my team", "direct reports", "i lead a team", "manage a team",
                       "manage people", "i manage people", "team of")


def _pass_a_heuristic(text: str) -> dict:
    """Conservative deterministic extraction. Explicit facts, derived facts,
    and ambiguities — separately."""
    t = re.sub(r"\s+", " ", text.lower())
    explicit: dict = {}
    derived: dict = {}
    ambiguities: list[dict] = []

    if any(w in t for w in ("student", "studying", "university", "college", "undergrad", "final year")):
        explicit["current_status"] = "student"
    if any(w in t for w in ("founder", "my startup", "my company", "co-founder", "i run a")):
        explicit["current_status"] = explicit.get("current_status") or "founder"
    if any(w in t for w in ("freelanc", "clients of my own", "my own clients")):
        explicit["freelance_experience"] = True
    if any(w in t for w in ("paid", "customers", "revenue", "sold", "earning")):
        explicit["commercial_evidence"] = True
    if any(w in t for w in ("built", "shipped", "launched", "created", "installed")):
        explicit["builds_things"] = True
    m = re.search(r"(\d+)\s*(?:\+\s*)?years?", t)
    if m:
        explicit["years_mentioned"] = min(50, int(m.group(1)))

    mentions_software = any(re.search(rf"\b{re.escape(w)}\b", t) for w in SOFTWARE_WORDS)
    if mentions_software:
        derived["works_with_software"] = True
    if any(w in t for w in HANDS_ON_MARKERS):
        derived["hands_on_technical"] = True
    if any(w in t for w in PEOPLE_MGMT_MARKERS):
        explicit["people_management_evidence"] = True

    # THE canonical ambiguity: "manage" + software, with no hands-on or
    # people-management disambiguator. It could mean development, coordination,
    # architecture, delivery, maintenance… we do not pick one.
    manages = re.search(r"\bmanag\w*\b", t)
    if manages and mentions_software and "hands_on_technical" not in derived \
            and "people_management_evidence" not in explicit:
        ambiguities.append({
            "key": "manage_software_scope",
            "description": "what 'manage' means here: building, coordinating people, "
                           "technical decisions, or delivery",
            "possibleInterpretations": ["software development", "technical coordination",
                                        "technical decision ownership", "delivery management"],
        })
    return {"explicit": explicit, "derived": derived, "ambiguities": ambiguities}


def _pass_a_llm(db: Session, text: str) -> dict:
    """LLM assists extraction under the PART 21 contract; anything outside the
    schema or the allowed key set is discarded."""
    out = gateway.generate(db, "free_text_interpretation_v1", {"text": text[:400]})
    if not out or not isinstance(out, dict):
        return {"explicit": {}, "derived": {}, "ambiguities": []}
    explicit = {k: v for k, v in (out.get("facts") or {}).items()
                if k in ALLOWED_FACT_KEYS and v not in (None, "", [])} \
        if isinstance(out.get("facts"), dict) else {}
    ambiguities = []
    for a in (out.get("ambiguities") or [])[:3]:
        if isinstance(a, dict) and a.get("key"):
            ambiguities.append({"key": str(a["key"])[:60],
                                "description": str(a.get("description", ""))[:200],
                                "possibleInterpretations": [str(i)[:60] for i in
                                                            (a.get("possibleInterpretations") or [])[:5]]})
    return {"explicit": explicit, "derived": {}, "ambiguities": ambiguities}


# ---------------- PASS B: is the clarification worth asking? ----------------

# decision impact: how much later analysis hinges on this ambiguity
DECISION_IMPACT = {"manage_software_scope": 0.9}
USER_EFFORT_EASY_CHOICE = 0.15


def clarification_value(session: DiscoverSession, key: str) -> float:
    impact = DECISION_IMPACT.get(key, 0.4)
    chapter = session.journey_status
    # professional-scope ambiguity matters most once reality enters the story
    chapter_factor = 1.0 if chapter in ("ALIGNMENT", "DISCOVER_WORKSPACE") else 0.7
    dims = session.dimensions or {}
    related_conf = max((dims.get(d, {}).get("confidence", 0.0)
                        for d in ("implementation_affinity", "leadership")), default=0.0)
    uncertainty = 1.0 - related_conf
    return round(impact * chapter_factor * uncertainty - USER_EFFORT_EASY_CHOICE, 3)


def interpret_free_text(db: Session, session: DiscoverSession, text: str,
                        source_interaction_id: str | None = None) -> dict:
    """Full two-pass pipeline. Returns the structured interpretation and
    records facts (with provenance), ambiguities, and narrative events."""
    heur = _pass_a_heuristic(text)
    llm = _pass_a_llm(db, text)
    explicit = {**llm["explicit"], **heur["explicit"]}          # heuristics win ties
    derived = dict(heur["derived"])
    amb_by_key = {a["key"]: a for a in llm["ambiguities"] + heur["ambiguities"]}

    pc = dict(session.practical_context or {})
    facts_meta = dict(pc.get("_facts", {}))
    changed: list[str] = []
    for key, value in explicit.items():
        if key in pc and pc.get(key) not in (None, ""):
            continue
        pc[key] = value
        facts_meta[key] = {"value": value, "source": "explicit_user_statement", "confidence": 1.0}
        changed.append(key)
        knowledge.record_evidence(db, session, "explicit_fact",
                                  f"user stated: {key} = {value}",
                                  strength=1.0, source_interaction_id=source_interaction_id)
    for key, value in derived.items():
        if key in pc:
            continue
        pc[key] = value
        facts_meta[key] = {"value": value, "source": "derived_fact", "confidence": 0.8}
        changed.append(key)
        knowledge.record_evidence(db, session, "free_text_extraction",
                                  f"conservatively derived: {key} = {value}",
                                  strength=0.6, source_interaction_id=source_interaction_id)
    # a stated occupation title is an explicit fact; the ontology decomposes
    # it into capabilities later — the title itself is never an inference
    if "current_occupation_title" not in pc:
        try:
            from .world.ontology import detect_occupation_in_text
            occ = detect_occupation_in_text(db, text)
        except Exception:
            occ = None
        if occ:
            pc["current_occupation_title"] = occ["alias"]
            facts_meta["current_occupation_title"] = {
                "value": occ["alias"], "source": "explicit_user_statement", "confidence": 1.0}
            changed.append("current_occupation_title")
            knowledge.record_evidence(db, session, "professional_history",
                                      f"user stated occupation: {occ['alias']}",
                                      strength=1.0, source_interaction_id=source_interaction_id)
    pc["_facts"] = facts_meta
    session.practical_context = pc

    recorded_ambiguities = []
    for key, amb in amb_by_key.items():
        existing = db.query(AmbiguityRecord).filter_by(session_id=session.id, key=key).first()
        if existing:
            continue
        value = clarification_value(session, key)
        row = AmbiguityRecord(session_id=session.id, key=key,
                              description=amb["description"],
                              possible_interpretations=amb.get("possibleInterpretations", []),
                              source_text=text[:300], clarification_value=value)
        db.add(row)
        recorded_ambiguities.append({"key": key, "clarificationValue": value})
    db.flush()

    if changed:
        knowledge.emit_event(db, session,
                             "PROFESSIONAL_CONTEXT_CHANGED_PICTURE" if
                             any(k in ("current_status", "builds_things", "commercial_evidence",
                                       "people_management_evidence") for k in changed)
                             else "NEW_FACT_CHANGED_MODEL",
                             {"facts": changed}, importance=0.7)
    return {"explicit": explicit, "derived": derived,
            "ambiguities": recorded_ambiguities, "changedFacts": changed}


# ---------------- clarification interactions (PART 9) ----------------

CLARIFICATION_DEFS: dict[str, dict] = {
    "manage_software_scope": {
        "headline": "When you say you manage software, which is closest?",
        "supportingText": "No wrong answer — it just sharpens what we ask next.",
        "options": [
            {"id": "build", "label": "I mostly build/code it",
             "facts": {"hands_on_technical": True, "builds_things": True}},
            {"id": "coordinate", "label": "I coordinate the people building it",
             "facts": {"people_management_evidence": True, "coordinates_delivery": True}},
            {"id": "architecture", "label": "I decide how the technical system should work",
             "facts": {"technical_decision_authority": True, "hands_on_technical": True}},
            {"id": "delivery", "label": "I manage delivery/projects around it",
             "facts": {"coordinates_delivery": True}},
            {"id": "mix", "label": "A mix", "facts": {"works_with_software": True}},
            {"id": "other", "label": "Something else", "facts": {}},
        ],
    },
}


def pending_clarification(db: Session, session: DiscoverSession) -> dict | None:
    """The single highest-value open ambiguity worth one easy question —
    respecting the per-chapter budget so clarification never becomes
    interrogation."""
    counters = session.counters or {}
    if counters.get("clarifications_this_chapter", 0) >= th.MAX_CLARIFICATIONS_PER_CHAPTER:
        return None
    rows = (db.query(AmbiguityRecord)
            .filter_by(session_id=session.id, status="open")
            .order_by(AmbiguityRecord.clarification_value.desc()).all())
    for row in rows:
        current_value = clarification_value(session, row.key)
        row.clarification_value = current_value
        if current_value < th.CLARIFICATION_VALUE_MIN:
            continue
        spec = CLARIFICATION_DEFS.get(row.key)
        if not spec:
            continue
        return {"ambiguityKey": row.key,
                "definition": {"id": f"clarify_{row.key}", "type": "clarification",
                               "chapters": [session.journey_status],
                               "content": {"headline": spec["headline"],
                                           "supportingText": spec.get("supportingText"),
                                           "options": [{"id": o["id"], "label": o["label"]}
                                                       for o in spec["options"]],
                                           "ambiguityKey": row.key}}}
    return None


def apply_clarification(db: Session, session: DiscoverSession, key: str, option_id: str) -> list[str]:
    spec = CLARIFICATION_DEFS.get(key)
    row = db.query(AmbiguityRecord).filter_by(session_id=session.id, key=key).first()
    if not spec or not row:
        return []
    option = next((o for o in spec["options"] if o["id"] == option_id), None)
    if not option:
        return []
    pc = dict(session.practical_context or {})
    facts_meta = dict(pc.get("_facts", {}))
    changed = []
    for fkey, fval in option["facts"].items():
        if fkey not in pc:
            pc[fkey] = fval
            facts_meta[fkey] = {"value": fval, "source": "explicit_user_statement", "confidence": 1.0}
            changed.append(fkey)
    pc["_facts"] = facts_meta
    session.practical_context = pc
    row.status = "clarified"
    row.resolution = option["label"]
    knowledge.record_evidence(db, session, "explicit_fact",
                              f"clarified '{key}': {option['label']}", strength=1.0)
    knowledge.emit_event(db, session, "NEW_FACT_CHANGED_MODEL",
                         {"clarified": key, "resolution": option["label"]}, importance=0.75)
    counters = dict(session.counters or {})
    counters["clarifications_this_chapter"] = counters.get("clarifications_this_chapter", 0) + 1
    session.counters = counters
    return changed
