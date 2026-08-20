"""UNBIFY product routing.

A product may only appear as infrastructure for something the user is already
trying to do. Every route must be able to show, internally:

    USER NEED -> EVIDENCE -> CAPABILITY GAP / ACTION NEED -> PRODUCT CAPABILITY

If that chain cannot be built, the product is not displayed. Product
conversion is never a ranking reward — routing is strictly downstream of the
user's own direction, and the experience never gates basic value behind it.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import DiscoverSession, EvidenceItem, ProductRouteRecord

CAPABILITIES = ("career", "marketplace", "agency", "suite", "brain")

# minimum relevance before a route is ever surfaced; a weak chain shows nothing
MIN_RELEVANCE = 0.45


def _evidence_ids(db: Session, session: DiscoverSession, kinds: tuple[str, ...] = (),
                  limit: int = 4) -> list[str]:
    q = db.query(EvidenceItem).filter_by(session_id=session.id)
    if kinds:
        q = q.filter(EvidenceItem.kind.in_(kinds))
    return [e.id for e in q.order_by(EvidenceItem.created_at.desc()).limit(limit).all()]


def _routes_for(db: Session, session: DiscoverSession, material: dict) -> list[dict]:
    pc = session.practical_context or {}
    directions = material.get("directions", [])
    gaps = material.get("gaps", [])
    leverage = material.get("leverage", [])
    routes: list[dict] = []
    gap_labels = {g["key"] for g in gaps}
    top = directions[0] if directions else None

    def add(capability: str, need: str, gap: str, reasons: list[str],
            prerequisites: list[str], relevance: float, evidence_kinds=()):
        ev = _evidence_ids(db, session, evidence_kinds)
        if not ev or not need or not gap:
            return          # incomplete chain -> no product, no exceptions
        routes.append({"capability": capability, "userNeed": need, "gap": gap,
                       "reasonCodes": reasons, "prerequisiteStates": prerequisites,
                       "relevanceScore": round(relevance, 3), "evidenceIds": ev})

    # CAREER — the gap is proof/capability, not ideas
    missing_caps = [g for g in gaps if g["kind"] == "capability"]
    if top and missing_caps:
        add("career",
            need=f"you have a direction ({top['label']}) but not yet the proof you can operate in it",
            gap=f"demonstrable capability in {missing_caps[0]['label']}",
            reasons=["direction_identified", "capability_gap", "needs_proof"],
            prerequisites=["MATERIALIZATION"],
            relevance=0.55 + 0.15 * min(2, len(missing_caps)),
            evidence_kinds=("behavioral_choice", "explicit_fact"))

    # AGENCY — commercial execution and distribution for an independent direction
    independent = [d for d in directions if d.get("pathway") in
                   ("business_ownership", "contracting", "consulting", "freelancing",
                    "practice_ownership", "problem_business")]
    commercial_gap = any(g["key"] in ("customer_acquisition", "sales_selling",
                                      "commercial_evidence") for g in gaps)
    if independent and commercial_gap:
        add("agency",
            need=f"the direction that fits you ({independent[0]['label']}) depends on finding "
                 "and winning customers",
            gap="finding and winning customers",
            reasons=["independent_direction", "commercial_gap", "distribution_needed"],
            prerequisites=["MATERIALIZATION"],
            relevance=0.6 if not pc.get("commercial_evidence") else 0.5,
            evidence_kinds=("explicit_fact", "free_text_extraction"))

    # SUITE — only for people who already operate something
    operating = pc.get("commercial_evidence") or pc.get("people_management_evidence") or \
        pc.get("coordinates_delivery") or (pc.get("current_status") == "founder")
    if operating:
        add("suite",
            need="you're already doing the work, not just planning it",
            gap="the day-to-day running of it as the volume goes up",
            reasons=["already_operating", "execution_load"],
            prerequisites=["MATERIALIZATION"],
            relevance=0.55,
            evidence_kinds=("explicit_fact", "professional_history"))

    # MARKETPLACE — a capability you need but do not want to build yourself
    unwanted = [g for g in gaps if g["kind"] == "capability" and g.get("preferBuy")]
    sellable = [l for l in leverage if l.get("strength", 0) >= 0.6]
    if unwanted:
        add("marketplace",
            need=f"{unwanted[0]['label']} stands between you and a direction you want",
            gap="a skill you'd rather pay for than spend years learning",
            reasons=["capability_gap", "prefer_buy"],
            prerequisites=["MATERIALIZATION"],
            relevance=0.5, evidence_kinds=("behavioral_choice",))
    elif sellable and independent:
        add("marketplace",
            need=f"you already have something sellable — {sellable[0]['label']}",
            gap="somewhere to sell it that isn't cold emails",
            reasons=["sellable_capability", "independent_direction"],
            prerequisites=["MATERIALIZATION"],
            relevance=0.5, evidence_kinds=("explicit_fact", "behavioral_choice"))

    # BRAIN — genuine decision uncertainty, not curiosity
    open_questions = material.get("openQuestionCount", 0)
    comparing = len(directions) >= 3
    if open_questions >= 2 and comparing:
        add("brain",
            need="several options are still open and you don't have what you need to choose yet",
            gap="help deciding, that keeps up as things change",
            reasons=["multiple_live_directions", "unresolved_uncertainty"],
            prerequisites=["MATERIALIZATION"],
            relevance=0.45 + 0.05 * min(3, open_questions),
            evidence_kinds=("calibration", "correction", "behavioral_choice"))

    return [r for r in routes if r["relevanceScore"] >= MIN_RELEVANCE]


PRESENTATION = {
    "career": ("Learn it, and be able to prove it",
               "UNBIFY Career is built for exactly this gap: you learn the skill and end up with "
               "something you can show people."),
    "agency": ("Get it in front of customers",
               "UNBIFY Agency handles the finding-customers side, which is what this stands or falls on."),
    "suite": ("Run it without it running you",
              "UNBIFY Suite runs the day-to-day of work you're already doing."),
    "marketplace": ("Buy the piece you're missing",
                    "UNBIFY Marketplace is where you can buy that in, or sell it."),
    "brain": ("Keep this up to date",
              "UNBIFY Brain keeps this up to date as your situation and the market change."),
}


def route(db: Session, session: DiscoverSession, material: dict) -> list[dict]:
    """Compute, persist and return displayable product routes (may be empty —
    that is a valid and common outcome)."""
    routes = sorted(_routes_for(db, session, material),
                    key=lambda r: -r["relevanceScore"])[:2]
    out = []
    for r in routes:
        row = (db.query(ProductRouteRecord)
               .filter_by(session_id=session.id, capability=r["capability"]).first())
        if not row:
            row = ProductRouteRecord(session_id=session.id, capability=r["capability"])
            db.add(row)
        row.reason_codes = r["reasonCodes"]
        row.prerequisite_states = r["prerequisiteStates"]
        row.relevance_score = r["relevanceScore"]
        row.explanation_evidence_ids = r["evidenceIds"]
        row.user_need = r["userNeed"]
        row.gap = r["gap"]
        from datetime import datetime
        row.shown_at = datetime.utcnow()
        db.flush()
        headline, help_text = PRESENTATION[r["capability"]]
        out.append({
            "id": row.id, "capability": r["capability"], "headline": headline,
            # contextual: the need first, the product only as the answer to it
            "because": r["userNeed"].capitalize() + ".",
            "gap": f"What's missing is {r['gap']}.",
            "help": help_text,
            "reasonCodes": r["reasonCodes"],
            "optional": "You can keep looking around, saving and testing without it.",
        })
    return out


def accept(db: Session, session: DiscoverSession, route_id: str) -> bool:
    row = db.get(ProductRouteRecord, route_id)
    if not row or row.session_id != session.id:
        return False
    row.accepted = True
    db.flush()
    return True
