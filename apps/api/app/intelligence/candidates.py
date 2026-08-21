"""OpportunityGenerator: capability profile → candidate opportunities.

Candidates are hypotheses in four types — CAREER, BUSINESS, SKILL, TRANSITION.
The LLM proposes them from the person's actual capabilities; a deterministic
generator composes candidates from the profile when the model is unavailable.
Neither path is allowed to carry market numbers: any demand/growth/salary
figure in a candidate is stripped here, before the evidence layer runs."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..llm import gateway
from ..models import DiscoverSession
from . import profile as profile_svc

CANDIDATE_TYPES = ("career", "business", "skill", "transition")
_FORBIDDEN_KEYS = {"demand", "growth", "yoy", "salary", "market_size", "postings"}


def _clean(c: dict) -> dict | None:
    if not isinstance(c, dict) or not c.get("title"):
        return None
    ctype = c.get("type") if c.get("type") in CANDIDATE_TYPES else "career"
    return {
        "title": str(c["title"]).strip()[:120],
        "type": ctype,
        "requiredCapabilities": [str(x).lower().strip()[:60]
                                 for x in (c.get("required_capabilities") or c.get("requiredCapabilities") or [])][:12],
        "whyFromProfile": str(c.get("why_from_profile") or c.get("whyFromProfile") or "")[:300],
        # structural work assessment, 0..1 — hypothesis, labeled as such downstream
        "aiLeverage": max(0.0, min(1.0, float(c.get("ai_leverage") or c.get("aiLeverage") or 0.5))),
        "automationRisk": max(0.0, min(1.0, float(c.get("automation_risk") or c.get("automationRisk") or 0.5))),
        "humanAdvantage": max(0.0, min(1.0, float(c.get("human_advantage") or c.get("humanAdvantage") or 0.5))),
        "searchTerms": [str(x).strip()[:80] for x in (c.get("search_terms") or c.get("searchTerms") or [])][:4],
        "steps": [str(x).strip()[:80] for x in (c.get("steps") or [])][:4],
        # no market claims survive generation, whatever the model returned
        **{},
    }


def _dedupe(cands: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in cands:
        key = c["title"].lower()
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _fallback_candidates(db: Session, session: DiscoverSession, profile: dict) -> list[dict]:
    """Model unavailable: compose candidates FROM the profile's own contents.
    Templates are parameterized by what this person can do — never a lookup
    from occupation to a stored recommendation list. The ontology contributes
    only documented adjacency edges, as reference."""
    caps = profile_svc.capability_names(profile)
    if not caps:
        caps = [str(t).lower() for t in profile.get("tasks_performed") or []][:6]
    occupation = (profile.get("current_occupation") or "").strip()
    industries = profile.get("industry") or []
    domain = industries[0] if industries else (occupation or (caps[0] if caps else ""))
    intent = profile.get("entrepreneurial_intent", "none")
    out: list[dict] = []

    def add(title, ctype, req, why, lev, risk, human, terms, steps=()):
        out.append(_clean({"title": title, "type": ctype, "required_capabilities": req,
                           "why_from_profile": why, "ai_leverage": lev,
                           "automation_risk": risk, "human_advantage": human,
                           "search_terms": terms, "steps": list(steps)}))

    top = caps[:6]
    if domain:
        add(f"{domain.title()} AI Implementation Specialist", "career",
            top[:4] + ["ai workflow design", "stakeholder communication"],
            f"Puts existing {domain} knowledge in charge of how AI actually gets used there.",
            0.85, 0.25, 0.8, [f"{domain} AI", f"AI implementation {domain}"],
            )
        add(f"AI-assisted {domain} practice", "transition",
            top[:5] + ["ai tools"],
            f"The same {domain} work, run with AI doing the repeatable parts.",
            0.8, 0.3, 0.75, [f"AI {domain}", f"{domain} automation"],
            (occupation or domain, f"AI-augmented {domain}", f"{domain} AI specialist"))
    for cap in top[:3]:
        add(f"{cap.title()} + AI workflow design", "skill",
            [cap, "ai workflow design", "prompting", "evaluation"],
            f"Their strongest capability, {cap}, is the part AI amplifies rather than replaces.",
            0.85, 0.2, 0.7, [f"{cap} AI"])
        break     # one skill candidate is enough from the fallback
    if intent in ("active", "operating", "curious"):
        add(f"{(domain or 'niche').title()} automation service", "business",
            top[:4] + ["customer discovery", "automation design"],
            "Businesses in their own field pay to have repeatable work automated by "
            "someone who already understands it.",
            0.9, 0.2, 0.8, [f"{domain} automation service", f"{domain} AI consulting"])
        add(f"AI adoption consulting for {domain or 'small businesses'}", "business",
            top[:3] + ["technical consulting", "teaching"],
            "Domain insiders are who operators trust to tell them what AI is actually for.",
            0.85, 0.2, 0.85, [f"{domain} AI consultant", "AI adoption consulting"])
    # documented adjacency edges from the reference taxonomy (never a
    # recommendation table — an edge only proposes, evidence still decides)
    try:
        from ..world import ontology
        from ..models import WIOccupationTransition, WIOccupation
        res = ontology.resolve_user_occupation(db, session)
        for c in (res.get("candidates") or [])[:1]:
            edges = (db.query(WIOccupationTransition)
                     .filter_by(from_occupation_id=c["occupationId"]).all())
            for e in edges[:4]:
                target = db.get(WIOccupation, e.to_occupation_id)
                if target:
                    add(target.preferred_label, "career",
                        top[:5], e.evidence_note or "a documented adjacent move",
                        0.6, 0.4, 0.6, [target.preferred_label.lower()])
    except Exception:
        pass
    return _dedupe([c for c in out if c])


def generate(db: Session, session: DiscoverSession, profile_payload: dict) -> dict:
    profile = profile_payload["profile"]
    out = gateway.generate(db, "opportunity_generation_v1", {
        "profile": profile,
        "note": "generate candidates only; a separate layer validates against market data",
    })
    if out and isinstance(out.get("candidates"), list):
        cands = _dedupe([c for c in (_clean(x) for x in out["candidates"]) if c])
        if cands:
            return {"candidates": cands[:14], "basis": "llm"}
    return {"candidates": _fallback_candidates(db, session, profile)[:14],
            "basis": "deterministic_fallback"}
