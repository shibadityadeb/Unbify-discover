"""postgres job queue, scope cache, coverage demand, source health, analysis versions

Revision ID: 0007_realtime_intelligence
Revises: 0006_materialization
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_realtime_intelligence"
down_revision = "0006_materialization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("intelligence_jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("job_type", sa.String(40), index=True),
        sa.Column("status", sa.String(20), index=True),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("scope_hash", sa.String(64), index=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("apify_run_id", sa.String(64), nullable=True, index=True),
        sa.Column("result_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True))
    # the claim query orders by (priority, created_at) over pending rows
    op.create_index("ix_jobs_claim", "intelligence_jobs", ["status", "priority", "created_at"])
    op.create_table("intelligence_scope_cache",
        sa.Column("scope_hash", sa.String(64), primary_key=True),
        sa.Column("occupation_id", sa.String(60), nullable=True, index=True),
        sa.Column("geography", sa.String(60), nullable=False),
        sa.Column("intent", sa.String(40), nullable=False),
        sa.Column("source_family", sa.String(40), nullable=False),
        sa.Column("query_terms", sa.JSON(), nullable=False),
        sa.Column("latest_snapshot_version", sa.String(40), nullable=True),
        sa.Column("coverage_score", sa.Float(), nullable=False),
        sa.Column("freshness_state", sa.String(20), nullable=False),
        sa.Column("refreshing_job_id", sa.String(32), nullable=True),
        sa.Column("last_refresh_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("domain_enrichment_requests",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("domain", sa.String(120), index=True),
        sa.Column("geography", sa.String(60), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("current_coverage", sa.Float(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("last_requested_at", sa.DateTime(), nullable=False),
        sa.Column("last_enriched_at", sa.DateTime(), nullable=True))
    op.create_index("uq_domain_geo", "domain_enrichment_requests",
                    ["domain", "geography"], unique=True)
    op.create_table("source_health",
        sa.Column("source_id", sa.String(60), primary_key=True),
        sa.Column("last_success", sa.DateTime(), nullable=True),
        sa.Column("last_failure", sa.DateTime(), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("latest_record_count", sa.Integer(), nullable=False),
        sa.Column("data_quality_score", sa.Float(), nullable=False),
        sa.Column("total_runs", sa.Integer(), nullable=False),
        sa.Column("total_cost_usd", sa.Float(), nullable=False),
        sa.Column("useful_observations", sa.Integer(), nullable=False),
        sa.Column("recommendations_affected", sa.Integer(), nullable=False))
    op.create_table("analysis_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("discover_sessions.id"), index=True),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("intent", sa.JSON(), nullable=False),
        sa.Column("profile_version_id", sa.String(32), nullable=True),
        sa.Column("market_snapshot_version", sa.String(40), nullable=True),
        sa.Column("ranker_version", sa.String(40), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("freshness_state", sa.String(20), nullable=False),
        sa.Column("coverage_score", sa.Float(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("supersedes_id", sa.String(32), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True))


def downgrade() -> None:
    for t in ("analysis_versions", "source_health", "domain_enrichment_requests",
              "intelligence_scope_cache", "intelligence_jobs"):
        op.drop_table(t)
