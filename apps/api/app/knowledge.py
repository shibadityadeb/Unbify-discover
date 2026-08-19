"""The intelligence core: evidence ledger, versioned hypotheses, abstention.

Four levels of knowledge, never confused:
  L1 explicit fact  — stated/selected by the user (practical_context + ledger)
  L2 derived fact   — conservative normalization of L1 (ledger, kind marks it)
  L3 hypothesis     — pattern suggested by MULTIPLE evidence items (rows here)
  L4 conclusion     — allowed to influence analysis only past strict thresholds

Every hypothesis points at evidence ids. One answer can never create a role
recommendation. "We do not know yet" is a feature, not a failure.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import thresholds as th
from .dimensions import DIMENSIONS, dim_phrase
from .models import (DiscoverSession, EvidenceItem, Hypothesis, HypothesisVersion,
                     InferenceFeedback, NarrativeEvent)

RELIABILITY_BY_KIND = {
    "explicit_fact": 1.0, "correction": 0.95, "calibration": 0.85,
    "professional_history": 0.8, "behavioral_choice": 0.55,
    "free_text_extraction": 0.5, "outcome": 0.9,
}

SOURCE_TO_KIND = {
    "calibration_agree": "calibration", "calibration_partial": "calibration",
    "calibration_correction": "correction", "micro_reflection": "free_text_extraction",
}


def kind_for_source(source: str) -> str:
    return SOURCE_TO_KIND.get(source, "behavioral_choice")


def record_evidence(db: Session, session: DiscoverSession, kind: str, claim: str,
                    dims: list[dict] | None = None, strength: float = 0.4,
                    source_interaction_id: str | None = None) -> EvidenceItem:
    item = EvidenceItem(
        session_id=session.id, kind=kind, claim=claim[:400],
        dims=[{"dim": d.get("dim"), "delta": round(float(d.get("delta", 0)), 3)} for d in (dims or [])],
        strength=max(0.05, min(1.0, strength)),
        reliability=RELIABILITY_BY_KIND.get(kind, 0.5),
        source_interaction_id=source_interaction_id,
    )
    db.add(item)
    db.flush()   # session is autoflush=False: hypothesis sync queries these
    return item


def emit_event(db: Session, session: DiscoverSession, type_: str, payload: dict,
               importance: float = 0.5) -> NarrativeEvent:
    ev = NarrativeEvent(session_id=session.id, type=type_, payload=payload,
                        importance=round(importance, 3), chapter=session.journey_status)
    db.add(ev)
    db.flush()   # session is autoflush=False: later queries must see this row
    return ev


# ---------------- hypotheses (L3) ----------------

def _status_for(confidence: float, n_support: int, n_contra: int, corrected: bool) -> str:
    if corrected:
        return "corrected"
    if n_contra and n_contra >= n_support:
        return "contradicted"
    if n_support < th.HYPOTHESIS_MIN_EVIDENCE:
        return "emerging"          # one answer is never "supported"
    if confidence >= th.MAY_TEST:
        return "supported"
    if n_contra:
        return "uncertain"
    return "emerging"


def sync_hypotheses(db: Session, session: DiscoverSession, trigger: str) -> list[dict]:
    """Reconcile hypothesis rows with the current evidence ledger + dimension
    state. Versions on material change; emits narrative events for the story.
    Returns a change summary for the inspector."""
    changes: list[dict] = []
    items = db.query(EvidenceItem).filter_by(session_id=session.id).all()
    by_dim_support: dict[tuple[str, int], list[str]] = {}
    by_dim_contra: dict[tuple[str, int], list[str]] = {}
    for item in items:
        for d in item.dims or []:
            dim, delta = d.get("dim"), d.get("delta", 0)
            if not dim or not delta:
                continue
            direction = 1 if delta > 0 else -1
            by_dim_support.setdefault((dim, direction), []).append(item.id)
            by_dim_contra.setdefault((dim, -direction), []).append(item.id)

    corrected_constructs = {fb.hypothesis_construct for fb in
                            db.query(InferenceFeedback).filter_by(session_id=session.id)
                            if fb.rejection in ("not_really", "no")}

    # load every hypothesis for this session in ONE query. Doing it per
    # dimension is an N+1 that costs a full network round trip each time —
    # invisible on localhost, brutal against a remote database.
    existing: dict[tuple[str, int], Hypothesis] = {
        (h.construct, h.direction): h
        for h in db.query(Hypothesis).filter_by(session_id=session.id).all()}
    created: list[tuple[Hypothesis, str]] = []

    for dim, state in (session.dimensions or {}).items():
        est, conf = state.get("estimate", 0.0), state.get("confidence", 0.0)
        if state.get("evidence_count", 0) == 0 or abs(est) < 0.05:
            continue
        direction = 1 if est >= 0 else -1
        support = by_dim_support.get((dim, direction), [])
        contra = by_dim_contra.get((dim, direction), [])
        corrected = dim in corrected_constructs
        status = _status_for(conf, len(support), len(contra), corrected)
        hyp = existing.get((dim, direction))
        if not hyp:
            hyp = Hypothesis(session_id=session.id, construct=dim, direction=direction,
                             statement=f"leans toward {dim_phrase(dim, direction)}",
                             thresholds_version=th.THRESHOLDS_VERSION)
            db.add(hyp)
            existing[(dim, direction)] = hyp
            prev_conf, prev_status = 0.0, None
        else:
            prev_conf, prev_status = hyp.confidence, hyp.status
        hyp.supporting_evidence_ids = support[-20:]
        hyp.contradicting_evidence_ids = contra[-20:]
        hyp.confidence = round(conf, 3)
        hyp.status = status
        material = (abs(conf - prev_conf) >= th.VERSION_DELTA) or (status != prev_status)
        if material:
            hyp.version = (hyp.version or 1) + (1 if prev_status is not None else 0)
            created.append((hyp, status))
            changes.append({"construct": dim, "direction": direction,
                            "from": {"confidence": round(prev_conf, 2), "status": prev_status},
                            "to": {"confidence": round(conf, 2), "status": status}})
            if prev_status is not None:
                if conf - prev_conf >= 0.12 and conf >= th.WEAK_INTERNAL:
                    emit_event(db, session, "HYPOTHESIS_STRENGTHENED",
                               {"construct": dim, "direction": direction,
                                "confidence": round(conf, 2)}, importance=min(0.9, conf))
                elif prev_conf - conf >= 0.15 or (status in ("contradicted", "corrected")
                                                  and prev_status not in ("contradicted", "corrected")):
                    emit_event(db, session, "HYPOTHESIS_COLLAPSED",
                               {"construct": dim, "direction": direction,
                                "from": round(prev_conf, 2), "to": round(conf, 2),
                                "status": status}, importance=0.8)
    if created:
        db.flush()          # one flush assigns ids to every new hypothesis
        for hyp, status in created:
            db.add(HypothesisVersion(hypothesis_id=hyp.id, session_id=session.id,
                                     version=hyp.version, confidence=hyp.confidence,
                                     status=status, trigger=trigger,
                                     chapter=session.journey_status))
        db.flush()
    return changes


def hypothesis_history(db: Session, session: DiscoverSession) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    rows = (db.query(HypothesisVersion).filter_by(session_id=session.id)
            .order_by(HypothesisVersion.created_at.asc()).all())
    hyps = {h.id: h for h in db.query(Hypothesis).filter_by(session_id=session.id).all()}
    for row in rows:
        hyp = hyps.get(row.hypothesis_id)
        if not hyp:
            continue
        out.setdefault(f"{hyp.construct}:{hyp.direction}", []).append(
            {"version": row.version, "confidence": row.confidence,
             "status": row.status, "chapter": row.chapter, "trigger": row.trigger})
    return out


# ---------------- abstention (PART 4) ----------------

def inference_decision(db: Session, session: DiscoverSession, construct: str) -> dict:
    """The system deciding whether it actually knows something."""
    from .models import AmbiguityRecord
    open_amb = (db.query(AmbiguityRecord)
                .filter_by(session_id=session.id, status="open")
                .filter(AmbiguityRecord.clarification_value >= th.CLARIFICATION_VALUE_MIN).all())
    related = next((a for a in open_amb if construct in (a.possible_interpretations or [])
                    or construct in a.key), None)
    if related:
        return {"status": "needs_clarification", "ambiguity": related.key}
    state = (session.dimensions or {}).get(construct, {})
    conf = state.get("confidence", 0.0)
    n = state.get("evidence_count", 0)
    if conf >= th.MAY_TEST and n >= th.HYPOTHESIS_MIN_EVIDENCE:
        return {"status": "supported",
                "hypothesis": f"leans toward {dim_phrase(construct, state.get('estimate', 1))}",
                "confidence": round(conf, 2)}
    return {"status": "insufficient_evidence"}


def overinterpretation_risk(claim_strength: float, evidence_confidence: float) -> float:
    """How much stronger is the claim than the evidence supporting it?"""
    return round(max(0.0, claim_strength - evidence_confidence), 3)


# ---------------- corrections + cascade invalidation (PART 55/56) ----------------

def record_correction(db: Session, session: DiscoverSession, construct: str,
                      rejection: str, context: dict, policy_version: str = "") -> None:
    hyp = db.query(Hypothesis).filter_by(session_id=session.id, construct=construct).first()
    db.add(InferenceFeedback(
        session_id=session.id, hypothesis_construct=construct,
        supporting_evidence_ids=(hyp.supporting_evidence_ids if hyp else []),
        rejection=rejection, context=context, policy_version=policy_version,
        thresholds_version=th.THRESHOLDS_VERSION))
    emit_event(db, session, "USER_CORRECTED_SYSTEM",
               {"construct": construct, "rejection": rejection}, importance=0.85)
    if rejection in ("not_really", "no"):
        cascade_invalidate(db, session, construct)


def cascade_invalidate(db: Session, session: DiscoverSession, construct: str) -> list[str]:
    """A corrected hypothesis must not leave stale downstream conclusions."""
    invalidated: list[str] = []
    pc = dict(session.practical_context or {})
    if pc.get("_lives"):
        pc.pop("_lives", None)
        invalidated.append("possible_lives_cache")
    if pc.get("_closing_cache"):
        pc.pop("_closing_cache", None)
        invalidated.append("closing_cache")
    session.practical_context = pc
    counters = dict(session.counters or {})
    if counters.get("lives_generated"):
        counters["lives_generated"] = False   # regenerate with corrected state
        invalidated.append("lives_generated_flag")
    session.counters = counters
    return invalidated


# ---------------- L4 gate: professional / role-level analysis ----------------

def role_analysis_allowed(session: DiscoverSession) -> tuple[bool, str]:
    """PART 59: minimum evidence before ranking specific directions."""
    pc = session.practical_context or {}
    fact_keys = [k for k in pc if not k.startswith("_")
                 and k not in ("notes", "resonant_life")]
    if len(fact_keys) < th.ROLE_ANALYSIS_MIN_FACTS:
        return False, f"professional context coverage too low ({len(fact_keys)}/{th.ROLE_ANALYSIS_MIN_FACTS} facts)"
    strong = [d for d, s in (session.dimensions or {}).items()
              if s.get("confidence", 0) >= th.PROFESSIONAL_SURFACE
              and s.get("evidence_count", 0) >= th.HYPOTHESIS_MIN_EVIDENCE]
    if len(strong) < th.ROLE_ANALYSIS_MIN_FEATURES:
        return False, f"relevant feature confidence too low ({len(strong)}/{th.ROLE_ANALYSIS_MIN_FEATURES} supported features)"
    return True, "evidence sufficient"
