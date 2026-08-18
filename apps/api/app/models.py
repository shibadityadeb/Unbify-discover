"""System of record. PostgreSQL in production (DATABASE_URL); pgvector embeddings
are stored as JSON alongside an optional native vector column created by the
postgres-only migration step. Nothing here is authoritative for the LLM."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.utcnow()


# ---------- identity ----------

class AnonymousIdentity(Base):
    __tablename__ = "anonymous_identities"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Consent(Base):
    __tablename__ = "consents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    anon_id: Mapped[str] = mapped_column(ForeignKey("anonymous_identities.id"))
    kind: Mapped[str] = mapped_column(String(40))          # marketing | analytics | profile
    granted: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ---------- discovery ----------

class DiscoverSession(Base):
    __tablename__ = "discover_sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    anon_id: Mapped[str] = mapped_column(ForeignKey("anonymous_identities.id"))
    journey_status: Mapped[str] = mapped_column(String(30), default="PROLOGUE")  # state machine
    chapter_progress: Mapped[float] = mapped_column(Float, default=0.0)
    # hot denormalized human state (authoritative history lives in signal_evidence + profile_versions)
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    contradictions: Mapped[list] = mapped_column(JSON, default=list)
    practical_context: Mapped[dict] = mapped_column(JSON, default=dict)
    revealed_insights: Mapped[list] = mapped_column(JSON, default=list)
    recent_interaction_types: Mapped[list] = mapped_column(JSON, default=list)
    counters: Mapped[dict] = mapped_column(JSON, default=dict)  # since_reveal, reveals_this_chapter, reflections, per-chapter interactions
    engagement: Mapped[dict] = mapped_column(JSON, default=dict)
    used_definitions: Mapped[list] = mapped_column(JSON, default=list)
    pending_instance_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class InteractionDefinition(Base):
    __tablename__ = "interaction_definitions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)   # e.g. "vp_worlds"
    version: Mapped[int] = mapped_column(Integer, default=1)
    type: Mapped[str] = mapped_column(String(30))
    chapters: Mapped[list] = mapped_column(JSON, default=list)
    targets: Mapped[list] = mapped_column(JSON, default=list)
    cognitive_cost: Mapped[float] = mapped_column(Float, default=0.3)
    practical_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    content: Mapped[dict] = mapped_column(JSON, default=dict)       # headline, options(+signals), poles...
    source: Mapped[str] = mapped_column(String(20), default="curated")  # curated | llm
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class InteractionInstance(Base):
    __tablename__ = "interaction_instances"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    definition_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    type: Mapped[str] = mapped_column(String(30))
    chapter: Mapped[str] = mapped_column(String(30))
    content: Mapped[dict] = mapped_column(JSON, default=dict)       # full server-side content incl. hidden signals
    public_content: Mapped[dict] = mapped_column(JSON, default=dict)
    policy_decision_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | answered | skipped | stale
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Response(Base):
    __tablename__ = "responses"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    instance_id: Mapped[str] = mapped_column(ForeignKey("interaction_instances.id"), unique=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SignalEvidence(Base):
    __tablename__ = "signal_evidence"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    instance_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    response_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    construct_updates: Mapped[dict] = mapped_column(JSON, default=dict)   # {dim: delta}
    weight: Mapped[float] = mapped_column(Float, default=0.4)
    confidence: Mapped[float] = mapped_column(Float, default=0.4)
    source: Mapped[str] = mapped_column(String(40))
    signal_version: Mapped[str] = mapped_column(String(20), default="sig_v1")
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Reveal(Base):
    __tablename__ = "reveals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    lines: Mapped[list] = mapped_column(JSON, default=list)
    insight: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class CalibrationFeedback(Base):
    __tablename__ = "calibration_feedback"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    reveal_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    answer: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ---------- profile ----------

class ProfileVersion(Base):
    __tablename__ = "profile_versions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    checkpoint: Mapped[str] = mapped_column(String(40))     # early_reveal | chapter_complete:X | story_complete
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    contradictions: Mapped[list] = mapped_column(JSON, default=list)
    corrections: Mapped[list] = mapped_column(JSON, default=list)
    practical_context: Mapped[dict] = mapped_column(JSON, default=dict)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    signal_version: Mapped[str] = mapped_column(String(20), default="sig_v1")
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class UserCorrection(Base):
    __tablename__ = "user_corrections"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    insight_summary: Mapped[str] = mapped_column(Text)
    dims: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ---------- adaptive policy ----------

class PolicyVersion(Base):
    __tablename__ = "policy_versions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # e.g. "rule_v0"
    kind: Mapped[str] = mapped_column(String(30))                   # rule | linucb | ...
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="production")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    policy_version: Mapped[str] = mapped_column(String(40))
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    eligible_actions: Mapped[list] = mapped_column(JSON, default=list)
    chosen_action: Mapped[str] = mapped_column(String(60))
    propensity: Mapped[float] = mapped_column(Float, default=1.0)
    action_values: Mapped[dict] = mapped_column(JSON, default=dict)
    reward_components: Mapped[dict] = mapped_column(JSON, default=dict)
    reward_version: Mapped[str] = mapped_column(String(20), default="reward_v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ---------- experiments ----------

class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    variants: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ExperimentAssignment(Base):
    __tablename__ = "experiment_assignments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    experiment_id: Mapped[str] = mapped_column(String(60), index=True)
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    variant: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    __table_args__ = (Index("uq_exp_session", "experiment_id", "session_id", unique=True),)


# ---------- opportunities ----------

class Opportunity(Base):
    __tablename__ = "opportunities"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    pathway_type: Mapped[str] = mapped_column(String(30))   # career | consulting | entrepreneurship | builder
    industries: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    value_proposition: Mapped[str] = mapped_column(Text, default="")
    prerequisite_features: Mapped[dict] = mapped_column(JSON, default=dict)  # {dim: min_score}
    preferred_features: Mapped[dict] = mapped_column(JSON, default=dict)     # {dim: weight}
    disqualifiers: Mapped[dict] = mapped_column(JSON, default=dict)
    skill_gaps: Mapped[list] = mapped_column(JSON, default=list)
    startup_capital: Mapped[str] = mapped_column(String(30), default="none")   # none|low|medium|high
    time_to_first_value: Mapped[str] = mapped_column(String(30), default="months")
    income_range: Mapped[str] = mapped_column(String(60), default="")
    risk_profile: Mapped[str] = mapped_column(String(20), default="medium")
    ai_leverage_score: Mapped[float] = mapped_column(Float, default=0.5)
    human_differentiation_score: Mapped[float] = mapped_column(Float, default=0.5)
    demand_score: Mapped[float] = mapped_column(Float, default=0.5)
    evidence_sources: Mapped[list] = mapped_column(JSON, default=list)
    related_products: Mapped[list] = mapped_column(JSON, default=list)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    is_seed: Mapped[bool] = mapped_column(Boolean, default=True)
    freshness_timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RecommendationSet(Base):
    __tablename__ = "recommendation_sets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    profile_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ranking_model: Mapped[str] = mapped_column(String(60), default="heuristic_v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RecommendationItem(Base):
    __tablename__ = "recommendation_items"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    set_id: Mapped[str] = mapped_column(ForeignKey("recommendation_sets.id"), index=True)
    opportunity_id: Mapped[str] = mapped_column(String(60))
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    factor_contributions: Mapped[dict] = mapped_column(JSON, default=dict)
    narrative: Mapped[dict] = mapped_column(JSON, default=dict)
    explored: Mapped[bool] = mapped_column(Boolean, default=False)
    saved: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------- outcomes / events / ML ----------

class Outcome(Base):
    __tablename__ = "outcomes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    opportunity_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    kind: Mapped[str] = mapped_column(String(40))   # path_started | skill_completed | revenue_outcome | ...
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    type: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class FeatureSnapshot(Base):
    __tablename__ = "feature_snapshots"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    feature_version: Mapped[str] = mapped_column(String(20), default="feat_v1")
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ModelRegistryEntry(Base):
    __tablename__ = "model_registry"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(80))
    family: Mapped[str] = mapped_column(String(40))          # behavior | ranking | policy
    version: Mapped[str] = mapped_column(String(40))
    artifact_uri: Mapped[str] = mapped_column(String(400))
    feature_version: Mapped[str] = mapped_column(String(20), default="feat_v1")
    dataset_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(20), default="candidate")  # candidate|evaluated|shadow|canary|production|retired
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ShadowPrediction(Base):
    __tablename__ = "shadow_predictions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    model_id: Mapped[str] = mapped_column(String(32), index=True)
    session_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subject: Mapped[str] = mapped_column(String(80))
    production_value: Mapped[dict] = mapped_column(JSON, default=dict)
    shadow_value: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class LLMCall(Base):
    __tablename__ = "llm_calls"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    capability: Mapped[str] = mapped_column(String(60))
    prompt_version: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(60))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    est_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
