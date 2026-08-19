"""Evidence-gated public-figure resonance.

USER STATE -> SUPPORTED USER PATTERNS -> PATTERN RETRIEVAL -> EVIDENCE FILTER
-> SIMILARITY / RANKING -> DIVERSITY -> (optional LLM presentation elsewhere)

Matches are PATTERNS, never people ("83% Person A" does not exist here).
Fame is not a ranking feature. Weak evidence returns NO matches — honesty is
what makes later matches credible. Every returned match traces
pattern -> approved evidence -> stored source, failing closed otherwise.
"""
from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from .figure_kb import CONSTRUCTS, pattern_bundle
from .models import (DiscoverSession, PublicFigure, PublicFigureMatchFeedback,
                     PublicFigurePattern, ResonanceSnapshot)

# how the interpretable human-state dimensions project onto the approved
# professional-pattern taxonomy; weights are contribution strengths
DIM_TO_CONSTRUCT: dict[str, list[tuple[str, float]]] = {
    "implementation_affinity": [("builder_orientation", 1.0)],
    "initiative": [("builder_orientation", 0.5)],
    "velocity": [("experimentation", 0.4)],
    "experimentation": [("experimentation", 1.0)],
    "mastery": [("technical_depth", 0.7), ("domain_depth", 0.6), ("long_term_orientation", 0.4)],
    "analytical": [("technical_depth", 0.5)],
    "domain_expertise": [("domain_depth", 1.0)],
    "systems_thinking": [("systems_thinking", 1.0)],
    "pattern_recognition": [("systems_thinking", 0.4)],
    "detail_orientation": [("product_obsession", 0.6)],
    "aesthetic_sensitivity": [("product_obsession", 0.6)],
    "persistence": [("long_term_orientation", 0.9)],
    "leadership": [("operational_leadership", 0.8)],
    "facilitation": [("operational_leadership", 0.5)],
    "planning": [("operational_leadership", 0.4)],
    "sales_comfort": [("commercial_orientation", 1.0)],
    "revenue_ambition": [("commercial_orientation", 0.6)],
    "risk_tolerance": [("risk_behavior", 1.0)],
    "exploration": [("learning_behavior", 0.6)],
    "adaptability": [("learning_behavior", 0.6)],
    "audience": [("distribution_orientation", 0.9)],
    "persuasion": [("distribution_orientation", 0.6)],
    "storytelling": [("distribution_orientation", 0.6)],
    "teaching": [("distribution_orientation", 0.4), ("learning_behavior", 0.3)],
}

# explicit professional facts strengthen constructs beyond inferred dimensions
PRACTICAL_TO_CONSTRUCT: dict[str, list[tuple[str, float]]] = {
    "builds_things": [("builder_orientation", 0.5)],
    "commercial_evidence": [("commercial_orientation", 0.5)],
    "freelance_experience": [("commercial_orientation", 0.3), ("risk_behavior", 0.25)],
    "management_exposure": [("operational_leadership", 0.5)],
}

# chapter-specific construct emphasis (the resonance engine adapts, §21)
CHAPTER_CONSTRUCT_WEIGHTS: dict[str, dict[str, float]] = {
    "SELF_DISCOVERY_CLOSING": {"builder_orientation": 1.0, "experimentation": 1.0, "learning_behavior": 0.9,
                               "risk_behavior": 0.8, "product_obsession": 0.8, "systems_thinking": 0.8},
    "REFLECTION_CLOSING": {c: 1.0 for c in CONSTRUCTS},
    "ALIGNMENT_CLOSING": {"commercial_orientation": 1.1, "operational_leadership": 1.1, "domain_depth": 1.0,
                          "distribution_orientation": 1.0, "builder_orientation": 0.9, "technical_depth": 0.9,
                          "long_term_orientation": 0.8, "learning_behavior": 0.8},
    "TRANSFORMATION_CLOSING": {c: 1.0 for c in CONSTRUCTS},
}

# professional-status adaptation: which constructs professional context can support
STATUS_CONSTRUCTS = {
    "student": ["learning_behavior", "builder_orientation", "experimentation", "domain_depth", "commercial_orientation"],
    "employed": ["domain_depth", "operational_leadership", "systems_thinking", "commercial_orientation", "technical_depth"],
    "founder": ["commercial_orientation", "distribution_orientation", "builder_orientation", "operational_leadership", "risk_behavior"],
    "freelance": ["commercial_orientation", "builder_orientation", "domain_depth", "risk_behavior"],
    "between_roles": ["learning_behavior", "domain_depth", "risk_behavior"],
}

# real thresholds behind the human labels — never invented confidence
MIN_FEATURE_CONFIDENCE = 0.30
MIN_RESONANCE_SCORE = 0.30
STRENGTH_LABELS = [(0.55, "Strong overlap"), (0.42, "Emerging"), (0.30, "Weak echo")]

CHAPTER_MAX_MATCHES = {"SELF_DISCOVERY_CLOSING": 2, "REFLECTION_CLOSING": 3,
                       "ALIGNMENT_CLOSING": 3, "TRANSFORMATION_CLOSING": 3}


def user_construct_features(session: DiscoverSession) -> dict[str, dict]:
    """Supported user features in construct space, each carrying the human-
    readable evidence that produced it (shown as 'your evidence')."""
    feats: dict[str, dict] = {}
    from .dimensions import dim_phrase
    for dim, d in (session.dimensions or {}).items():
        est, conf = d.get("estimate", 0.0), d.get("confidence", 0.0)
        if conf < MIN_FEATURE_CONFIDENCE or est <= 0.05:
            continue  # only positively-supported ends map onto figure patterns
        for construct, w in DIM_TO_CONSTRUCT.get(dim, []):
            f = feats.setdefault(construct, {"score": 0.0, "confidence": 0.0, "evidence": []})
            contribution = est * conf * w
            if contribution <= 0:
                continue
            f["score"] = min(1.0, f["score"] + contribution)
            f["confidence"] = max(f["confidence"], conf * w)
            f["evidence"].append(f"you kept choosing {dim_phrase(dim, est)} "
                                 f"({d.get('evidence_count', 0)} separate moments)")
    pc = session.practical_context or {}
    for key, mappings in PRACTICAL_TO_CONSTRUCT.items():
        if pc.get(key):
            for construct, w in mappings:
                f = feats.setdefault(construct, {"score": 0.0, "confidence": 0.0, "evidence": []})
                f["score"] = min(1.0, f["score"] + w)
                f["confidence"] = max(f["confidence"], 0.75)
                f["evidence"].append({"builds_things": "you told us you build things",
                                      "commercial_evidence": "you've already been paid for your work",
                                      "freelance_experience": "you've worked independently for real clients",
                                      "management_exposure": "you've led people"}[key])
    for f in feats.values():
        f["evidence"] = f["evidence"][:3]
    return feats


def _fingerprint(feats: dict) -> str:
    basis = "|".join(f"{c}:{round(v['score'], 2)}" for c, v in sorted(feats.items()))
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def _status_filter(session: DiscoverSession, chapter: str, construct: str) -> bool:
    """From ALIGNMENT on, professional context gates which constructs are
    comparable — psychology alone no longer carries a professional match."""
    if chapter not in ("ALIGNMENT_CLOSING", "TRANSFORMATION_CLOSING"):
        return True
    from .professional import current_status
    status = current_status(session)
    if not status:
        return True
    return construct in STATUS_CONSTRUCTS.get(status, CONSTRUCTS)


def _rejected_figures(db: Session, session: DiscoverSession) -> dict[str, str]:
    """figure_id -> evidence fingerprint at rejection time. A rejected match may
    only return once the user's supporting evidence has materially changed."""
    out = {}
    for fb in db.query(PublicFigureMatchFeedback).filter_by(session_id=session.id, verdict="not_relevant"):
        out[fb.figure_id] = fb.evidence_fingerprint
    return out


def compute_matches(db: Session, session: DiscoverSession, chapter: str) -> dict:
    """Full pipeline; returns {matches, considered, fingerprint, movement}."""
    feats = user_construct_features(session)
    fingerprint = _fingerprint(feats)
    chapter_w = CHAPTER_CONSTRUCT_WEIGHTS.get(chapter, {c: 1.0 for c in CONSTRUCTS})
    rejected = _rejected_figures(db, session)
    considered: list[dict] = []
    scored: list[dict] = []

    patterns = (db.query(PublicFigurePattern).join(PublicFigure)
                .filter(PublicFigurePattern.status == "active", PublicFigure.status == "active").all())
    for p in patterns:
        fig = db.get(PublicFigure, p.figure_id)
        entry = {"figureId": fig.id, "figure": fig.name, "patternId": p.id, "construct": p.construct}
        feat = feats.get(p.construct)
        if not feat:
            considered.append({**entry, "outcome": "rejected", "why": "no supported user feature for construct"})
            continue
        if not _status_filter(session, chapter, p.construct):
            considered.append({**entry, "outcome": "rejected", "why": "professional context does not support this construct"})
            continue
        if fig.id in rejected and rejected[fig.id] == fingerprint:
            considered.append({**entry, "outcome": "rejected", "why": "user marked not relevant; no new evidence since"})
            continue
        bundle = pattern_bundle(db, p)
        if not bundle:
            considered.append({**entry, "outcome": "rejected", "why": "evidence chain broken — fail closed"})
            continue
        # RESONANCE_SCORE (§15): similarity x user confidence x evidence quality
        # x chapter relevance, minus overclaim penalty; fame is absent by design
        similarity = min(1.0, feat["score"]) * (0.7 + 0.3 * p.confidence)
        score = (similarity
                 * (0.6 + 0.4 * feat["confidence"])
                 * (0.7 + 0.3 * fig.evidence_quality)
                 * chapter_w.get(p.construct, 0.6))
        score -= max(0.0, 0.25 - fig.evidence_quality * 0.25)  # overclaim penalty for thin sourcing
        entry.update({"score": round(score, 3)})
        if score < MIN_RESONANCE_SCORE:
            considered.append({**entry, "outcome": "rejected", "why": f"below evidence threshold ({round(score, 2)} < {MIN_RESONANCE_SCORE})"})
            continue
        strength = next(label for cutoff, label in STRENGTH_LABELS if score >= cutoff)
        scored.append({**entry, "strength": strength, "figureDomains": fig.primary_domains,
                       "figureRoles": fig.professional_roles, "description": bundle["description"],
                       "theirEvidence": bundle["evidence"], "userEvidence": feat["evidence"]})

    scored.sort(key=lambda m: m["score"], reverse=True)
    # DIVERSITY: one pattern per figure, one figure per construct, and avoid
    # three matches sharing a single professional role
    matches: list[dict] = []
    used_figures, used_constructs, role_counts = set(), set(), {}
    for m in scored:
        if m["figureId"] in used_figures or m["construct"] in used_constructs:
            considered.append({k: m[k] for k in ("figureId", "figure", "patternId", "construct", "score")}
                              | {"outcome": "rejected", "why": "diversity — figure or construct already represented"})
            continue
        primary_role = (m["figureRoles"] or ["other"])[0]
        if role_counts.get(primary_role, 0) >= 2:
            considered.append({k: m[k] for k in ("figureId", "figure", "patternId", "construct", "score")}
                              | {"outcome": "rejected", "why": f"diversity — enough {primary_role}s already"})
            continue
        matches.append(m)
        used_figures.add(m["figureId"])
        used_constructs.add(m["construct"])
        role_counts[primary_role] = role_counts.get(primary_role, 0) + 1
        considered.append({k: m[k] for k in ("figureId", "figure", "patternId", "construct", "score")}
                          | {"outcome": "selected", "why": f"supported {m['construct']} overlap, {m['strength'].lower()}"})
        if len(matches) >= CHAPTER_MAX_MATCHES.get(chapter, 3):
            break

    movement = _movement(db, session, matches)
    snapshot = ResonanceSnapshot(session_id=session.id, chapter=chapter,
                                 matches=[{k: v for k, v in m.items() if k != "theirEvidence"} | {"theirEvidence": m["theirEvidence"]} for m in matches],
                                 candidates_considered=considered[-60:],
                                 user_feature_fingerprint=fingerprint)
    db.add(snapshot)
    db.flush()
    return {"matches": matches, "considered": considered, "fingerprint": fingerprint, "movement": movement}


def _movement(db: Session, session: DiscoverSession, current: list[dict]) -> dict:
    prev = (db.query(ResonanceSnapshot).filter_by(session_id=session.id)
            .order_by(ResonanceSnapshot.created_at.desc()).first())
    if not prev:
        return {"appeared": [m["figure"] for m in current], "disappeared": [], "strengthened": [], "first": True}
    prev_by_fig = {m["figureId"]: m for m in (prev.matches or [])}
    cur_by_fig = {m["figureId"]: m for m in current}
    return {
        "first": False,
        "appeared": [m["figure"] for fid, m in cur_by_fig.items() if fid not in prev_by_fig],
        "disappeared": [m["figure"] for fid, m in prev_by_fig.items() if fid not in cur_by_fig],
        "strengthened": [m["figure"] for fid, m in cur_by_fig.items()
                         if fid in prev_by_fig and m["score"] > prev_by_fig[fid]["score"] + 0.04],
    }


def record_feedback(db: Session, session: DiscoverSession, figure_id: str,
                    pattern_id: str | None, verdict: str, chapter: str) -> None:
    feats = user_construct_features(session)
    db.add(PublicFigureMatchFeedback(
        session_id=session.id, figure_id=figure_id, pattern_id=pattern_id,
        verdict=verdict, chapter=chapter, evidence_fingerprint=_fingerprint(feats)))
    db.flush()
