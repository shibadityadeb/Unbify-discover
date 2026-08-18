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


def extract_profession(db: Session, session: DiscoverSession, text: str) -> None:
    """LLM extraction of structured professional attributes. The raw answer is
    persisted separately (practical_context.profession_text); extraction is
    contextual data, never authoritative psychology."""
    out = gateway.generate(db, "professional_extraction_v1", {"text": text[:300]})
    if out and isinstance(out, dict):
        set_position(session, {
            "domain": str(out.get("domain", ""))[:60] or None,
            "industry": str(out.get("industry", ""))[:60] or None,
            "function": str(out.get("function", ""))[:60] or None,
            "activities": [str(a)[:50] for a in (out.get("activities") or [])[:5]] or None,
        })
