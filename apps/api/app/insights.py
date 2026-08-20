"""The ten things worth knowing about someone's field.

The ask was concrete: whether to stay in a job or build something, and if a
job — the pay, the requirements, the market, the country; and if there is room
to build — where the income actually comes from in an AI era.

Some of that we hold real data for, per occupation, and it is genuinely useful:
how much of a field works for itself, how exposed the work is to automation
versus how much it is amplified by tools, whether it is licensed, and which
pathways the occupation actually supports. Those numbers come from the
ontology, not from a model's opinion.

Some of it we do not hold at all. There are zero salary signals in the
database, and no country resolution. Those insights are still returned — as
explicitly unavailable, naming what would fill them — because a person deciding
whether to leave a job needs to know which half of the picture is missing far
more than they need a confident guess.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import thresholds as th
from .models import DiscoverSession, WIOccupation

MAX_INSIGHTS = 10

# a reading is only worth stating as fact with more than one source behind it
MIN_SOURCES = 2
MIN_CONFIDENCE = 0.40


def _supported(headline: str, detail: str, basis: str, confidence: str = "grounded") -> dict:
    return {"headline": headline, "detail": detail, "basis": basis,
            "status": "supported", "confidence": confidence}


def _unavailable(headline: str, why: str, unlocks: str) -> dict:
    """An insight we cannot give, said plainly. Never a hedge dressed as an
    answer — the reader must be able to tell the difference at a glance."""
    return {"headline": headline, "detail": why, "basis": unlocks,
            "status": "unavailable", "confidence": "none"}


def resolve_field(db: Session, session: DiscoverSession) -> WIOccupation | None:
    """The occupation, from whichever answer actually carried it.

    Only current_occupation_title was consulted, but real sessions store the
    same information under profession_text (the free-text answer) or inside the
    extracted `professional` block — so a person who had told us their field
    plainly still got "we don't know your field".
    """
    from .world.ontology import detect_occupation_in_text, resolve_title
    pc = session.practical_context or {}
    prof = pc.get("professional") or {}
    candidates = [pc.get("current_occupation_title"), prof.get("function"),
                  prof.get("domain"), pc.get("profession_text")]
    for raw in [c for c in candidates if c and str(c).lower() != "none"]:
        res = resolve_title(db, str(raw))
        if res.get("status") == "resolved" and res.get("candidates"):
            return db.get(WIOccupation, res["candidates"][0]["occupationId"])
    # free text may still name an occupation inside a longer sentence
    for raw in [pc.get("profession_text"), prof.get("function")]:
        if not raw:
            continue
        hit = detect_occupation_in_text(db, str(raw))
        if hit and hit.get("occupationId"):
            return db.get(WIOccupation, hit["occupationId"])
    return None


def _demand(db: Session, occ: WIOccupation) -> dict:
    from .world import signals as world_signals
    sig = world_signals.signal_for(db, occ.id, "demand_direction")
    if not sig:
        return _unavailable(
            "Which way demand is moving",
            f"We hold no demand observations for {occ.preferred_label}.",
            "A live postings source would fill this within a day of being enabled.")
    if sig.source_count < MIN_SOURCES or sig.confidence < MIN_CONFIDENCE:
        return _unavailable(
            "Which way demand is moving",
            f"Our only reading for {occ.preferred_label} comes from {sig.source_count} "
            f"seeded source, which is not enough to state as fact.",
            "Two independent sources would make this a real number.")
    direction = ("growing" if sig.value >= 0.65 else
                 "steady" if sig.value >= 0.45 else "softening")
    return _supported(
        "Which way demand is moving",
        f"Demand for {occ.preferred_label} looks {direction}.",
        f"{sig.source_count} sources, refreshed {world_signals.freshness_days(sig)}d ago")


def _business_scope(occ: WIOccupation) -> dict:
    pct = int(round(occ.self_employment_prevalence * 100))
    if pct >= 45:
        verdict = (f"About {pct}% of people in this field already work for themselves. "
                   "Going independent here is the normal path, not the brave one.")
    elif pct >= 25:
        verdict = (f"About {pct}% of this field works independently — a real minority, "
                   "so it is proven but not the default.")
    else:
        verdict = (f"Only about {pct}% of this field works for itself. Building your own "
                   "thing here means going against how the work is usually organised.")
    return _supported("Whether there's room to build your own", verdict,
                      "occupation ontology · self-employment prevalence")


def _ai_position(occ: WIOccupation) -> dict:
    exposure, augment = occ.ai_automation_exposure, occ.ai_augmentation_potential
    if exposure >= 0.6:
        detail = ("A lot of this work is the kind machines are getting good at. The income "
                  "worth building is in the parts that stay human, or in running the tools.")
    elif augment - exposure >= 0.2:
        detail = ("Machines are bad at the core of this work but good at the admin around it. "
                  "That gap is where the money is: same craft, far more of it per week.")
    else:
        detail = ("Tools change this work slowly. Income comes from being good at it and "
                  "from reaching more customers, not from automating it.")
    return _supported("Where the income comes from in an AI era", detail,
                      f"ontology · automation exposure {exposure:.2f}, augmentation {augment:.2f}")


def _licensing(occ: WIOccupation) -> dict:
    if occ.regulated:
        return _supported(
            "Whether you need a licence",
            f"{occ.preferred_label} is regulated. Whatever you decide, eligibility comes "
            "first — it decides whether a direction is real at all.",
            "occupation ontology · regulated status")
    return _supported("Whether you need a licence",
                      f"{occ.preferred_label} is not licensed, so nothing formal blocks you "
                      "starting. Proof of work does the job instead.",
                      "occupation ontology · regulated status")


def _pathways(occ: WIOccupation) -> dict:
    from .world.matching import PATHWAY_LABEL
    paths = [PATHWAY_LABEL.get(p, p) for p in (occ.pathway_potentials or [])]
    if not paths:
        return _unavailable("The shapes this work can take",
                            "We have no pathway mapping for this occupation yet.",
                            "It is added when the occupation is next reviewed.")
    return _supported("The shapes this work can take",
                      "Documented routes from here: " + ", ".join(paths[:5]) + ".",
                      f"occupation ontology · {len(paths)} mapped pathways")


def _salary() -> dict:
    return _unavailable(
        "What it pays",
        "We hold no salary data at all — not a weak reading, none. Anything we printed "
        "here would be invented, and you would know it before we did.",
        "Salary arrives with a live postings source; it is the single biggest gap.")


def _market_country(session: DiscoverSession) -> dict:
    where = (session.practical_context or {}).get("geographic_context")
    if where:
        return _supported("Which market this applies to", f"Read for {where}.",
                          "you told us directly")
    return _unavailable(
        "Which market this applies to",
        "Pay and demand differ enormously by country, and we don't know yours.",
        "One answer fixes it, and every number above gets sharper.")


def _own_evidence(db: Session, session: DiscoverSession) -> list[dict]:
    """What the person's own answers already settle — the cheapest real data
    there is, because they gave it to us."""
    out = []
    dims = session.dimensions or {}
    pc = session.practical_context or {}
    risk = dims.get("risk_tolerance", {})
    if risk.get("confidence", 0) >= th.MAY_TEST:
        bold = risk.get("estimate", 0) > 0
        out.append(_supported(
            "How much downside you'd actually accept",
            "You lean toward bets with real downside." if bold else
            "You lean toward moves where you can't lose much.",
            f"your answers · {risk.get('evidence_count', 0)} of them", "from your answers"))
    if pc.get("commercial_evidence"):
        out.append(_supported(
            "Whether people already pay you",
            "They do. That is the hardest thing on this page to fake, and you have it.",
            "you told us directly", "from your answers"))
    time_state = dims.get("time_availability", {})
    if time_state.get("confidence", 0) >= th.MAY_TEST:
        out.append(_supported(
            "The time you actually have",
            "Real hours each week." if time_state.get("estimate", 0) > 0
            else "Scraps between everything else — which rules out anything needing a runway.",
            "your answers", "from your answers"))
    return out


def top_insights(db: Session, session: DiscoverSession, intent: str | None = None) -> dict:
    """Up to ten, ordered by what changes a decision most.

    `intent` is the branch the person picked — "job" or "business". It reorders
    what comes first; it never changes what is true.
    """
    occ = resolve_field(db, session)
    if not occ:
        stated = (session.practical_context or {}).get("profession_text")
        return {"status": "no_field",
                "note": (
                    f"We couldn't match \u201c{stated}\u201d to an occupation we hold data "
                    "for, so every number here would be guesswork. Our map is still "
                    "small and skewed toward trades and clinical work."
                    if stated else
                    "We haven't pinned down which field you're in, and every number "
                    "below depends on it. One answer unlocks the rest."),
                "intent": intent, "insights": []}

    field_first = [_demand(db, occ), _salary(), _market_country(session), _licensing(occ)]
    build_first = [_business_scope(occ), _ai_position(occ), _pathways(occ),
                   _market_country(session)]

    if intent == "business":
        ordered = build_first + field_first
    elif intent == "job":
        ordered = field_first + [_business_scope(occ), _ai_position(occ), _pathways(occ)]
    else:
        ordered = [_business_scope(occ), _ai_position(occ), _demand(db, occ),
                   _licensing(occ), _salary(), _market_country(session), _pathways(occ)]

    seen, insights = set(), []
    for item in ordered + _own_evidence(db, session):
        if item["headline"] in seen:
            continue
        seen.add(item["headline"])
        insights.append(item)
        if len(insights) >= MAX_INSIGHTS:
            break

    supported = sum(1 for i in insights if i["status"] == "supported")
    return {"status": "ok", "field": occ.preferred_label, "intent": intent,
            "supported": supported, "unavailable": len(insights) - supported,
            "insights": insights}


# ---------------- the branch itself ----------------

DIRECTION_QUESTION = {
    "id": "direction",
    "question": "Before the numbers — what are you actually weighing up?",
    "options": [
        {"id": "job", "label": "Staying employed, but better paid"},
        {"id": "business", "label": "Building something of my own"},
        {"id": "unsure", "label": "Genuinely don't know yet"},
    ],
}


def save_direction(db: Session, session: DiscoverSession, option_id: str) -> bool:
    if option_id not in {o["id"] for o in DIRECTION_QUESTION["options"]}:
        return False
    pc = dict(session.practical_context or {})
    pc["_direction_intent"] = option_id
    session.practical_context = pc
    db.flush()
    return True


def current_intent(session: DiscoverSession) -> str | None:
    intent = (session.practical_context or {}).get("_direction_intent")
    return intent if intent in ("job", "business") else None
