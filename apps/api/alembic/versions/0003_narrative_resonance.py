"""narrative director state + public figure knowledge base + resonance

Revision ID: 0003_narrative_resonance
Revises: 0002_pgvector
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_narrative_resonance"
down_revision = "0002_pgvector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("narrative_states",
        sa.Column("session_id", sa.String(32), sa.ForeignKey("discover_sessions.id"), primary_key=True),
        sa.Column("chapter", sa.String(30), nullable=False),
        sa.Column("emotional_phase", sa.String(20), nullable=False),
        sa.Column("story_beats_shown", sa.JSON(), nullable=False),
        sa.Column("observations_shown", sa.JSON(), nullable=False),
        sa.Column("metaphors_used", sa.JSON(), nullable=False),
        sa.Column("transition_patterns_used", sa.JSON(), nullable=False),
        sa.Column("sentence_openings_used", sa.JSON(), nullable=False),
        sa.Column("sentence_shapes_used", sa.JSON(), nullable=False),
        sa.Column("tics_used", sa.JSON(), nullable=False),
        sa.Column("public_figure_matches_shown", sa.JSON(), nullable=False),
        sa.Column("surprises_shown", sa.JSON(), nullable=False),
        sa.Column("threads", sa.JSON(), nullable=False),
        sa.Column("recent_copy", sa.JSON(), nullable=False),
        sa.Column("chapter_closing_style_history", sa.JSON(), nullable=False),
        sa.Column("pending_event", sa.JSON(), nullable=True),
        sa.Column("next_narrative_intent", sa.String(80), nullable=True),
        sa.Column("rejected_copy_log", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table("public_figures",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("primary_domains", sa.JSON(), nullable=False),
        sa.Column("professional_roles", sa.JSON(), nullable=False),
        sa.Column("evidence_quality", sa.Float(), nullable=False),
        sa.Column("record_version", sa.Integer(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
    )
    op.create_table("public_figure_aliases",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("figure_id", sa.String(60), sa.ForeignKey("public_figures.id"), index=True),
        sa.Column("alias", sa.String(120), nullable=False),
    )
    op.create_table("public_figure_sources",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("figure_id", sa.String(60), sa.ForeignKey("public_figures.id"), index=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("publisher", sa.String(120), nullable=False),
        sa.Column("url", sa.String(400), nullable=True),
        sa.Column("published_at", sa.String(20), nullable=True),
        sa.Column("credibility", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table("public_figure_evidence",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("figure_id", sa.String(60), sa.ForeignKey("public_figures.id"), index=True),
        sa.Column("source_id", sa.String(60), sa.ForeignKey("public_figure_sources.id")),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table("public_figure_patterns",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("figure_id", sa.String(60), sa.ForeignKey("public_figures.id"), index=True),
        sa.Column("construct", sa.String(40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table("public_figure_embeddings",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("figure_id", sa.String(60), sa.ForeignKey("public_figures.id"), index=True),
        sa.Column("pattern_id", sa.String(60), nullable=True),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("embedding_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table("public_figure_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("figure_id", sa.String(60), sa.ForeignKey("public_figures.id"), index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table("public_figure_match_feedback",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("discover_sessions.id"), index=True),
        sa.Column("figure_id", sa.String(60), index=True),
        sa.Column("pattern_id", sa.String(60), nullable=True),
        sa.Column("verdict", sa.String(20), nullable=False),
        sa.Column("chapter", sa.String(30), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table("resonance_snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("discover_sessions.id"), index=True),
        sa.Column("chapter", sa.String(30), nullable=False),
        sa.Column("matches", sa.JSON(), nullable=False),
        sa.Column("candidates_considered", sa.JSON(), nullable=False),
        sa.Column("user_feature_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    for t in ("resonance_snapshots", "public_figure_match_feedback", "public_figure_versions",
              "public_figure_embeddings", "public_figure_patterns", "public_figure_evidence",
              "public_figure_sources", "public_figure_aliases", "public_figures", "narrative_states"):
        op.drop_table(t)
