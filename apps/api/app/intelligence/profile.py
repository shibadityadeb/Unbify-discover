"""CapabilityExtractor: questionnaire evidence → structured capability profile.

The LLM decomposes what the person DOES into capabilities (a doctor is
diagnosis + patient communication + clinical decision making, never just
"healthcare"). When the model is unavailable the deterministic fallback builds
a thinner profile from extracted facts, the capability vector, and the
occupation taxonomy used strictly as reference data. The profile is cached
against a hash of its questionnaire inputs — it recomputes when answers change,
not on every page open."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

from ..llm import gateway
from ..models import DiscoverSession, DiscoveryCache, Response

PROFILE_KEYS = [
    "identity_context", "current_occupation", "industry", "technical_skills",
    "domain_knowledge", "soft_skills", "business_skills", "tools", "credentials",
    "education", "experience", "tasks_performed", "interests", "constraints",
    "location", "career_goals", "entrepreneurial_intent", "ai_experience",
    "capabilities", "adjacent_capabilities", "latent_capabilities",
    "ai_augments", "ai_automates", "human_essential",
]

_LIST_KEYS = {k for k in PROFILE_KEYS if k not in
              ("current_occupation", "location", "entrepreneurial_intent")}


def _free_text_answers(db: Session, session: DiscoverSession, limit: int = 12) -> list[str]:
    rows = (db.query(Response)
            .filter_by(session_id=session.id)
            .order_by(Response.created_at.asc()).all())
    texts = []
    for r in rows:
        t = (r.payload or {}).get("text")
        if t and len(str(t).strip()) > 2:
            texts.append(str(t).strip()[:200])
    return texts[-limit:]


def _extraction_input(db: Session, session: DiscoverSession) -> dict:
    pc = session.practical_context or {}
    dims = session.dimensions or {}
    strong_dims = sorted(
        ((d, round(v.get("estimate", 0), 2)) for d, v in dims.items()
         if v.get("confidence", 0) >= 0.5 and abs(v.get("estimate", 0)) >= 0.25),
        key=lambda kv: -abs(kv[1]))[:12]
    return {
        "professional": pc.get("professional") or {},
        "currentOccupationTitle": pc.get("current_occupation_title") or "",
        "currentStatus": pc.get("current_status") or "",
        "facts": {k: v for k, v in pc.items()
                  if k in ("freelance_experience", "builds_things", "commercial_evidence",
                           "years_mentioned", "works_with_software", "people_management_evidence",
                           "hands_on_technical", "coordinates_delivery", "client_exposure",
                           "independent_projects", "studies_field", "technical_decision_authority")},
        "assets": pc.get("assets") or pc.get("al_assets") or [],
        "situation": pc.get("situation") or {},
        "geography": pc.get("geography") or pc.get("location") or "",
        "hours": pc.get("hours_available") or "",
        "freeTextAnswers": _free_text_answers(db, session),
        "strongDimensions": [{"dimension": d, "estimate": e} for d, e in strong_dims],
    }


def profile_hash(extraction_input: dict) -> str:
    return hashlib.sha256(
        json.dumps(extraction_input, sort_keys=True, default=str).encode()).hexdigest()[:32]


def _empty_profile() -> dict:
    p = {k: ([] if k in _LIST_KEYS else "") for k in PROFILE_KEYS}
    p["entrepreneurial_intent"] = "none"
    return p


def _normalize(profile: dict) -> dict:
    out = _empty_profile()
    for k in PROFILE_KEYS:
        v = profile.get(k)
        if k in _LIST_KEYS:
            if isinstance(v, list):
                out[k] = v[:24]
        elif isinstance(v, str):
            out[k] = v.strip()[:120]
    if out["entrepreneurial_intent"] not in ("none", "curious", "active", "operating"):
        out["entrepreneurial_intent"] = "none"
    # capabilities entries must be well-formed
    caps = []
    for c in out["capabilities"]:
        if isinstance(c, dict) and c.get("name"):
            caps.append({"name": str(c["name"]).lower()[:60],
                         "type": c.get("type") if c.get("type") in
                                 ("technical", "domain", "soft", "business", "tool") else "domain",
                         "confidence": max(0.0, min(1.0, float(c.get("confidence") or 0.5)))})
        elif isinstance(c, str):
            caps.append({"name": c.lower()[:60], "type": "domain", "confidence": 0.5})
    out["capabilities"] = caps[:30]
    return out


def _fallback_profile(db: Session, session: DiscoverSession, xin: dict) -> dict:
    """No model: fact-driven profile. The ontology serves only as reference —
    a resolvable title contributes its capability names, nothing more."""
    from ..world import ontology
    p = _empty_profile()
    prof = xin["professional"]
    p["current_occupation"] = (xin["currentOccupationTitle"]
                               or prof.get("domain") or "")
    p["identity_context"] = [x for x in (xin["currentStatus"],) if x]
    p["industry"] = [prof["industry"]] if prof.get("industry") else []
    p["location"] = str(xin["geography"] or "")
    p["tasks_performed"] = list(prof.get("activities") or [])[:12]
    facts = xin["facts"]
    if facts.get("studies_field"):
        p["education"] = [str(facts["studies_field"])] if isinstance(
            facts["studies_field"], str) else ["student"]
    if facts.get("years_mentioned"):
        p["experience"] = [f"{facts['years_mentioned']} years"]
    intent = "none"
    if xin["currentStatus"] in ("founder", "freelance") or facts.get("freelance_experience"):
        intent = "operating"
    elif facts.get("commercial_evidence") or facts.get("independent_projects"):
        intent = "active"
    elif (xin["situation"] or {}).get("ambition") in ("own_thing", "running my own thing"):
        intent = "active"
    p["entrepreneurial_intent"] = intent
    vec = ontology.user_capability_vector(db, session)
    p["capabilities"] = [
        {"name": cap.replace("_", " "), "type": "domain", "confidence": round(min(1.0, w), 2)}
        for cap, w in sorted(vec.items(), key=lambda kv: -kv[1])[:18] if w >= 0.25]
    # stated activities are capabilities too — the only evidence some people
    # (no formal occupation, career breaks, students) have is what they DO
    for act in p["tasks_performed"]:
        name = str(act).lower().strip()[:60]
        if name and all(c["name"] != name for c in p["capabilities"]):
            p["capabilities"].append({"name": name, "type": "domain", "confidence": 0.5})
    if facts.get("works_with_software"):
        p["technical_skills"] = ["software"]
    p["interests"] = [t for t in xin["freeTextAnswers"][:3]]
    return p


def extract(db: Session, session: DiscoverSession, force: bool = False) -> dict:
    """Profile + provenance. Cached by input hash; LLM first, fallback always
    available. The returned dict carries how it was produced."""
    xin = _extraction_input(db, session)
    h = profile_hash(xin)
    if not force:
        cached = (db.query(DiscoveryCache)
                  .filter_by(session_id=session.id, kind="profile", profile_hash=h)
                  .order_by(DiscoveryCache.created_at.desc()).first())
        if cached:
            return cached.payload
    out = gateway.generate(db, "capability_extraction_v1", xin)
    if out and (out.get("capabilities") or out.get("technical_skills")
                or out.get("domain_knowledge")):
        profile, basis = _normalize(out), "llm"
    else:
        profile, basis = _fallback_profile(db, session, xin), "deterministic_fallback"
    payload = {"profile": profile, "basis": basis, "profileHash": h,
               "extractedAt": datetime.utcnow().isoformat() + "Z"}
    db.add(DiscoveryCache(session_id=session.id, kind="profile",
                          profile_hash=h, payload=payload))
    db.flush()
    return payload


def capability_names(profile: dict) -> list[str]:
    names = [c["name"] for c in profile.get("capabilities", []) if c.get("name")]
    for key in ("technical_skills", "domain_knowledge", "business_skills", "soft_skills", "tools"):
        names.extend(str(x).lower() for x in profile.get(key, []))
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out
