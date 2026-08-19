"""Authoritative Signal Engine. The LLM never scores choices.
One interaction only ever contributes weak evidence; several independent
signals build confidence; user corrections outweigh inference;
contradictions are preserved, never averaged away."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .dimensions import DIMENSIONS, is_dim
from .models import DiscoverSession, SignalEvidence

SIGNAL_VERSION = "sig_v1"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _ensure(dimensions: dict, dim: str) -> dict:
    if dim not in dimensions:
        dimensions[dim] = {"estimate": 0.0, "confidence": 0.0, "variance": 0.0,
                           "evidence_count": 0, "pos_w": 0.0, "neg_w": 0.0}
    return dimensions[dim]


def apply_evidence(
    db: Session,
    session: DiscoverSession,
    evidence: list[dict],
    source: str,
    instance_id: str | None = None,
    response_id: str | None = None,
    latency_ms: int | None = None,
) -> list[SignalEvidence]:
    """evidence: [{dim, delta(-1..1), weight(0..1.6)}]"""
    dims = dict(session.dimensions or {})
    rows: list[SignalEvidence] = []
    updates: dict[str, float] = {}
    weights: list[float] = []
    for ev in evidence:
        dim = ev.get("dim")
        if not is_dim(dim):
            continue
        delta = _clamp(float(ev.get("delta", 0)), -1, 1)
        weight = _clamp(float(ev.get("weight", 0.4)), 0.05, 1.6)
        if delta == 0:
            continue
        d = _ensure(dims, dim)
        if delta > 0:
            d["pos_w"] += weight * delta
        else:
            d["neg_w"] += weight * -delta
        total = d["pos_w"] + d["neg_w"]
        d["estimate"] = (d["pos_w"] - d["neg_w"]) / total if total else 0.0
        d["confidence"] = min(0.92, total / 3.2)
        d["variance"] = (min(d["pos_w"], d["neg_w"]) / total) if total else 0.0
        d["evidence_count"] += 1
        updates[dim] = delta
        weights.append(weight)
    if updates:
        row = SignalEvidence(
            session_id=session.id, instance_id=instance_id, response_id=response_id,
            construct_updates=updates, weight=sum(weights) / len(weights),
            confidence=min(0.9, sum(weights) / len(weights)),
            source=source, signal_version=SIGNAL_VERSION, latency_ms=latency_ms,
        )
        db.add(row)
        rows.append(row)
        # evidence ledger: every meaningful interpretation traces back here
        from . import knowledge
        from .dimensions import dim_fragment
        pieces = [f"chose toward {dim_fragment(d, delta)}" for d, delta in list(updates.items())[:3]]
        knowledge.record_evidence(
            db, session, knowledge.kind_for_source(source),
            f"[{source}] " + "; ".join(pieces),
            dims=[{"dim": d, "delta": delta} for d, delta in updates.items()],
            strength=sum(weights) / len(weights), source_interaction_id=instance_id)
    pre_contradictions = len(session.contradictions or [])
    session.dimensions = dims
    _detect_contradictions(session)
    if len(session.contradictions or []) > pre_contradictions:
        from . import knowledge
        new_c = (session.contradictions or [])[-1]
        knowledge.emit_event(db, session, "CONTRADICTION_APPEARED",
                             {"dim": new_c.get("dim")}, importance=0.8)
    return rows


def _detect_contradictions(session: DiscoverSession) -> None:
    existing = {c["dim"] for c in (session.contradictions or [])}
    contradictions = list(session.contradictions or [])
    for dim, d in (session.dimensions or {}).items():
        if d.get("pos_w", 0) >= 1.1 and d.get("neg_w", 0) >= 1.1 and dim not in existing:
            contradictions.append({"dim": dim, "explored": False})
    session.contradictions = contradictions


def top_dims(session: DiscoverSession, n: int = 3, min_confidence: float = 0.2,
             families: list[str] | None = None) -> list[dict]:
    out = []
    for dim, d in (session.dimensions or {}).items():
        if d.get("confidence", 0) < min_confidence:
            continue
        if families and DIMENSIONS[dim]["family"] not in families:
            continue
        out.append({"dim": dim, **d})
    out.sort(key=lambda x: abs(x["estimate"]) * x["confidence"], reverse=True)
    return out[:n]


def thinnest_dims(session: DiscoverSession, families: list[str], n: int = 4) -> list[str]:
    pool = [(dim, (session.dimensions or {}).get(dim, {}).get("evidence_count", 0))
            for dim, meta in DIMENSIONS.items() if meta["family"] in families]
    pool.sort(key=lambda p: p[1])
    return [dim for dim, _ in pool[:n]]


def total_evidence(session: DiscoverSession) -> int:
    return sum(d.get("evidence_count", 0) for d in (session.dimensions or {}).values())


def information_gain_estimate(session: DiscoverSession, targets: list[str]) -> float:
    """Expected uncertainty reduction: prefer dimensions we know least about."""
    if not targets:
        return 0.3
    gains = []
    for dim in targets:
        d = (session.dimensions or {}).get(dim, {})
        gains.append(1.0 - d.get("confidence", 0.0))
    return sum(gains) / len(gains)
