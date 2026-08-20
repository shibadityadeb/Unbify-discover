"""Canonical ontology access: entity resolution and unknown-title handling.

Occupation != job title. Resolution goes lexical → alias → token overlap,
keeps ambiguity when candidates are close, and never force-fits a hybrid
human into one box (custom identity + multiple mappings are fine).
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..models import (DiscoverSession, WICapability, WIOccupation, WIOccupationAlias,
                      WIOccupationCapability)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())).strip()


# Occupational head nouns that carry no information on their own. Sharing only
# one of these with an alias must never be enough to claim a match.
GENERIC_TITLE_TOKENS = {
    "officer", "manager", "teacher", "engineer", "technician", "specialist",
    "assistant", "director", "lead", "leader", "head", "worker", "consultant",
    "analyst", "coordinator", "supervisor", "operator", "professional",
    "agent", "executive", "administrator", "associate", "staff", "senior",
    "junior", "chief", "principal", "officer's", "service", "services",
}


def resolve_title(db: Session, raw_title: str) -> dict:
    """→ {status: resolved|ambiguous|unknown, candidates: [{occupationId, label, confidence}]}
    Ambiguity is preserved: 'electrician' resolves, but 'electrical technician'
    vs 'industrial electrician' stay distinguishable."""
    t = _norm(raw_title)
    if not t:
        return {"status": "unknown", "candidates": []}
    exact = db.query(WIOccupationAlias).filter(WIOccupationAlias.alias == t).all()
    if exact:
        cands = [{"occupationId": a.occupation_id,
                  "label": db.get(WIOccupation, a.occupation_id).preferred_label,
                  "confidence": 0.95} for a in exact]
        return {"status": "resolved" if len(cands) == 1 else "ambiguous", "candidates": cands}
    # token-overlap over aliases
    tokens = set(t.split())
    scored: dict[str, float] = {}
    for alias in db.query(WIOccupationAlias).all():
        a_tokens = set(alias.alias.split())
        if not a_tokens:
            continue
        shared = tokens & a_tokens
        # A single generic head noun is not evidence of anything: "chief vibe
        # officer" shares only "officer" with "supply officer", and "yoga
        # teacher" shares only "teacher" with "school teacher". Both used to
        # resolve outright, which then attached real market numbers to the
        # wrong occupation — a confident answer about someone's own industry
        # that happens to be wrong.
        if shared and shared <= GENERIC_TITLE_TOKENS:
            continue
        overlap = len(shared) / len(tokens | a_tokens)
        if overlap > 0:
            scored[alias.occupation_id] = max(scored.get(alias.occupation_id, 0), overlap)
    ranked = sorted(scored.items(), key=lambda kv: -kv[1])[:4]
    cands = [{"occupationId": oid,
              "label": db.get(WIOccupation, oid).preferred_label,
              "confidence": round(0.4 + 0.5 * s, 2)} for oid, s in ranked if s >= 0.25]
    if not cands:
        return {"status": "unknown", "candidates": []}
    if len(cands) == 1 or (len(cands) > 1 and cands[0]["confidence"] - cands[1]["confidence"] > 0.25):
        return {"status": "resolved", "candidates": cands[:1]}
    return {"status": "ambiguous", "candidates": cands}


def detect_occupation_in_text(db: Session, text: str) -> dict | None:
    """Find a stated occupation inside free text via the alias table —
    longest alias wins ('industrial electrician' beats 'electrician')."""
    t = f" {_norm(text)} "
    best = None
    for alias in db.query(WIOccupationAlias).all():
        needle = f" {alias.alias} "
        if needle in t:
            if best is None or len(alias.alias) > len(best["alias"]):
                best = {"alias": alias.alias, "occupationId": alias.occupation_id,
                        "label": db.get(WIOccupation, alias.occupation_id).preferred_label}
    return best


def occupation_capabilities(db: Session, occupation_id: str) -> dict[str, float]:
    rows = db.query(WIOccupationCapability).filter_by(occupation_id=occupation_id).all()
    return {r.capability_id: r.weight for r in rows}


# ---------------- HUMAN side bridge: experience → capabilities ----------------
# The human profile stays independent of world data (market popularity never
# alters the human). This bridge only projects the person's OWN evidence into
# capability space so the two systems can meet at matching time.

FACT_TO_CAPABILITIES = {
    "hands_on_technical": [("systems_troubleshooting", 0.6)],
    "builds_things": [("physical_execution", 0.3)],
    "works_with_software": [("software_construction", 0.5), ("systems_troubleshooting", 0.4)],
    "people_management_evidence": [("people_leadership", 0.8), ("crew_supervision", 0.5)],
    "coordinates_delivery": [("scheduling_dispatch", 0.6), ("project_management", 0.6),
                             ("logistics_planning", 0.4)],
    "technical_decision_authority": [("design_engineering", 0.5), ("systems_troubleshooting", 0.4)],
    "commercial_evidence": [("customer_acquisition", 0.6), ("customer_interaction", 0.5),
                            ("sales_selling", 0.4)],
    "freelance_experience": [("customer_acquisition", 0.5), ("business_administration", 0.5)],
    "management_exposure": [("people_leadership", 0.6)],
}

DIM_TO_CAPABILITIES = {
    "teaching": [("teaching_instruction", 0.7), ("training_delivery", 0.5)],
    "leadership": [("people_leadership", 0.7)],
    "planning": [("project_management", 0.6), ("logistics_planning", 0.4)],
    "sales_comfort": [("sales_selling", 0.7), ("customer_acquisition", 0.5)],
    "detail_orientation": [("quality_inspection", 0.4)],
    "storytelling": [("writing_composition", 0.5)],
    "aesthetic_sensitivity": [("visual_design", 0.6)],
    "facilitation": [("training_delivery", 0.3)],
}

SOFTWARE_BUILD_CAPS = [("software_construction", 0.8)]
PHYSICAL_BUILD_CAPS = [("physical_execution", 0.6), ("installation_work", 0.4)]


def user_capability_vector(db: Session, session: DiscoverSession) -> dict[str, float]:
    """Project the user's OWN evidence (facts, resolved experience, supported
    dimensions) into capability space. Title decomposes into capabilities via
    the ontology — experience is modeled, not the label."""
    vec: dict[str, float] = {}
    pc = session.practical_context or {}

    def bump(cap: str, w: float) -> None:
        vec[cap] = min(1.0, vec.get(cap, 0.0) + w)

    for fact, caps in FACT_TO_CAPABILITIES.items():
        if pc.get(fact):
            for cap, w in caps:
                bump(cap, w)
    if pc.get("builds_things"):
        caps = SOFTWARE_BUILD_CAPS if pc.get("works_with_software") else PHYSICAL_BUILD_CAPS
        for cap, w in caps:
            bump(cap, w)
    # resolved current occupation → inherit its capability profile at
    # experience weight (a title CONTAINS capabilities; it isn't one).
    # The user's explicitly stated title always outranks derived domain labels,
    # and an ambiguous resolution still inherits — at reduced weight.
    prof = (pc.get("professional") or {})
    for title in (pc.get("current_occupation_title"), prof.get("function"), prof.get("domain")):
        if not title:
            continue
        res = resolve_title(db, str(title))
        if res["status"] == "resolved":
            for cap, w in occupation_capabilities(db, res["candidates"][0]["occupationId"]).items():
                bump(cap, w * 0.7)
            break
        if res["status"] == "ambiguous" and res["candidates"]:
            for cap, w in occupation_capabilities(db, res["candidates"][0]["occupationId"]).items():
                bump(cap, w * 0.45)
            break
    for dim, caps in DIM_TO_CAPABILITIES.items():
        state = (session.dimensions or {}).get(dim, {})
        if state.get("confidence", 0) >= 0.5 and state.get("estimate", 0) > 0.2:
            for cap, w in caps:
                bump(cap, w * state["confidence"])
    return vec


def resolve_user_occupation(db: Session, session: DiscoverSession) -> dict:
    pc = session.practical_context or {}
    prof = (pc.get("professional") or {})
    for candidate in (pc.get("current_occupation_title"), prof.get("function"), prof.get("domain")):
        if candidate:
            res = resolve_title(db, str(candidate))
            if res["status"] != "unknown":
                return res
    return {"status": "unknown", "candidates": []}
