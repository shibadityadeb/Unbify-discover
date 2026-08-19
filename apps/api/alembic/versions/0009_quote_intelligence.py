"""quote intelligence library and pattern-value relationships

Revision ID: 0009_quote_intelligence
Revises: 0008_latency
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_quote_intelligence"
down_revision = "0008_latency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("quote_people",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("field", sa.String(60), nullable=False),
        sa.Column("descriptor", sa.String(160), nullable=False),
        sa.Column("era", sa.String(40), nullable=True),
        sa.Column("status", sa.String(20), nullable=False))
    op.create_table("quote_sources",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("publisher", sa.String(160), nullable=False),
        sa.Column("url", sa.String(400), nullable=True),
        sa.Column("published_at", sa.String(20), nullable=True),
        sa.Column("credibility", sa.Float(), nullable=False))
    op.create_table("quotes",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("person_id", sa.String(60), sa.ForeignKey("quote_people.id"), index=True),
        sa.Column("source_id", sa.String(60), sa.ForeignKey("quote_sources.id")),
        sa.Column("quote_text", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("themes", sa.JSON(), nullable=False),
        sa.Column("professional_patterns", sa.JSON(), nullable=False),
        sa.Column("verification_status", sa.String(20), nullable=False),
        sa.Column("evidence_quality", sa.Float(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(), nullable=False))
    op.create_table("quote_impressions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("discover_sessions.id"), index=True),
        sa.Column("quote_id", sa.String(60), nullable=False),
        sa.Column("person_id", sa.String(60), nullable=False),
        sa.Column("theme", sa.String(60), nullable=False),
        sa.Column("module", sa.String(40), nullable=False),
        sa.Column("chapter", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("pattern_value_relationships",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("pattern", sa.String(60), index=True),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("value_mechanisms", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("market_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("outcome_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False))


def downgrade() -> None:
    for t in ("pattern_value_relationships", "quote_impressions", "quotes",
              "quote_sources", "quote_people"):
        op.drop_table(t)
