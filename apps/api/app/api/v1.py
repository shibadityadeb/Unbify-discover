"""Versioned public API. The server owns authoritative journey progression."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import orchestrator, statemachine
from ..db import get_db
from ..events import emit
from ..models import (AnonymousIdentity, DiscoverSession, Outcome,
                      RecommendationItem, RecommendationSet)

router = APIRouter(prefix="/v1")

# ---- simple in-memory rate limiting (Redis-backed in production deployments) ----
_buckets: dict[str, list[float]] = {}


def _rate_limit(key: str, limit: int, window: float = 60.0) -> None:
    now = time.time()
    bucket = [t for t in _buckets.get(key, []) if now - t < window]
    if len(bucket) >= limit:
        raise HTTPException(429, "rate limited")
    bucket.append(now)
    _buckets[key] = bucket


class CreateSession(BaseModel):
    sessionId: str | None = None


class SubmitResponse(BaseModel):
    interactionId: str = Field(min_length=8, max_length=64)
    response: dict = Field(default_factory=dict)
    elapsedMs: int | None = None


class Advance(BaseModel):
    to: str


class OutcomeIn(BaseModel):
    sessionId: str | None = None
    opportunityId: str | None = None
    kind: str = Field(max_length=40)
    payload: dict = Field(default_factory=dict)


def _get_session(db: Session, session_id: str) -> DiscoverSession:
    session = db.get(DiscoverSession, session_id)
    if not session:
        raise HTTPException(404, "unknown session")
    return session


@router.post("/discover/sessions")
def create_or_resume(body: CreateSession, request: Request, db: Session = Depends(get_db)):
    _rate_limit(f"sess:{request.client.host if request.client else 'x'}", 30)
    session = db.get(DiscoverSession, body.sessionId) if body.sessionId else None
    if not session:
        anon = AnonymousIdentity()
        db.add(anon)
        db.flush()
        session = DiscoverSession(anon_id=anon.id, **orchestrator.new_session_defaults())
        db.add(session)
        db.flush()
        emit(db, session.id, "discover.started", {})
    step = orchestrator.next_step(db, session)
    db.commit()
    return {"sessionId": session.id, **step}


@router.get("/discover/sessions/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)):
    s = _get_session(db, session_id)
    return {"sessionId": s.id, "state": s.journey_status,
            "createdAt": s.created_at.isoformat(), "updatedAt": s.updated_at.isoformat()}


@router.get("/discover/sessions/{session_id}/next")
def get_next(session_id: str, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    step = orchestrator.next_step(db, session)
    db.commit()
    return {"sessionId": session.id, **step}


@router.post("/discover/sessions/{session_id}/responses")
def submit(session_id: str, body: SubmitResponse, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    result = orchestrator.submit_response(db, session, body.interactionId, body.response, body.elapsedMs)
    if not result.get("ok"):
        db.rollback()
        session = _get_session(db, session_id)
        step = orchestrator.next_step(db, session)  # safely re-serve current step
        db.commit()
        return {"sessionId": session.id, "stale": True, **step}
    step = orchestrator.next_step(db, session)
    db.commit()
    return {"sessionId": session.id, **step}


@router.post("/discover/sessions/{session_id}/advance")
def advance(session_id: str, body: Advance, db: Session = Depends(get_db)):
    """Acknowledge a server-offered transition (chapter cinematics live on the client;
    validity lives here). Illegal jumps are rejected."""
    session = _get_session(db, session_id)
    try:
        orchestrator.acknowledge_transition(db, session, body.to)
    except statemachine.InvalidTransition as e:
        raise HTTPException(409, str(e))
    step = orchestrator.next_step(db, session)
    db.commit()
    return {"sessionId": session.id, **step}


@router.get("/discover/sessions/{session_id}/profile")
def profile(session_id: str, db: Session = Depends(get_db)):
    """The user's own mirror — transparency and correction rights."""
    s = _get_session(db, session_id)
    dims = {k: {"estimate": round(v.get("estimate", 0), 2), "confidence": round(v.get("confidence", 0), 2),
                "evidence": v.get("evidence_count", 0)}
            for k, v in (s.dimensions or {}).items()}
    return {"state": s.journey_status, "dimensions": dims,
            "contradictions": s.contradictions, "practicalContext":
                {k: v for k, v in (s.practical_context or {}).items() if not k.startswith("_")}}


@router.delete("/discover/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    """Privacy: the user can delete their session and profile data."""
    s = _get_session(db, session_id)
    for table in ("signal_evidence", "responses", "interaction_instances", "reveals",
                  "calibration_feedback", "profile_versions", "user_corrections",
                  "policy_decisions", "events", "recommendation_sets"):
        db.execute(__import__("sqlalchemy").text(f"DELETE FROM {table} WHERE session_id = :sid"), {"sid": s.id})
    db.delete(s)
    db.commit()
    return {"deleted": True}


@router.post("/opportunities/{opportunity_id}/explore")
def explore(opportunity_id: str, body: CreateSession, db: Session = Depends(get_db)):
    return _mark(db, opportunity_id, body.sessionId, "explored")


@router.post("/opportunities/{opportunity_id}/save")
def save(opportunity_id: str, body: CreateSession, db: Session = Depends(get_db)):
    return _mark(db, opportunity_id, body.sessionId, "saved")


def _mark(db, opportunity_id, session_id, field):
    if not session_id:
        raise HTTPException(400, "sessionId required")
    item = (db.query(RecommendationItem)
            .join(RecommendationSet, RecommendationItem.set_id == RecommendationSet.id)
            .filter(RecommendationSet.session_id == session_id,
                    RecommendationItem.opportunity_id == opportunity_id).first())
    if not item:
        raise HTTPException(404, "not recommended to this session")
    setattr(item, field, True)
    emit(db, session_id, f"opportunity.{field}", {"opportunity": opportunity_id})
    db.commit()
    return {"ok": True}


@router.post("/discover/sessions/{session_id}/activate")
def activate(session_id: str, body: dict, db: Session = Depends(get_db)):
    """Record a chosen path from the workspace. The workspace persists — no state change."""
    session = _get_session(db, session_id)
    if session.journey_status != "DISCOVER_WORKSPACE":
        raise HTTPException(409, "the story must complete before activation")
    emit(db, session_id, "path.selected", {"action": body.get("action"), "opportunity": body.get("opportunityId")})
    if body.get("opportunityId"):
        db.add(Outcome(session_id=session_id, opportunity_id=body["opportunityId"],
                       kind="path_started", payload={"action": body.get("action")}))
    db.commit()
    return {"ok": True, "state": session.journey_status}


@router.get("/workspace/{session_id}")
def workspace(session_id: str, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    if session.journey_status != "DISCOVER_WORKSPACE":
        raise HTTPException(409, "workspace opens after the story completes")
    from ..workspace import workspace_summary
    out = workspace_summary(db, session)
    db.commit()
    return {"sessionId": session.id, **out}


@router.post("/workspace/{session_id}/questions/next")
def next_question(session_id: str, db: Session = Depends(get_db)):
    """Serve the single highest-value adaptive question (never a form)."""
    session = _get_session(db, session_id)
    if session.journey_status != "DISCOVER_WORKSPACE":
        raise HTTPException(409, "workspace opens after the story completes")
    from ..workspace import pending_questions
    from ..orchestrator import _instance, _public_content
    pending = pending_questions(session, 1)
    if not pending:
        from ..workspace import workspace_summary
        out = workspace_summary(db, session)
        db.commit()
        return {"sessionId": session.id, "interaction": out, "state": session.journey_status}
    q = pending[0]
    definition = {"id": q["id"], "type": q["type"], "content": q["content"],
                  "practical_key": q["practical_key"]}
    public = _public_content(definition)
    inst = _instance(db, session, q["id"], q["type"], q["content"], public, None)
    db.commit()
    return {"sessionId": session.id, "interaction": inst.public_content, "state": session.journey_status}


@router.get("/workspace/{session_id}/actions/{action_id}")
def action_detail(session_id: str, action_id: str, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    if session.journey_status != "DISCOVER_WORKSPACE":
        raise HTTPException(409, "workspace opens after the story completes")
    from ..workspace import action_content
    out = action_content(db, session, action_id)
    emit(db, session_id, "workspace.action_opened", {"action": action_id})
    db.commit()
    return {"sessionId": session.id, **out}


@router.post("/outcomes")
def report_outcome(body: OutcomeIn, request: Request, db: Session = Depends(get_db)):
    _rate_limit(f"out:{request.client.host if request.client else 'x'}", 20)
    db.add(Outcome(session_id=body.sessionId, opportunity_id=body.opportunityId,
                   kind=body.kind, payload=body.payload))
    emit(db, body.sessionId, "outcome.reported", {"kind": body.kind})
    db.commit()
    return {"ok": True}
