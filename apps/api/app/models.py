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
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    google_sub: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AuthToken(Base):
    """Opaque bearer tokens. One row per issued token so logout/revocation is a
    delete, and a stolen DB row still reveals only a random string."""
    __tablename__ = "auth_tokens"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
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


# ---------- narrative (storytelling state, never psychology) ----------

class NarrativeSessionState(Base):
    """One row per session: everything the Narrative Director remembers.
    Exists only to prevent repetitive storytelling and create continuity."""
    __tablename__ = "narrative_states"
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), primary_key=True)
    chapter: Mapped[str] = mapped_column(String(30), default="SELF_DISCOVERY")
    emotional_phase: Mapped[str] = mapped_column(String(20), default="curiosity")  # curiosity|recognition|grounding|synthesis
    story_beats_shown: Mapped[list] = mapped_column(JSON, default=list)        # [{intent, text, chapter}]
    observations_shown: Mapped[list] = mapped_column(JSON, default=list)
    metaphors_used: Mapped[list] = mapped_column(JSON, default=list)
    transition_patterns_used: Mapped[list] = mapped_column(JSON, default=list)
    sentence_openings_used: Mapped[dict] = mapped_column(JSON, default=dict)   # {opening: count}
    sentence_shapes_used: Mapped[dict] = mapped_column(JSON, default=dict)     # {shape: count}
    tics_used: Mapped[dict] = mapped_column(JSON, default=dict)                # {tic: count}
    public_figure_matches_shown: Mapped[list] = mapped_column(JSON, default=list)  # figure ids
    surprises_shown: Mapped[list] = mapped_column(JSON, default=list)          # surprise format keys
    threads: Mapped[list] = mapped_column(JSON, default=list)                  # NarrativeThread dicts
    recent_copy: Mapped[list] = mapped_column(JSON, default=list)
    chapter_closing_style_history: Mapped[list] = mapped_column(JSON, default=list)
    pending_event: Mapped[dict | None] = mapped_column(JSON, nullable=True)    # the actual thing that just changed
    next_narrative_intent: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rejected_copy_log: Mapped[list] = mapped_column(JSON, default=list)        # [{text, reasons}] for the inspector
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ---------- public figure knowledge base (verified, sourced, versioned) ----------

class PublicFigure(Base):
    __tablename__ = "public_figures"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    primary_domains: Mapped[list] = mapped_column(JSON, default=list)
    professional_roles: Mapped[list] = mapped_column(JSON, default=list)   # builder|operator|researcher|creator|leader|entrepreneur|engineer|scientist
    evidence_quality: Mapped[float] = mapped_column(Float, default=0.5)    # aggregate source quality 0..1
    record_version: Mapped[int] = mapped_column(Integer, default=1)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    status: Mapped[str] = mapped_column(String(20), default="active")      # active | archived


class PublicFigureAlias(Base):
    __tablename__ = "public_figure_aliases"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    figure_id: Mapped[str] = mapped_column(ForeignKey("public_figures.id"), index=True)
    alias: Mapped[str] = mapped_column(String(120))


class PublicFigureSource(Base):
    __tablename__ = "public_figure_sources"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    figure_id: Mapped[str] = mapped_column(ForeignKey("public_figures.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))          # interview|speech|biography|book|talk|company_material|profile
    title: Mapped[str] = mapped_column(String(240))
    publisher: Mapped[str] = mapped_column(String(120), default="")
    url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ISO date or year
    credibility: Mapped[float] = mapped_column(Float, default=0.6)               # 0..1, curated
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PublicFigureEvidence(Base):
    __tablename__ = "public_figure_evidence"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    figure_id: Mapped[str] = mapped_column(ForeignKey("public_figures.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("public_figure_sources.id"))
    claim: Mapped[str] = mapped_column(Text)               # narrow, documented professional fact
    review_status: Mapped[str] = mapped_column(String(20), default="approved")  # extracted|approved|rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PublicFigurePattern(Base):
    __tablename__ = "public_figure_patterns"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    figure_id: Mapped[str] = mapped_column(ForeignKey("public_figures.id"), index=True)
    construct: Mapped[str] = mapped_column(String(40))     # approved taxonomy (resonance.CONSTRUCTS)
    description: Mapped[str] = mapped_column(Text)         # short sourced professional behavior
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)  # PublicFigureEvidence ids — mandatory
    confidence: Mapped[float] = mapped_column(Float, default=0.6)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PublicFigureEmbedding(Base):
    __tablename__ = "public_figure_embeddings"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    figure_id: Mapped[str] = mapped_column(ForeignKey("public_figures.id"), index=True)
    pattern_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    vector: Mapped[list] = mapped_column(JSON, default=list)   # construct-space vector (pgvector native in prod migration)
    embedding_version: Mapped[str] = mapped_column(String(20), default="construct_v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PublicFigureVersion(Base):
    __tablename__ = "public_figure_versions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    figure_id: Mapped[str] = mapped_column(ForeignKey("public_figures.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)  # full record at this version
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PublicFigureMatchFeedback(Base):
    __tablename__ = "public_figure_match_feedback"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    figure_id: Mapped[str] = mapped_column(String(60), index=True)
    pattern_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    verdict: Mapped[str] = mapped_column(String(20))       # see_it | not_sure | not_relevant
    chapter: Mapped[str] = mapped_column(String(30))
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), default="")  # user evidence at feedback time
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ResonanceSnapshot(Base):
    """What the matching pipeline returned at a chapter boundary — the substrate
    for 'the matches moved' storytelling and for match-evolution tests."""
    __tablename__ = "resonance_snapshots"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    chapter: Mapped[str] = mapped_column(String(30))
    matches: Mapped[list] = mapped_column(JSON, default=list)      # [{figureId, patternId, construct, score, strength, userEvidence}]
    candidates_considered: Mapped[list] = mapped_column(JSON, default=list)  # inspector: why selected / rejected
    user_feature_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ---------- intelligence core: evidence ledger + hypotheses ----------
# Four levels of knowledge, kept apart in state: explicit/derived FACTS live in
# practical_context (with provenance in evidence_items), HYPOTHESES are rows
# here with evidence links, and ACTIONABLE CONCLUSIONS exist only downstream
# once thresholds are met. Nothing important without evidence ids.

class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))   # explicit_fact | behavioral_choice | professional_history
                                                    # | free_text_extraction | calibration | correction | outcome
    claim: Mapped[str] = mapped_column(Text)
    dims: Mapped[list] = mapped_column(JSON, default=list)          # dimensions this bears on (signed)
    source_interaction_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    strength: Mapped[float] = mapped_column(Float, default=0.4)
    reliability: Mapped[float] = mapped_column(Float, default=0.6)  # explicit > calibration > behavioral > extraction
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    construct: Mapped[str] = mapped_column(String(60))              # dimension or professional construct
    direction: Mapped[int] = mapped_column(Integer, default=1)      # which pole the hypothesis claims
    statement: Mapped[str] = mapped_column(Text, default="")
    supporting_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    contradicting_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="emerging")
    # emerging | supported | uncertain | contradicted | corrected
    version: Mapped[int] = mapped_column(Integer, default=1)
    thresholds_version: Mapped[str] = mapped_column(String(20), default="thresh_v1")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    __table_args__ = (Index("uq_hypothesis_construct", "session_id", "construct", "direction", unique=True),)


class HypothesisVersion(Base):
    """Never overwrite silently — the story needs to show its own revisions."""
    __tablename__ = "hypothesis_versions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    hypothesis_id: Mapped[str] = mapped_column(ForeignKey("hypotheses.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20))
    trigger: Mapped[str] = mapped_column(String(60), default="")    # what caused this revision
    chapter: Mapped[str] = mapped_column(String(30), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AmbiguityRecord(Base):
    """Detected but deliberately unresolved understanding gaps. Ambiguity is
    never itself treated as psychological signal (PART 62)."""
    __tablename__ = "ambiguities"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    key: Mapped[str] = mapped_column(String(60))                    # e.g. "manage_software_scope"
    description: Mapped[str] = mapped_column(Text)
    possible_interpretations: Mapped[list] = mapped_column(JSON, default=list)
    source_text: Mapped[str] = mapped_column(Text, default="")
    clarification_value: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="open") # open | clarified | abandoned
    resolution: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class InferenceFeedback(Base):
    """User said an analysis was wrong — proprietary calibration training data."""
    __tablename__ = "inference_feedback"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    hypothesis_construct: Mapped[str] = mapped_column(String(60))
    supporting_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    rejection: Mapped[str] = mapped_column(String(30))              # not_really | kind_of | not_relevant
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    policy_version: Mapped[str] = mapped_column(String(40), default="")
    thresholds_version: Mapped[str] = mapped_column(String(20), default="thresh_v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class NarrativeEvent(Base):
    """Story exists only when something changed. Beats derive from these."""
    __tablename__ = "narrative_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    type: Mapped[str] = mapped_column(String(50))
    # NEW_FACT_CHANGED_MODEL | HYPOTHESIS_STRENGTHENED | HYPOTHESIS_COLLAPSED |
    # CONTRADICTION_APPEARED | CONTRADICTION_RESOLVED | USER_CORRECTED_SYSTEM |
    # PROFESSIONAL_CONTEXT_CHANGED_PICTURE | OLD_ANSWER_BECAME_RELEVANT |
    # EXPECTED_PATTERN_DID_NOT_APPEAR | PUBLIC_RESONANCE_CHANGED | CHAPTER_OBJECTIVE_REACHED
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    chapter: Mapped[str] = mapped_column(String(30), default="")
    consumed_by_closing: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ChapterClosingPlan(Base):
    """Every closing has a recorded purpose; a closing that cannot answer
    'why this structure / what changed' is generic and must not exist."""
    __tablename__ = "chapter_closing_plans"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    chapter: Mapped[str] = mapped_column(String(30))
    selected_structure: Mapped[str] = mapped_column(String(40))
    available_events: Mapped[list] = mapped_column(JSON, default=list)
    why_this_closing: Mapped[str] = mapped_column(Text, default="")
    what_changed: Mapped[str] = mapped_column(Text, default="")
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    open_thread: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ---------- world intelligence: canonical ontology ----------
# WORLD knowledge is independent of any user. It is ingested, versioned and
# refreshed — never generated per user, never authored by the LLM at runtime.

class WIOccupation(Base):
    __tablename__ = "occupations"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)     # occupation_unbify_*
    preferred_label: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    labels_i18n: Mapped[dict] = mapped_column(JSON, default=dict)     # {lang: [labels]}
    work_class: Mapped[str] = mapped_column(String(30), default="knowledge")  # knowledge|trade|clinical|field|service|creative|operational|mixed
    physical_environment: Mapped[list] = mapped_column(JSON, default=list)
    pathway_potentials: Mapped[list] = mapped_column(JSON, default=list)  # employment|specialization|contracting|business_ownership|consulting|training|advisory|part_time|...
    regulated: Mapped[bool] = mapped_column(Boolean, default=False)
    self_employment_prevalence: Mapped[float] = mapped_column(Float, default=0.3)
    ai_automation_exposure: Mapped[float] = mapped_column(Float, default=0.3)
    ai_augmentation_potential: Mapped[float] = mapped_column(Float, default=0.5)
    definition_version: Mapped[int] = mapped_column(Integer, default=1)
    definition_updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    status: Mapped[str] = mapped_column(String(20), default="active")


class WIOccupationAlias(Base):
    __tablename__ = "occupation_aliases"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    occupation_id: Mapped[str] = mapped_column(ForeignKey("occupations.id"), index=True)
    alias: Mapped[str] = mapped_column(String(120), index=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    region: Mapped[str | None] = mapped_column(String(60), nullable=True)


class WIOccupationExternalMapping(Base):
    __tablename__ = "occupation_external_mappings"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    occupation_id: Mapped[str] = mapped_column(ForeignKey("occupations.id"), index=True)
    scheme: Mapped[str] = mapped_column(String(30))       # onet | esco | isco | nco | other
    external_id: Mapped[str] = mapped_column(String(120))
    mapping_confidence: Mapped[float] = mapped_column(Float, default=0.9)


class WICapability(Base):
    __tablename__ = "capabilities"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30), default="capability")   # capability | skill | tool
    description: Mapped[str] = mapped_column(Text, default="")


class WIOccupationCapability(Base):
    __tablename__ = "occupation_capabilities"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    occupation_id: Mapped[str] = mapped_column(ForeignKey("occupations.id"), index=True)
    capability_id: Mapped[str] = mapped_column(ForeignKey("capabilities.id"), index=True)
    relation: Mapped[str] = mapped_column(String(20), default="requires")  # requires | uses | develops
    weight: Mapped[float] = mapped_column(Float, default=0.6)


class WIOccupationTransition(Base):
    __tablename__ = "occupation_transitions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    from_occupation_id: Mapped[str] = mapped_column(ForeignKey("occupations.id"), index=True)
    to_occupation_id: Mapped[str] = mapped_column(ForeignKey("occupations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="transition")  # specialization | transition | independent_practice
    evidence_note: Mapped[str] = mapped_column(Text, default="")
    strength: Mapped[float] = mapped_column(Float, default=0.5)


class WIIndustry(Base):
    __tablename__ = "industries"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))


class WIProblem(Base):
    """What are people/companies paying to solve? Feeds entrepreneurial and
    consulting directions — never random startup ideas."""
    __tablename__ = "problems"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    label: Mapped[str] = mapped_column(String(200))
    industries: Mapped[list] = mapped_column(JSON, default=list)
    solved_by_capabilities: Mapped[list] = mapped_column(JSON, default=list)
    evidence_note: Mapped[str] = mapped_column(Text, default="")


class WILicenseRequirement(Base):
    __tablename__ = "license_requirements"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    occupation_id: Mapped[str] = mapped_column(ForeignKey("occupations.id"), index=True)
    jurisdiction: Mapped[str] = mapped_column(String(60), default="*")
    requirement: Mapped[str] = mapped_column(String(200))
    restricted_activities: Mapped[list] = mapped_column(JSON, default=list)
    source_note: Mapped[str] = mapped_column(Text, default="")


# ---------- world intelligence: ingestion + sources ----------

class WISource(Base):
    __tablename__ = "intelligence_sources"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(30))         # official_taxonomy|government|job_board|community|...
    country_coverage: Mapped[list] = mapped_column(JSON, default=list)
    access_method: Mapped[str] = mapped_column(String(30))  # api|dataset|rss|licensed_feed|permitted_crawl|manual
    refresh_policy: Mapped[str] = mapped_column(String(60), default="weekly")
    ttl_hours: Mapped[int] = mapped_column(Integer, default=168)
    allowed_uses: Mapped[list] = mapped_column(JSON, default=list)
    attribution_required: Mapped[bool] = mapped_column(Boolean, default=False)
    license_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    trust_score: Mapped[float] = mapped_column(Float, default=0.5)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # compliance is mandatory before any ingestion happens
    compliance: Mapped[dict] = mapped_column(JSON, default=dict)
    # {terms_reviewed, crawl_policy_reviewed, license_known, storage_permitted,
    #  usage_known, retention_rules}
    cost_stats: Mapped[dict] = mapped_column(JSON, default=dict)


class WIApifyActorConfig(Base):
    __tablename__ = "apify_actor_configs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("intelligence_sources.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(120))
    actor_version: Mapped[str] = mapped_column(String(30), default="latest")
    input_template: Mapped[dict] = mapped_column(JSON, default=dict)
    dataset_schema_version: Mapped[str] = mapped_column(String(20), default="v1")
    refresh_strategy: Mapped[str] = mapped_column(String(30), default="weekly")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class WIIngestionRun(Base):
    __tablename__ = "intelligence_ingestion_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    source_id: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(20), default="started")  # started|completed|failed|partial
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    deduplicated_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_failures: Mapped[int] = mapped_column(Integer, default=0)
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    normalization_version: Mapped[str] = mapped_column(String(20), default="norm_v1")
    extractor_version: Mapped[str] = mapped_column(String(20), default="ext_v1")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class WISourceObservation(Base):
    """Raw external evidence never becomes truth directly — it becomes an
    observation, and observations aggregate into market signals."""
    __tablename__ = "source_observations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    source_id: Mapped[str] = mapped_column(String(60), index=True)
    ingestion_run_id: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)  # change detection / dedupe
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    geography: Mapped[str] = mapped_column(String(60), default="*")   # country|state|metro|city|remote
    geography_level: Mapped[str] = mapped_column(String(20), default="country")
    occupation_refs: Mapped[list] = mapped_column(JSON, default=list)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    signal_type: Mapped[str] = mapped_column(String(40))
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    source_quality: Mapped[float] = mapped_column(Float, default=0.5)
    raw_reference: Mapped[str | None] = mapped_column(String(400), nullable=True)


class WIMarketSignal(Base):
    __tablename__ = "market_signals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    occupation_id: Mapped[str] = mapped_column(String(60), index=True)
    construct: Mapped[str] = mapped_column(String(40))    # demand_direction|posting_volume|self_employment_prevalence|...
    geography: Mapped[str] = mapped_column(String(60), default="*")
    geography_level: Mapped[str] = mapped_column(String(20), default="country")
    value: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    source_diversity: Mapped[int] = mapped_column(Integer, default=0)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)   # observation ids
    conflicts: Mapped[list] = mapped_column(JSON, default=list)       # disagreeing source classes, retained
    window_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    snapshot_version: Mapped[str] = mapped_column(String(40), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class WITargetedRefreshRequest(Base):
    """Privacy boundary: only generic market queries leave UNBIFY — never a
    user's identity, answers, or psychological signals."""
    __tablename__ = "targeted_refresh_requests"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    occupation_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    query_terms: Mapped[list] = mapped_column(JSON, default=list)
    geography: Mapped[str] = mapped_column(String(60), default="*")
    reason: Mapped[str] = mapped_column(String(60), default="stale")  # stale|coverage_gap|domain_enrichment
    status: Mapped[str] = mapped_column(String(20), default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class WIOpportunitySnapshot(Base):
    """Exactly which intelligence produced a recommendation — reproducible,
    never silently mutated."""
    __tablename__ = "opportunity_market_snapshots"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    recommendation_set_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    profile_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    market_snapshot_version: Mapped[str] = mapped_column(String(40))
    ranking_model_version: Mapped[str] = mapped_column(String(40))
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ---------- materialization: story meaning -> material objects ----------

class MaterialObject(Base):
    """A tangible thing produced from the journey: a capability, a leverage
    asset, a gap, a direction, or an experiment. Users can save these, and
    they persist beyond one session."""
    __tablename__ = "material_objects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    # capability | leverage | gap | direction | experiment | insight | question
    key: Mapped[str] = mapped_column(String(120))          # stable per-session identity
    label: Mapped[str] = mapped_column(String(200))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)   # EvidenceItem ids — provenance
    strength: Mapped[float] = mapped_column(Float, default=0.5)
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="new")
    # new | exploring | saved | testing | active | dismissed | completed
    dismissal_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    materialization_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    __table_args__ = (Index("uq_material_key", "session_id", "kind", "key", unique=True),)


class ExperimentRun(Base):
    """A cheap, specific test of one direction — and what actually happened.
    Outcomes are far stronger evidence than early questionnaire answers."""
    __tablename__ = "experiment_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    material_object_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    direction_key: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(Text)
    teaches: Mapped[str] = mapped_column(Text, default="")     # the uncertainty it resolves
    effort: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(20), default="started")  # started | completed | abandoned
    outcome: Mapped[dict] = mapped_column(JSON, default=dict)  # {verdict, note, earned, continued}
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ProductRouteRecord(Base):
    """Product routing is evidence-based infrastructure, never a banner.
    A route without a complete need→evidence→gap→capability chain is not shown."""
    __tablename__ = "product_routes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    capability: Mapped[str] = mapped_column(String(30))   # career|marketplace|agency|suite|brain
    reason_codes: Mapped[list] = mapped_column(JSON, default=list)
    prerequisite_states: Mapped[list] = mapped_column(JSON, default=list)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    explanation_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    user_need: Mapped[str] = mapped_column(Text, default="")
    gap: Mapped[str] = mapped_column(Text, default="")
    shown_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class MaterializationSnapshot(Base):
    """What Materialization produced, and from which intelligence versions."""
    __tablename__ = "materialization_snapshots"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    profile_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recommendation_set_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ---------- PostgreSQL as the operational backbone: jobs, locks, coverage ----------
# No Redis, no external queue. Workers claim jobs with FOR UPDATE SKIP LOCKED.

class IntelligenceJob(Base):
    __tablename__ = "intelligence_jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    job_type: Mapped[str] = mapped_column(String(40), index=True)
    # targeted_refresh | deep_refresh | normalize_dataset | domain_enrichment | broad_refresh
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # pending | running | completed | failed | cancelled
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    scope_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    priority: Mapped[int] = mapped_column(Integer, default=100)   # lower runs first
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    apify_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    result_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IntelligenceScopeCache(Base):
    """One row per (occupation, geography, intent, source family). Concurrent
    identical requests reuse the in-flight refresh instead of each firing one."""
    __tablename__ = "intelligence_scope_cache"
    scope_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    occupation_id: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    geography: Mapped[str] = mapped_column(String(60), default="*")
    intent: Mapped[str] = mapped_column(String(40), default="explore")
    source_family: Mapped[str] = mapped_column(String(40), default="market")
    query_terms: Mapped[list] = mapped_column(JSON, default=list)
    latest_snapshot_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    coverage_score: Mapped[float] = mapped_column(Float, default=0.0)
    freshness_state: Mapped[str] = mapped_column(String(20), default="INSUFFICIENT")
    # CURRENT | REFRESHING | PARTIAL | STALE_BUT_USABLE | INSUFFICIENT
    refreshing_job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class DomainEnrichmentRequest(Base):
    """Repeated demand from a weakly-covered domain raises its priority, so
    the world model grows toward the humans who actually arrive."""
    __tablename__ = "domain_enrichment_requests"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    domain: Mapped[str] = mapped_column(String(120), index=True)
    geography: Mapped[str] = mapped_column(String(60), default="*")
    request_count: Mapped[int] = mapped_column(Integer, default=1)
    current_coverage: Mapped[float] = mapped_column(Float, default=0.0)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    last_requested_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (Index("uq_domain_geo", "domain", "geography", unique=True),)


class SourceHealth(Base):
    __tablename__ = "source_health"
    source_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    last_success: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_failure: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    latest_record_count: Mapped[int] = mapped_column(Integer, default=0)
    data_quality_score: Mapped[float] = mapped_column(Float, default=0.5)
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    useful_observations: Mapped[int] = mapped_column(Integer, default=0)
    recommendations_affected: Mapped[int] = mapped_column(Integer, default=0)


class AnalysisVersion(Base):
    """Every analysis is computed at request time and recorded with exactly
    which human/world/ranker versions produced it — never overwritten."""
    __tablename__ = "analysis_versions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    action: Mapped[str] = mapped_column(String(60))
    intent: Mapped[dict] = mapped_column(JSON, default=dict)
    profile_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    market_snapshot_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ranker_version: Mapped[str] = mapped_column(String(40), default="")
    scope_hash: Mapped[str] = mapped_column(String(64), default="")
    freshness_state: Mapped[str] = mapped_column(String(20), default="CURRENT")
    coverage_score: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    supersedes_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class RequestLatency(Base):
    """Per-request phase timings — the substrate for p50/p95/p99 monitoring and
    for telling a UX problem apart from a backend one."""
    __tablename__ = "request_latency"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)   # response | analysis | workspace
    total_ms: Mapped[int] = mapped_column(Integer)
    phases: Mapped[dict] = mapped_column(JSON, default=dict)
    over_budget: Mapped[list] = mapped_column(JSON, default=list)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


# ---------- quote intelligence: verified, sourced, never LLM-recalled ----------

class QuotePerson(Base):
    """Accomplished people across MANY fields — trades, medicine, science,
    sport, craft, engineering, business. Success is not "tech billionaire"."""
    __tablename__ = "quote_people"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    field: Mapped[str] = mapped_column(String(60))          # trades|medicine|science|sport|craft|...
    descriptor: Mapped[str] = mapped_column(String(160), default="")
    era: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")


class QuoteSource(Base):
    __tablename__ = "quote_sources"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))           # speech|interview|book|letter|talk|archive
    title: Mapped[str] = mapped_column(String(240))
    publisher: Mapped[str] = mapped_column(String(160), default="")
    url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    credibility: Mapped[float] = mapped_column(Float, default=0.7)


class QuoteRecord(Base):
    __tablename__ = "quotes"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("quote_people.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("quote_sources.id"))
    quote_text: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text, default="")   # what they were addressing
    themes: Mapped[list] = mapped_column(JSON, default=list)  # PRINCIPLES (focus, craft, ...)
    professional_patterns: Mapped[list] = mapped_column(JSON, default=list)  # construct ids
    verification_status: Mapped[str] = mapped_column(String(20), default="review_needed")
    # verified | review_needed | rejected — only "verified" may ever be displayed
    evidence_quality: Mapped[float] = mapped_column(Float, default=0.6)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class QuoteImpression(Base):
    """What a session has already seen, so no one meets the same person or
    principle repeatedly."""
    __tablename__ = "quote_impressions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("discover_sessions.id"), index=True)
    quote_id: Mapped[str] = mapped_column(String(60))
    person_id: Mapped[str] = mapped_column(String(60))
    theme: Mapped[str] = mapped_column(String(60), default="")
    module: Mapped[str] = mapped_column(String(40), default="quote")  # quote | same_principle
    chapter: Mapped[str] = mapped_column(String(30), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PatternValueRelationship(Base):
    """pattern × context → the value mechanism it can produce. Authored to
    start; meant to be learned from real outcomes. This is the thing that
    turns a personal pattern into economic leverage."""
    __tablename__ = "pattern_value_relationships"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    pattern: Mapped[str] = mapped_column(String(60), index=True)
    context: Mapped[list] = mapped_column(JSON, default=list)     # work_class / domain conditions
    value_mechanisms: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    market_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    outcome_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
