"""evidence ledger, hypotheses, ambiguities, narrative events, closing plans

Revision ID: 0004_intelligence_core
Revises: 0003_narrative_resonance
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_intelligence_core"
down_revision = "0003_narrative_resonance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("evidence_items",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("discover_sessions.id"), index=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("dims", sa.JSON(), nullable=False),
        sa.Column("source_interaction_id", sa.String(32), nullable=True),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("reliability", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table("hypotheses",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("discover_sessions.id"), index=True),
        sa.Column("construct", sa.String(60), nullable=False),
        sa.Column("direction", sa.Integer(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("supporting_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("contradicting_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("thresholds_version", sa.String(20), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("uq_hypothesis_construct", "hypotheses",
                    ["session_id", "construct", "direction"], unique=True)
    op.create_table("hypothesis_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("hypothesis_id", sa.String(32), sa.ForeignKey("hypotheses.id"), index=True),
        sa.Column("session_id", sa.String(32), index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("trigger", sa.String(60), nullable=False),
        sa.Column("chapter", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table("ambiguities",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("discover_sessions.id"), index=True),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("possible_interpretations", sa.JSON(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("clarification_value", sa.Float(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("resolution", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table("inference_feedback",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("discover_sessions.id"), index=True),
        sa.Column("hypothesis_construct", sa.String(60), nullable=False),
        sa.Column("supporting_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("rejection", sa.String(30), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("thresholds_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table("narrative_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("discover_sessions.id"), index=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("chapter", sa.String(30), nullable=False),
        sa.Column("consumed_by_closing", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table("chapter_closing_plans",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("discover_sessions.id"), index=True),
        sa.Column("chapter", sa.String(30), nullable=False),
        sa.Column("selected_structure", sa.String(40), nullable=False),
        sa.Column("available_events", sa.JSON(), nullable=False),
        sa.Column("why_this_closing", sa.Text(), nullable=False),
        sa.Column("what_changed", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("open_thread", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    for t in ("chapter_closing_plans", "narrative_events", "inference_feedback",
              "ambiguities", "hypothesis_versions", "hypotheses", "evidence_items"):
        op.drop_table(t)
