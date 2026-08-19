"""Quote Intelligence: retrieval, ranking and the 'same principle, different
world' module.

    SUPPORTED USER PATTERN → RETRIEVE VERIFIED QUOTE → RANK → DISPLAY

The LLM never supplies a quote; it may only write the one sentence tying a
retrieved quote back to the user's own evidence. Unverified rows can never be
displayed. A quote is narrative context only — it never touches Human State,
Professional State or ranking (§52), so no circular inference is possible.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import thresholds as th
from .dimensions import dim_fragment
from .models import (DiscoverSession, PatternValueRelationship, QuoteImpression,
                     QuotePerson, QuoteRecord, QuoteSource)

# a quote only appears when the pattern behind it is genuinely supported
MIN_PATTERN_CONFIDENCE = th.MAY_TEST          # 0.70
MIN_QUOTE_SCORE = 0.35

CHAPTER_THEME_BIAS = {
    "SELF_DISCOVERY_CLOSING": {"FOCUS": 1.1, "CRAFT": 1.05, "LEARNING": 1.1,
                               "EXPERIMENTATION": 1.05, "DISCIPLINE": 1.0},
    "REFLECTION_CLOSING": {"PERSISTENCE": 1.15, "CONVICTION": 1.1, "DISCIPLINE": 1.1,
                           "RISK": 1.05, "FOCUS": 1.0},
    "ALIGNMENT_CLOSING": {"CRAFT": 1.15, "SYSTEMS": 1.15, "QUALITY": 1.1,
                          "OWNERSHIP": 1.15, "EXECUTION": 1.1, "COMPOUNDING": 1.1},
    "TRANSFORMATION_CLOSING": {"OWNERSHIP": 1.2, "COMPOUNDING": 1.2, "EXECUTION": 1.1,
                               "SYSTEMS": 1.05},
}


def seed(db: Session) -> int:
    from . import quote_seeds as s
    if db.query(QuoteRecord).count():
        return 0
    for pid, name, field, descriptor, era in s.PEOPLE:
        if not db.get(QuotePerson, pid):
            db.add(QuotePerson(id=pid, name=name, field=field,
                               descriptor=descriptor, era=era))
    for sid, kind, title, publisher, url, published_at, cred in s.SOURCES:
        if not db.get(QuoteSource, sid):
            db.add(QuoteSource(id=sid, kind=kind, title=title, publisher=publisher,
                               url=url, published_at=published_at, credibility=cred))
    db.flush()
    added = 0
    for qid, pid, sid, text, context, themes, patterns, quality in s.QUOTES:
        if db.get(QuoteRecord, qid):
            continue
        db.add(QuoteRecord(id=qid, person_id=pid, source_id=sid, quote_text=text,
                           context=context, themes=themes, professional_patterns=patterns,
                           # seeded UNVERIFIED on purpose: a human signs off before
                           # anything is shown to a user
                           verification_status="review_needed",
                           evidence_quality=quality))
        added += 1
    for rid, pattern, context, mechanisms, explanation, conf in s.PATTERN_VALUE:
        if not db.get(PatternValueRelationship, rid):
            db.add(PatternValueRelationship(id=rid, pattern=pattern, context=context,
                                            value_mechanisms=mechanisms,
                                            explanation=explanation, confidence=conf))
    db.flush()
    return added


# ---------------- retrieval ----------------

def _supported_patterns(db: Session, session: DiscoverSession) -> list[dict]:
    """The user's own supported constructs — the ONLY thing that can pull a quote."""
    from .world.ontology import user_capability_vector   # noqa: F401  (kept for parity)
    from .resonance import user_construct_features
    feats = user_construct_features(session)
    out = []
    for construct, f in feats.items():
        if f["confidence"] >= MIN_PATTERN_CONFIDENCE and f["score"] >= 0.35:
            out.append({"construct": construct, "confidence": f["confidence"],
                        "score": f["score"], "evidence": f["evidence"]})
    out.sort(key=lambda p: -(p["score"] * p["confidence"]))
    return out


def _seen(db: Session, session: DiscoverSession) -> dict:
    rows = db.query(QuoteImpression).filter_by(session_id=session.id).all()
    return {"quotes": {r.quote_id for r in rows},
            "people": {r.person_id for r in rows},
            "themes": {r.theme for r in rows if r.theme},
            "modules": [r.module for r in rows]}


def _bundle(db: Session, quote: QuoteRecord) -> dict | None:
    person = db.get(QuotePerson, quote.person_id)
    source = db.get(QuoteSource, quote.source_id)
    if not person or not source:
        return None          # fail closed: no provenance, no display
    return {
        "quoteId": quote.id, "text": quote.quote_text, "context": quote.context,
        "person": {"id": person.id, "name": person.name, "field": person.field,
                   "descriptor": person.descriptor, "era": person.era},
        "source": {"title": source.title, "kind": source.kind,
                   "publisher": source.publisher, "url": source.url,
                   "year": source.published_at},
        "themes": quote.themes,
    }


def select_quote(db: Session, session: DiscoverSession, chapter: str) -> dict | None:
    """One quote for one supported pattern — or nothing. A forced quote is
    worse than no quote."""
    patterns = _supported_patterns(db, session)
    if not patterns:
        return None
    seen = _seen(db, session)
    bias = CHAPTER_THEME_BIAS.get(chapter, {})
    candidates = (db.query(QuoteRecord)
                  .filter(QuoteRecord.verification_status == "verified").all())
    best, best_score = None, 0.0
    for quote in candidates:
        if quote.id in seen["quotes"] or quote.person_id in seen["people"]:
            continue                                  # never the same voice twice
        for p in patterns:
            if p["construct"] not in (quote.professional_patterns or []):
                continue
            theme_bias = max((bias.get(t, 0.9) for t in (quote.themes or [])), default=0.9)
            novelty = 0.75 if any(t in seen["themes"] for t in (quote.themes or [])) else 1.0
            score = (p["score"] * p["confidence"] * quote.evidence_quality
                     * theme_bias * novelty)
            if score > best_score:
                best, best_score = (quote, p), score
    if not best or best_score < MIN_QUOTE_SCORE:
        return None
    quote, pattern = best
    bundle = _bundle(db, quote)
    if not bundle:
        return None
    bundle["forPattern"] = pattern["construct"].replace("_", " ")
    bundle["yourEvidence"] = pattern["evidence"][:2]
    bundle["score"] = round(best_score, 3)
    return bundle


def same_principle_different_world(db: Session, session: DiscoverSession,
                                   chapter: str) -> dict | None:
    """Two people from DIFFERENT fields who arrived at the same working
    principle. The point is never the names — it is that the principle recurs."""
    patterns = _supported_patterns(db, session)
    if not patterns:
        return None
    seen = _seen(db, session)
    verified = (db.query(QuoteRecord)
                .filter(QuoteRecord.verification_status == "verified").all())
    by_theme: dict[str, list[QuoteRecord]] = {}
    for q in verified:
        if q.id in seen["quotes"] or q.person_id in seen["people"]:
            continue
        for theme in (q.themes or []):
            by_theme.setdefault(theme, []).append(q)

    for p in patterns:
        for theme, quotes in by_theme.items():
            relevant = [q for q in quotes if p["construct"] in (q.professional_patterns or [])]
            fields, picked = set(), []
            for q in sorted(relevant, key=lambda x: -x.evidence_quality):
                person = db.get(QuotePerson, q.person_id)
                if not person or person.field in fields:
                    continue           # the whole point is DIFFERENT worlds
                fields.add(person.field)
                picked.append(q)
                if len(picked) == 2:
                    break
            if len(picked) == 2:
                bundles = [_bundle(db, q) for q in picked]
                if not all(bundles):
                    continue
                return {
                    "theme": theme,
                    "people": bundles,
                    "overlap": (f"Different fields — {bundles[0]['person']['field']} and "
                                f"{bundles[1]['person']['field']} — and the same working "
                                f"principle: {theme.lower().replace('_', ' ')}."),
                    "honesty": "Their goals and circumstances had almost nothing in common. "
                               "One principle overlaps, and that is all we are claiming.",
                    "forPattern": p["construct"].replace("_", " "),
                    "yourEvidence": p["evidence"][:2],
                }
    return None


def record_impression(db: Session, session: DiscoverSession, bundle: dict,
                      module: str, chapter: str) -> None:
    people = bundle.get("people") or [bundle]
    theme = bundle.get("theme") or (bundle.get("themes") or [""])[0]
    for entry in people:
        db.add(QuoteImpression(session_id=session.id, quote_id=entry.get("quoteId", ""),
                               person_id=(entry.get("person") or {}).get("id", ""),
                               theme=theme, module=module, chapter=chapter))
    db.flush()


# ---------------- pattern → value ----------------

def value_of_pattern(db: Session, session: DiscoverSession, construct: str) -> dict | None:
    """Why a personal pattern might matter economically, in this person's
    context. This is what turns an observation into leverage."""
    rows = db.query(PatternValueRelationship).filter_by(pattern=construct).all()
    if not rows:
        return None
    from .world.ontology import resolve_user_occupation
    from .models import WIOccupation
    resolution = resolve_user_occupation(db, session)
    work_class = None
    if resolution.get("candidates"):
        occ = db.get(WIOccupation, resolution["candidates"][0]["occupationId"])
        work_class = occ.work_class if occ else None
    best = None
    for row in rows:
        fit = 1.0 if (work_class and work_class in (row.context or [])) else 0.6
        if not best or fit * row.confidence > best[1]:
            best = (row, fit * row.confidence)
    if not best:
        return None
    row, score = best
    return {"pattern": construct.replace("_", " "), "explanation": row.explanation,
            "mechanisms": row.value_mechanisms[:3], "confidence": round(score, 2)}
