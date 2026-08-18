"""Professional Position Model — evidence-based understanding of the person's
professional reality, kept beside the Human State Model. Status-dependent
question routing lives here; the LLM only extracts structure from free text,
never infers psychology."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .llm import gateway
from .models import DiscoverSession

STATUS_MAP = {
    "employed_good": "employed", "employed_stale": "employed",
    "founder": "founder", "freelance": "freelance",
    "student": "student", "between": "between_roles",
}


def get_position(session: DiscoverSession) -> dict:
    return dict((session.practical_context or {}).get("professional", {}))


def set_position(session: DiscoverSession, updates: dict) -> None:
    pc = dict(session.practical_context or {})
    prof = dict(pc.get("professional", {}))
    prof.update({k: v for k, v in updates.items() if v})
    pc["professional"] = prof
    session.practical_context = pc


def current_status(session: DiscoverSession) -> str | None:
    raw = (session.practical_context or {}).get("current_status")
    if raw:
        return STATUS_MAP.get(raw, raw)
    return None


def status_allows(session: DiscoverSession, requires: list[str] | None) -> bool:
    if not requires:
        return True
    status = current_status(session)
    if status is None:
        return False  # branch questions wait until status is known
    return status in requires


DOMAIN_KEYWORDS = {
    "software": ["software", "coding", "developer", "programming", "apps", "web", "engineer"],
    "logistics": ["logistics", "supply chain", "warehouse", "shipping"],
    "design": ["design", "designer", "brand", "visual"],
    "marketing": ["marketing", "growth", "ads", "content"],
    "finance": ["finance", "accounting", "investment", "banking"],
    "health": ["health", "medical", "clinic", "nurse", "doctor"],
    "education": ["teacher", "teaching", "education", "tutor"],
    "operations": ["operations", "process", "ops"],
    "sales": ["sales", "selling", "business development"],
    "engineering": ["engineering", "mechanical", "electrical", "civil"],
}


def heuristic_extract(text: str) -> dict:
    """Deterministic extraction so the engine adapts even with the LLM offline.
    One natural answer may close multiple uncertainties (status, domain,
    independent work, experience)."""
    t = text.lower()
    facts: dict = {}
    if any(w in t for w in ("student", "studying", "university", "college", "final year", "undergrad")):
        facts["current_status"] = "student"
    if any(w in t for w in ("freelanc", "clients of my own", "my own clients", "side project", "side business")):
        facts["freelance_experience"] = True
    if any(w in t for w in ("founder", "my company", "my startup", "my business", "co-founder")):
        facts["current_status"] = facts.get("current_status") or "founder"
    if any(w in t for w in ("i manage", "i lead", "my team")):
        facts["management_exposure"] = True
    for domain, words in DOMAIN_KEYWORDS.items():
        if any(w in t for w in words):
            facts["domain"] = domain
            break
    import re
    m = re.search(r"(\d+)\s*(?:\+\s*)?years?", t)
    if m:
        facts["years_mentioned"] = min(50, int(m.group(1)))
    if any(w in t for w in ("built", "building", "shipped", "launched", "created")):
        facts["builds_things"] = True
    if any(w in t for w in ("paid", "customers", "revenue", "sold", "earning", "local businesses")):
        facts["commercial_evidence"] = True
    return facts


def apply_extracted_facts(session: DiscoverSession, facts: dict) -> list[str]:
    """Explicit facts immediately reshape eligibility. Returns fact keys set."""
    if not facts:
        return []
    pc = dict(session.practical_context or {})
    changed = []
    if facts.get("current_status") and not pc.get("current_status"):
        pc["current_status"] = facts["current_status"]
        changed.append("current_status")
    for key in ("freelance_experience", "management_exposure", "builds_things",
                "commercial_evidence", "years_mentioned"):
        if key in facts and key not in pc:
            pc[key] = facts[key]
            changed.append(key)
    session.practical_context = pc
    if facts.get("domain") or facts.get("industry"):
        set_position(session, {"domain": facts.get("domain"), "industry": facts.get("industry")})
        changed.append("domain")
    return changed


def extract_profession(db: Session, session: DiscoverSession, text: str) -> list[str]:
    """Structured extraction: LLM when available, deterministic heuristics always.
    The raw answer persists separately; extraction is contextual data, never
    authoritative psychology. Returns the list of fact keys that changed."""
    facts = heuristic_extract(text)
    out = gateway.generate(db, "professional_extraction_v1", {"text": text[:300]})
    if out and isinstance(out, dict):
        set_position(session, {
            "domain": str(out.get("domain", ""))[:60] or None,
            "industry": str(out.get("industry", ""))[:60] or None,
            "function": str(out.get("function", ""))[:60] or None,
            "activities": [str(a)[:50] for a in (out.get("activities") or [])[:5]] or None,
        })
    return apply_extracted_facts(session, facts)
