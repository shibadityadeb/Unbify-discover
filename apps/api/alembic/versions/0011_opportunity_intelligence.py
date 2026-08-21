"""opportunity intelligence: live market postings, query runs, discovery cache

Revision ID: 0011_opportunity_intelligence
Revises: 0010_accounts
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_opportunity_intelligence"
down_revision = "0010_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("market_postings",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("source_id", sa.String(60), nullable=False, index=True),
        sa.Column("query", sa.String(200), nullable=False, index=True),
        sa.Column("cluster_key", sa.String(120), nullable=False, index=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("title_norm", sa.String(200), nullable=False, index=True),
        sa.Column("company", sa.String(200), nullable=True),
        sa.Column("location", sa.String(200), nullable=True),
        sa.Column("geography", sa.String(60), nullable=False, index=True),
        sa.Column("remote", sa.Boolean(), nullable=True),
        sa.Column("salary_min", sa.Float(), nullable=True),
        sa.Column("salary_max", sa.Float(), nullable=True),
        sa.Column("salary_currency", sa.String(10), nullable=True),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("url", sa.String(600), nullable=True),
        sa.Column("posted_at", sa.DateTime(), nullable=True, index=True),
        sa.Column("retrieved_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("content_hash", sa.String(64), nullable=False, index=True))
    op.create_table("market_query_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("query", sa.String(200), nullable=False, index=True),
        sa.Column("geography", sa.String(60), nullable=False),
        sa.Column("source_id", sa.String(60), nullable=False),
        sa.Column("postings_found", sa.Integer(), nullable=False),
        sa.Column("ran_at", sa.DateTime(), nullable=False, index=True))
    op.create_table("discovery_cache",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), nullable=False, index=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))


def downgrade() -> None:
    op.drop_table("discovery_cache")
    op.drop_table("market_query_runs")
    op.drop_table("market_postings")
