"""Versioned public API. The server owns authoritative journey progression."""
from __future__ import annotations

import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import orchestrator, statemachine
from ..config import settings
from ..db import get_db
from ..events import emit
from ..models import (AnonymousIdentity, DiscoverSession, InteractionInstance,
                      Outcome, RecommendationItem, RecommendationSet)

router = APIRouter(prefix="/v1")

# ---- simple in-memory rate limiting (Redis-backed in production deployments) ----
_buckets: dict[str, list[float]] = {}


def _rate_limit(key: str, limit: int, window: float = 60.0) -> None:
    from ..config import settings
    if settings.app_env == "test":
        return   # abuse protection, not a test constraint — the whole suite is one host
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
    """Idempotent: a retried or duplicated submission for an already-answered
    interaction re-serves the current step instead of double-counting evidence,
    advancing the chapter twice, or creating a second next interaction."""
    from .. import latency
    timer = latency.PhaseTimer()
    session = _get_session(db, session_id)
    with timer.phase("persist"):
        result = orchestrator.submit_response(db, session, body.interactionId,
                                              body.response, body.elapsedMs)
    if not result.get("ok"):
        db.rollback()
        session = _get_session(db, session_id)
        with timer.phase("policy"):
            step = orchestrator.next_step(db, session)   # safely re-serve current step
        latency.record(db, session_id, "response", timer, {"duplicate": True})
        db.commit()
        return {"sessionId": session.id, "duplicate": True, "stale": True, **step}
    with timer.phase("policy"):
        step = orchestrator.next_step(db, session)
    latency.record(db, session_id, "response", timer,
                   {"type": step.get("interaction", {}).get("type")})
    db.commit()
    out = {"sessionId": session.id, **step}
    if not settings.is_production:
        out["timings"] = {"phases": timer.phases, "totalMs": timer.total_ms(),
                          "overBudget": timer.over_budget()}
    return out


@router.post("/discover/sessions/{session_id}/interactions/{instance_id}/help")
def get_decision_help(session_id: str, instance_id: str, db: Session = Depends(get_db)):
    """Real help for someone stuck on a question — a concrete moment and what
    each option costs in it. There is deliberately no skip beside this: the way
    out of a hard choice is making it, and a choice made from a clear picture is
    better evidence than one made from fatigue."""
    session = _get_session(db, session_id)
    inst = db.get(InteractionInstance, instance_id)
    if not inst or inst.session_id != session.id:
        raise HTTPException(404, "unknown interaction")
    from .. import decision_help
    out = decision_help.build(db, session, inst)
    emit(db, session_id, "assist.help_shown",
         {"interaction": inst.type, "source": out.get("source")})
    db.commit()
    return out


@router.post("/discover/sessions/{session_id}/advance")
def advance(session_id: str, body: Advance, db: Session = Depends(get_db)):
    """Acknowledge a server-offered transition (chapter cinematics live on the client;
    validity lives here). Illegal jumps are rejected."""
    session = _get_session(db, session_id)
    try:
        orchestrator.acknowledge_transition(db, session, body.to)
    except statemachine.InvalidTransition as e:
        raise HTTPException(409, str(e))
    # The journey is free and anonymous; the audit is where a name attaches.
    # Entering the persistent workspace without an owner would strand the data.
    # Raised after validation so illegal jumps still read as 409, and before
    # commit so the state change is discarded along with the refusal.
    if body.to == "DISCOVER_WORKSPACE" and not _session_owner(db, session):
        raise HTTPException(401, "sign in to keep your audit")
    step = orchestrator.next_step(db, session)
    db.commit()
    return {"sessionId": session.id, **step}


# ---------------- accounts: the audit belongs to someone ----------------

class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class GoogleIn(BaseModel):
    credential: str = Field(min_length=20, max_length=4096)


class ClaimIn(BaseModel):
    sessionId: str = Field(min_length=8, max_length=64)


def _session_owner(db: Session, session: DiscoverSession):
    from ..models import User
    anon = db.get(AnonymousIdentity, session.anon_id)
    return db.get(User, anon.user_id) if anon and anon.user_id else None


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else None


def _require_user(request: Request, db: Session):
    from .. import auth
    user = auth.user_for_token(db, _bearer(request))
    if not user:
        raise HTTPException(401, "not signed in")
    return user


@router.get("/auth/config")
def auth_config():
    """What the client needs to draw the right buttons — never secrets."""
    return {"googleClientId": settings.google_client_id or None}


@router.post("/auth/signup")
def signup(body: SignupIn, request: Request, db: Session = Depends(get_db)):
    from .. import auth
    from ..models import User
    _rate_limit(f"auth:{request.client.host if request.client else 'x'}", 20)
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "that doesn't look like an email")
    if auth.user_by_email(db, email):
        raise HTTPException(409, "an account with this email already exists")
    user = User(email=email, name=body.name.strip(),
                password_hash=auth.hash_password(body.password))
    db.add(user)
    db.flush()
    token = auth.issue_token(db, user)
    db.commit()
    return {"token": token, "user": auth.public_user(user)}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    from .. import auth
    _rate_limit(f"auth:{request.client.host if request.client else 'x'}", 20)
    user = auth.user_by_email(db, body.email)
    if not user or not auth.verify_password(body.password, user.password_hash):
        raise HTTPException(401, "email or password doesn't match")
    token = auth.issue_token(db, user)
    db.commit()
    return {"token": token, "user": auth.public_user(user)}


@router.post("/auth/google")
def google_auth(body: GoogleIn, request: Request, db: Session = Depends(get_db)):
    from .. import auth
    from ..models import User
    _rate_limit(f"auth:{request.client.host if request.client else 'x'}", 20)
    claims = auth.verify_google_credential(body.credential)
    if not claims:
        raise HTTPException(401, "Google sign-in could not be verified")
    email = (claims.get("email") or "").lower()
    user = auth.user_by_email(db, email) if email else None
    if not user:
        user = User(email=email or None, name=claims.get("name"),
                    google_sub=claims.get("sub"))
        db.add(user)
        db.flush()
    elif not user.google_sub:
        user.google_sub = claims.get("sub")
        user.name = user.name or claims.get("name")
    token = auth.issue_token(db, user)
    db.commit()
    return {"token": token, "user": auth.public_user(user)}


@router.get("/auth/me")
def me(request: Request, db: Session = Depends(get_db)):
    from .. import auth
    user = _require_user(request, db)
    latest = auth.latest_audit_session(db, user)
    return {"user": auth.public_user(user),
            "auditSessionId": latest.id if latest else None}


@router.post("/auth/claim")
def claim(body: ClaimIn, request: Request, db: Session = Depends(get_db)):
    """Attach a journey to the signed-in person. Idempotent; a session already
    owned by someone else cannot be quietly re-owned."""
    from .. import auth
    user = _require_user(request, db)
    session = _get_session(db, body.sessionId)
    owner = _session_owner(db, session)
    if owner and owner.id != user.id:
        raise HTTPException(409, "this journey already belongs to another account")
    auth.claim_session(db, session, user)
    emit(db, session.id, "session.claimed", {"user": user.id})
    db.commit()
    return {"ok": True, "user": auth.public_user(user)}


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


@router.get("/debug/sessions/{session_id}/decision")
def debug_decision(session_id: str, db: Session = Depends(get_db)):
    """Development-only decision inspector. Never exposed in production."""
    from ..config import settings
    from ..models import PolicyDecision
    if settings.is_production:
        raise HTTPException(404, "not found")
    session = _get_session(db, session_id)
    d = (db.query(PolicyDecision).filter_by(session_id=session_id)
         .order_by(PolicyDecision.created_at.desc()).first())
    dims = session.dimensions or {}
    return {
        "state": session.journey_status,
        "knownFacts": {k: v for k, v in (session.practical_context or {}).items() if not k.startswith("_")},
        "topUncertainties": sorted(((k, round(1 - v.get("confidence", 0), 2)) for k, v in dims.items()),
                                   key=lambda x: -x[1])[:5],
        "ineligible": (session.counters or {}).get("_last_rejected", {}),
        "eligibleActions": d.eligible_actions if d else [],
        "actionValues": d.action_values if d else {},
        "chosenAction": d.chosen_action if d else None,
        "propensity": d.propensity if d else None,
        "policyVersion": d.policy_version if d else None,
    }


@router.post("/outcomes")
def report_outcome(body: OutcomeIn, request: Request, db: Session = Depends(get_db)):
    _rate_limit(f"out:{request.client.host if request.client else 'x'}", 20)
    db.add(Outcome(session_id=body.sessionId, opportunity_id=body.opportunityId,
                   kind=body.kind, payload=body.payload))
    emit(db, body.sessionId, "outcome.reported", {"kind": body.kind})
    db.commit()
    return {"ok": True}


class ResonanceFeedback(BaseModel):
    figureId: str = Field(max_length=60)
    patternId: str | None = None
    verdict: str = Field(pattern="^(see_it|not_sure|not_relevant)$")


@router.post("/discover/sessions/{session_id}/resonance/feedback")
def resonance_feedback(session_id: str, body: ResonanceFeedback, db: Session = Depends(get_db)):
    """The user may challenge a match. Disagreement is training signal, not
    error: a rejected resonance is suppressed until the evidence materially
    changes, and feeds future ranking training data."""
    session = _get_session(db, session_id)
    from ..resonance import record_feedback
    record_feedback(db, session, body.figureId, body.patternId, body.verdict, session.journey_status)
    emit(db, session_id, "resonance.feedback", {"figure": body.figureId, "verdict": body.verdict})
    db.commit()
    return {"ok": True}


@router.get("/debug/sessions/{session_id}/story")
def debug_story(session_id: str, db: Session = Depends(get_db)):
    """Development-only Story Inspector — the tool for debugging repetition."""
    from ..config import settings
    if settings.is_production:
        raise HTTPException(404, "not found")
    session = _get_session(db, session_id)
    from ..models import NarrativeSessionState, ResonanceSnapshot
    st = db.get(NarrativeSessionState, session_id)
    snap = (db.query(ResonanceSnapshot).filter_by(session_id=session_id)
            .order_by(ResonanceSnapshot.created_at.desc()).first())
    if not st:
        return {"narrativeState": None}
    threads = st.threads or []
    return {
        "narrativeState": {
            "chapter": st.chapter, "emotionalPhase": st.emotional_phase,
            "nextNarrativeIntent": st.next_narrative_intent,
            "closingStyleHistory": st.chapter_closing_style_history,
            "surprisesShown": st.surprises_shown,
        },
        "threadsOpened": [t for t in threads if t["status"] in ("opened", "developing")],
        "threadsResolved": [t for t in threads if t["status"] in ("resolved", "contradicted", "abandoned")],
        "previousStoryBeats": st.story_beats_shown,
        "recentCopy": st.recent_copy,
        "repetitionScores": {
            "openings": st.sentence_openings_used, "shapes": st.sentence_shapes_used,
            "tics": st.tics_used, "metaphors": st.metaphors_used,
        },
        "rejectedCopy": st.rejected_copy_log,
        "publicFigureCandidates": (snap.candidates_considered if snap else []),
        "matchEvidence": (snap.matches if snap else []),
    }


@router.get("/debug/sessions/{session_id}/intelligence")
def debug_intelligence(session_id: str, db: Session = Depends(get_db)):
    """Development-only Intelligence Inspector (PART 65): what the system
    believes, why, what it refused to conclude, and what it plans to do."""
    from ..config import settings
    if settings.is_production:
        raise HTTPException(404, "not found")
    session = _get_session(db, session_id)
    from ..models import (AmbiguityRecord, ChapterClosingPlan, EvidenceItem,
                          Hypothesis, InferenceFeedback, NarrativeEvent,
                          PolicyDecision, Response)
    from ..knowledge import overinterpretation_risk, role_analysis_allowed
    from .. import thresholds as _th
    latest_response = (db.query(Response).filter_by(session_id=session_id)
                       .order_by(Response.created_at.desc()).first())
    decision = (db.query(PolicyDecision).filter_by(session_id=session_id)
                .order_by(PolicyDecision.created_at.desc()).first())
    hyps = db.query(Hypothesis).filter_by(session_id=session_id).all()
    events = (db.query(NarrativeEvent).filter_by(session_id=session_id)
              .order_by(NarrativeEvent.created_at.desc()).limit(8).all())
    plan = (db.query(ChapterClosingPlan).filter_by(session_id=session_id)
            .order_by(ChapterClosingPlan.created_at.desc()).first())
    pc = session.practical_context or {}
    dims = session.dimensions or {}
    tops = sorted(dims.items(), key=lambda kv: kv[1].get("confidence", 0), reverse=True)
    allowed, gate_reason = role_analysis_allowed(session)
    return {
        "latestUserResponse": (latest_response.payload if latest_response else None),
        "explicitAndDerivedFacts": pc.get("_facts", {}),
        "ambiguities": [{"key": a.key, "status": a.status, "value": a.clarification_value,
                         "interpretations": a.possible_interpretations}
                        for a in db.query(AmbiguityRecord).filter_by(session_id=session_id)],
        "hypotheses": [{"construct": h.construct, "direction": h.direction,
                        "confidence": h.confidence, "status": h.status, "version": h.version,
                        "supportingEvidence": len(h.supporting_evidence_ids or []),
                        "contradictingEvidence": len(h.contradicting_evidence_ids or [])}
                       for h in sorted(hyps, key=lambda x: -x.confidence)],
        "invalidatedHypotheses": [h.construct for h in hyps if h.status in ("corrected", "contradicted")],
        "recentHypothesisChanges": (session.counters or {}).get("_last_hypothesis_changes", []),
        "topUncertainties": [{"dim": k, "confidence": round(v.get("confidence", 0), 2)}
                             for k, v in sorted(dims.items(), key=lambda kv: kv[1].get("confidence", 0))[:5]],
        "candidateActions": (decision.eligible_actions if decision else []),
        "actionValues": (decision.action_values if decision else {}),
        "selectedAction": (decision.chosen_action if decision else None),
        "rejectedInteractions": (session.counters or {}).get("_last_rejected", {}),
        "overinterpretationRisk": overinterpretation_risk(
            0.7, tops[0][1].get("confidence", 0) if tops else 0.0),
        "roleAnalysisGate": {"allowed": allowed, "reason": gate_reason},
        "recentStoryEvents": [{"type": e.type, "importance": e.importance,
                               "consumed": bool(e.consumed_by_closing)} for e in events],
        "lastClosingPlan": ({"structure": plan.selected_structure, "why": plan.why_this_closing,
                             "whatChanged": plan.what_changed,
                             "availableEvents": plan.available_events} if plan else None),
        "evidenceLedgerSize": db.query(EvidenceItem).filter_by(session_id=session_id).count(),
        "inferenceFeedback": db.query(InferenceFeedback).filter_by(session_id=session_id).count(),
        "thresholdsVersion": _th.THRESHOLDS_VERSION,
    }


# ---------------- world intelligence: internal + evidence endpoints ----------------

def _internal_guard(request: Request) -> None:
    """Internal ops endpoints. SESSION_SECRET is optional for local work, but
    an unset secret must never leave these open on a reachable deployment —
    without it we only serve loopback callers."""
    from ..config import settings
    token = request.headers.get("X-Internal-Token", "")
    configured = bool(os.environ.get("SESSION_SECRET"))
    if not configured:
        host = request.client.host if request.client else ""
        if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
            raise HTTPException(403, "set SESSION_SECRET to use internal endpoints remotely")
        return
    if not token or token != settings.session_secret:
        raise HTTPException(403, "internal endpoint")


@router.post("/internal/intelligence/sources/{source_id}/refresh")
def refresh_source(source_id: str, request: Request, db: Session = Depends(get_db)):
    _internal_guard(request)
    from ..models import WISource
    from ..world import ingestion
    from ..world.signals import recompute_signals
    from ..world.sources import ingestible
    source = db.get(WISource, source_id)
    if not source:
        raise HTTPException(404, "unknown source")
    ok, why = ingestible(source)
    if not ok:
        raise HTTPException(409, f"source not ingestible: {why}")
    if source_id == "src_seed_taxonomy":
        ingestion.seed_ontology(db)
    elif source_id == "src_seed_labor_stats":
        ingestion.seed_baseline_signals(db)
    version = recompute_signals(db)
    db.commit()
    return {"ok": True, "marketSnapshotVersion": version}


@router.post("/internal/intelligence/apify/webhook")
async def apify_webhook(request: Request, db: Session = Depends(get_db)):
    """Acknowledge-and-queue. Signature AND run provenance are validated, and
    large dataset normalization happens in a worker, never in this request."""
    import json as _json
    from ..world import apify_gateway, jobs
    body = await request.body()
    if not apify_gateway.verify_webhook(body, request.headers.get("X-Apify-Webhook-Signature")):
        raise HTTPException(403, "invalid webhook signature")
    try:
        payload = _json.loads(body or b"{}")
    except ValueError:
        raise HTTPException(400, "malformed payload")
    validation = apify_gateway.validate_run_event(db, payload)
    if not validation.get("ok"):
        raise HTTPException(409, validation.get("error", "run not recognized"))
    source_run = validation["job"]
    scope = dict(source_run.scope or {})
    if validation.get("status") not in (None, "SUCCEEDED"):
        jobs.fail(db, source_run, f"apify run {validation.get('status')}")
        db.commit()
        return {"ok": True, "queued": False, "runStatus": validation.get("status")}
    normalize = jobs.enqueue(db, "normalize_dataset",
                             scope={**scope, "datasetId": validation.get("datasetId")},
                             scope_hash=source_run.scope_hash, priority=40, dedupe=False)
    db.commit()
    return {"ok": True, "queued": True, "jobId": normalize.id}


@router.get("/internal/intelligence/runs")
def ingestion_runs(request: Request, db: Session = Depends(get_db)):
    _internal_guard(request)
    from ..models import WIIngestionRun
    runs = (db.query(WIIngestionRun).order_by(WIIngestionRun.started_at.desc()).limit(30).all())
    return {"runs": [{"id": r.id, "source": r.source_id, "status": r.status,
                      "records": r.record_count, "deduplicated": r.deduplicated_count,
                      "validationFailures": r.validation_failures, "quality": r.quality,
                      "startedAt": r.started_at.isoformat(), "error": r.error} for r in runs]}


@router.get("/opportunities/{opportunity_id}/evidence")
def opportunity_evidence(opportunity_id: str, sessionId: str, db: Session = Depends(get_db)):
    """'Why are you saying this?' — full provenance for one recommendation:
    claim → factors → market signal → observations → source."""
    from ..models import (Opportunity, RecommendationItem, RecommendationSet,
                          WIMarketSignal, WISource, WISourceObservation)
    item = (db.query(RecommendationItem)
            .join(RecommendationSet, RecommendationItem.set_id == RecommendationSet.id)
            .filter(RecommendationSet.session_id == sessionId,
                    RecommendationItem.opportunity_id == opportunity_id)
            .order_by(RecommendationItem.rank).first())
    if not item:
        raise HTTPException(404, "not recommended to this session")
    opp = db.get(Opportunity, opportunity_id)
    occ_id = None
    if opportunity_id.startswith("world_"):
        occ_id = opportunity_id[len("world_"):].rsplit("_", 1)[0]
    sigs = (db.query(WIMarketSignal).filter_by(occupation_id=occ_id).all() if occ_id else [])
    evidence = []
    for sig in sigs:
        obs_rows = [db.get(WISourceObservation, oid) for oid in (sig.evidence_refs or [])[:5]]
        evidence.append({
            "construct": sig.construct, "value": sig.value, "confidence": sig.confidence,
            "geography": sig.geography, "sourceCount": sig.source_count,
            "sourceDiversity": sig.source_diversity, "conflicts": sig.conflicts,
            "snapshotVersion": sig.snapshot_version,
            "updatedAt": sig.updated_at.isoformat(),
            "observations": [{"source": (db.get(WISource, o.source_id).name
                                         if o and db.get(WISource, o.source_id) else o.source_id if o else None),
                              "signalType": o.signal_type if o else None,
                              "observedAt": o.observed_at.isoformat() if o else None}
                             for o in obs_rows if o],
        })
    return {"opportunity": opp.title if opp else opportunity_id,
            "rankingFactors": item.factor_contributions,
            "narrative": item.narrative, "marketEvidence": evidence}


# ---------------- materialization: material objects, experiments, routes ----------------

class ObjectStatus(BaseModel):
    kind: str = Field(pattern="^(capability|leverage|gap|direction|experiment|insight|question)$")
    key: str = Field(max_length=120)
    status: str = Field(pattern="^(new|exploring|saved|testing|active|dismissed|completed)$")
    reason: str | None = Field(default=None, max_length=200)


class ExperimentOutcome(BaseModel):
    verdict: str = Field(pattern="^(promising|mixed|not_for_me)$")
    note: str | None = Field(default=None, max_length=400)
    earned: bool | None = None
    continuing: bool | None = None


@router.get("/discover/sessions/{session_id}/materialization")
def get_materialization(session_id: str, db: Session = Depends(get_db)):
    """The material picture. Available from MATERIALIZATION onward — it stays
    reachable from the workspace, since these objects persist."""
    session = _get_session(db, session_id)
    if session.journey_status not in ("MATERIALIZATION", "DISCOVER_WORKSPACE"):
        raise HTTPException(409, "materialization opens after the story completes")
    from .. import content_build, materialization
    cached = content_build.fresh((session.practical_context or {}).get("_materialization"))
    payload = cached or materialization.build(db, session)
    if not cached:
        pc = dict(session.practical_context or {})
        pc["_materialization"] = content_build.stamped(payload)
        session.practical_context = pc
    db.commit()
    return {"sessionId": session.id, **payload}


class SituationAnswer(BaseModel):
    key: str = Field(max_length=40)
    optionId: str = Field(max_length=40)
    label: str | None = Field(default=None, max_length=80)
    question: str | None = Field(default=None, max_length=200)


@router.post("/discover/sessions/{session_id}/situation")
def answer_situation(session_id: str, body: SituationAnswer, db: Session = Depends(get_db)):
    """One answer to the model-chosen follow-up, and the next question if there
    is one worth asking."""
    session = _get_session(db, session_id)
    from .. import situation
    if not situation.save_answer(db, session, body.key, body.optionId,
                                 body.label, body.question).get("ok"):
        raise HTTPException(400, "bad answer")
    nxt = situation.next_question(db, session)
    emit(db, session_id, "situation.answered", {"key": body.key, "option": body.optionId})
    db.commit()
    return {"ok": True, "next": nxt}


class DirectionChoice(BaseModel):
    optionId: str = Field(max_length=20)


@router.get("/discover/sessions/{session_id}/insights")
def get_insights(session_id: str, db: Session = Depends(get_db)):
    """The ten things worth knowing about this person's field, ordered by the
    branch they picked. Insights we have no data for are returned as explicitly
    unavailable rather than omitted — someone deciding whether to leave a job
    needs to know which half of the picture is missing."""
    session = _get_session(db, session_id)
    from .. import insights
    out = insights.top_insights(db, session, insights.current_intent(session))
    out["question"] = insights.DIRECTION_QUESTION if not insights.current_intent(session) else None
    db.commit()
    return out


@router.post("/discover/sessions/{session_id}/insights/direction")
def set_direction(session_id: str, body: DirectionChoice, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    from .. import insights
    if not insights.save_direction(db, session, body.optionId):
        raise HTTPException(400, "unknown direction")
    # the ordering changed, so any cached page is stale
    pc = dict(session.practical_context or {})
    pc.pop("_materialization", None)
    session.practical_context = pc
    emit(db, session_id, "insights.direction", {"intent": body.optionId})
    out = insights.top_insights(db, session, insights.current_intent(session))
    db.commit()
    return out


class ProbeAnswer(BaseModel):
    stepId: str = Field(max_length=40)
    optionId: str = Field(max_length=40)


@router.post("/discover/sessions/{session_id}/venture/probe")
def answer_venture_probe(session_id: str, body: ProbeAnswer, db: Session = Depends(get_db)):
    """One answer from the operator probe — the follow-up questions behind
    "Explore something interesting for you". Each answer is stored as an
    explicit fact and immediately re-routes the surfaces, so the questions
    visibly do something rather than feeding a form."""
    session = _get_session(db, session_id)
    from .. import venture
    if not venture.is_operator(session):
        raise HTTPException(409, "the venture probe is for people already running something")
    result = venture.save_probe(db, session, body.stepId, body.optionId)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "bad probe answer"))
    answers = result["answers"]
    from .. import materialization
    caps = materialization.capability_map(db, session)
    surfaces = venture.surfaces_for(db, session, answers, [c["key"] for c in caps])
    # the cached materialization payload is now stale
    pc = dict(session.practical_context or {})
    pc.pop("_materialization", None)
    session.practical_context = pc
    emit(db, session_id, "venture.probe_answered",
         {"step": body.stepId, "option": body.optionId})
    db.commit()
    return {"ok": True, "answers": answers, "next": result["next"],
            "read": venture.probe_read(answers), "surfaces": surfaces,
            "complete": result["next"] is None}


@router.post("/discover/sessions/{session_id}/objects/status")
def set_object_status(session_id: str, body: ObjectStatus, db: Session = Depends(get_db)):
    """Save, dismiss, or advance any material object. Dismissal is ranking
    feedback — the user is never told the model knows better."""
    session = _get_session(db, session_id)
    from .. import materialization
    row = materialization.set_status(db, session, body.kind, body.key, body.status, body.reason)
    if not row:
        raise HTTPException(404, "unknown object")
    emit(db, session_id, "material.status", {"kind": body.kind, "key": body.key,
                                             "status": body.status})
    if body.status == "dismissed":
        # a dismissed direction must not silently persist in cached payloads
        pc = dict(session.practical_context or {})
        pc.pop("_materialization", None)
        pc.pop("_lives", None)
        session.practical_context = pc
    db.commit()
    return {"ok": True, "status": row.status, "saved": row.saved}


@router.get("/discover/sessions/{session_id}/saved")
def get_saved(session_id: str, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    from .. import materialization
    return {"saved": materialization.saved_objects(db, session)}


@router.post("/discover/sessions/{session_id}/experiments/{direction_key}/start")
def start_experiment(session_id: str, direction_key: str, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    from .. import experiments, materialization
    from ..models import MaterialObject
    obj = (db.query(MaterialObject)
           .filter_by(session_id=session.id, kind="direction", key=direction_key).first())
    if not obj:
        raise HTTPException(404, "unknown direction")
    spec = (obj.detail or {}).get("experiment") or experiments.generate(session, obj.detail or {})
    run = experiments.persist(db, session, direction_key, spec, obj.id)
    materialization.set_status(db, session, "direction", direction_key, "testing")
    emit(db, session_id, "experiment.started", {"direction": direction_key})
    db.commit()
    return {"ok": True, "experimentId": run.id, "action": run.action, "teaches": run.teaches}


@router.post("/discover/sessions/{session_id}/experiments/{experiment_id}/outcome")
def report_experiment_outcome(session_id: str, experiment_id: str, body: ExperimentOutcome,
                              db: Session = Depends(get_db)):
    """Outcomes are the strongest evidence the system ever receives — much
    stronger than early questionnaire answers."""
    session = _get_session(db, session_id)
    from datetime import datetime
    from .. import knowledge, materialization
    from ..models import ExperimentRun, Outcome
    run = db.get(ExperimentRun, experiment_id)
    if not run or run.session_id != session.id:
        raise HTTPException(404, "unknown experiment")
    run.status = "completed"
    run.completed_at = datetime.utcnow()
    run.outcome = body.model_dump()
    knowledge.record_evidence(db, session, "outcome",
                              f"ran experiment '{run.action[:80]}' → {body.verdict}"
                              + (f": {body.note}" if body.note else ""),
                              strength=1.0)
    knowledge.sync_hypotheses(db, session, trigger=f"experiment_outcome:{body.verdict}")
    db.add(Outcome(session_id=session.id, opportunity_id=run.direction_key,
                   kind="experiment_outcome", payload=body.model_dump()))
    materialization.set_status(db, session, "direction", run.direction_key,
                               "active" if body.verdict == "promising" else
                               ("dismissed" if body.verdict == "not_for_me" else "exploring"),
                               reason=(body.note if body.verdict == "not_for_me" else None))
    pc = dict(session.practical_context or {})
    pc.pop("_materialization", None)   # the picture changes when reality answers
    pc.pop("_lives", None)
    session.practical_context = pc
    emit(db, session_id, "experiment.outcome", {"verdict": body.verdict})
    db.commit()
    return {"ok": True}


@router.post("/discover/sessions/{session_id}/product-routes/{route_id}/accept")
def accept_product_route(session_id: str, route_id: str, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    from .. import products
    if not products.accept(db, session, route_id):
        raise HTTPException(404, "unknown route")
    emit(db, session_id, "product.route_accepted", {"route": route_id})
    db.commit()
    return {"ok": True}


# ---------------- real-time analysis: computed at request time ----------------

class AnalyzeRequest(BaseModel):
    sessionId: str = Field(min_length=8, max_length=64)
    action: str = Field(max_length=60)
    intent: dict = Field(default_factory=dict)
    refreshPreference: str = Field(default="live_if_needed",
                                   pattern="^(live_if_needed|never|force)$")
    geography: str | None = Field(default=None, max_length=60)


@router.post("/discover/actions/analyze")
def analyze_action(body: AnalyzeRequest, db: Session = Depends(get_db)):
    """The real-time recommendation pipeline. Loads the LATEST human state,
    checks the freshness of exactly the signals this action needs, triggers a
    targeted refresh only when warranted, ranks now, and records the versions
    that produced the answer."""
    session = _get_session(db, body.sessionId)
    if session.journey_status not in ("MATERIALIZATION", "DISCOVER_WORKSPACE"):
        raise HTTPException(409, "analysis opens after the story completes")
    from ..world.analysis import analyze
    out = analyze(db, session, body.action, body.intent,
                  body.refreshPreference, body.geography)
    emit(db, session.id, "analysis.generated",
         {"action": body.action, "status": out["status"],
          "freshness": out["marketFreshness"]["state"]})
    db.commit()
    return out


@router.get("/intelligence/refresh/{job_id}")
def refresh_status(job_id: str, sessionId: str | None = None, db: Session = Depends(get_db)):
    """Poll a targeted refresh. When it completes, the caller re-runs the
    analysis — new observations produce a NEW analysis version, never an
    in-place edit of the old conclusion."""
    from ..world import jobs
    state = jobs.status(db, job_id)
    if not state:
        raise HTTPException(404, "unknown refresh")
    out = {"refresh": state}
    if state["status"] == "completed" and sessionId:
        session = db.get(DiscoverSession, sessionId)
        if session:
            from ..world.analysis import rerun_after_refresh
            action = (state.get("scope") or {}).get("action") or "explore_opportunities"
            out["analysis"] = rerun_after_refresh(db, session, action)
            db.commit()
    return out


@router.get("/internal/intelligence/health")
def intelligence_health(request: Request, db: Session = Depends(get_db)):
    """Source health, job queue depth and domain coverage demand."""
    _internal_guard(request)
    from ..models import (DomainEnrichmentRequest, IntelligenceJob,
                          IntelligenceScopeCache, SourceHealth)
    from sqlalchemy import func
    queue = dict(db.query(IntelligenceJob.status, func.count(IntelligenceJob.id))
                 .group_by(IntelligenceJob.status).all())
    return {
        "jobQueue": queue,
        "sources": [{"id": h.source_id, "lastSuccess": h.last_success.isoformat() if h.last_success else None,
                     "failures": h.failure_count, "records": h.latest_record_count,
                     "runs": h.total_runs, "costUsd": h.total_cost_usd,
                     "usefulObservations": h.useful_observations}
                    for h in db.query(SourceHealth).all()],
        "scopes": [{"hash": s.scope_hash, "occupation": s.occupation_id,
                    "geography": s.geography, "state": s.freshness_state,
                    "coverage": s.coverage_score}
                   for s in db.query(IntelligenceScopeCache).limit(25).all()],
        "domainDemand": [{"domain": d.domain, "geography": d.geography,
                          "requests": d.request_count, "priority": d.priority,
                          "coverage": d.current_coverage}
                         for d in db.query(DomainEnrichmentRequest)
                         .order_by(DomainEnrichmentRequest.priority.asc()).limit(15).all()],
    }


@router.get("/debug/latency")
def debug_latency(request: Request, kind: str | None = None, db: Session = Depends(get_db)):
    """p50/p75/p95/p99 per phase — so a slow experience can be attributed to a
    real phase rather than guessed at."""
    if settings.is_production:
        _internal_guard(request)
    from .. import latency
    return {"budgetsMs": latency.BUDGETS_MS,
            "response": latency.percentiles(db, "response"),
            "analysis": latency.percentiles(db, "analysis"),
            **({"filtered": latency.percentiles(db, kind)} if kind else {})}
