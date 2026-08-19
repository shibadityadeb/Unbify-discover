"""world intelligence: canonical ontology, ingestion, market signals, snapshots

Revision ID: 0005_world_intelligence
Revises: 0004_intelligence_core
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_world_intelligence"
down_revision = "0004_intelligence_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("occupations",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("preferred_label", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("labels_i18n", sa.JSON(), nullable=False),
        sa.Column("work_class", sa.String(30), nullable=False),
        sa.Column("physical_environment", sa.JSON(), nullable=False),
        sa.Column("pathway_potentials", sa.JSON(), nullable=False),
        sa.Column("regulated", sa.Boolean(), nullable=False),
        sa.Column("self_employment_prevalence", sa.Float(), nullable=False),
        sa.Column("ai_automation_exposure", sa.Float(), nullable=False),
        sa.Column("ai_augmentation_potential", sa.Float(), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("definition_updated_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False))
    op.create_table("occupation_aliases",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("occupation_id", sa.String(60), sa.ForeignKey("occupations.id"), index=True),
        sa.Column("alias", sa.String(120), index=True),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("region", sa.String(60), nullable=True))
    op.create_table("occupation_external_mappings",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("occupation_id", sa.String(60), sa.ForeignKey("occupations.id"), index=True),
        sa.Column("scheme", sa.String(30), nullable=False),
        sa.Column("external_id", sa.String(120), nullable=False),
        sa.Column("mapping_confidence", sa.Float(), nullable=False))
    op.create_table("capabilities",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("description", sa.Text(), nullable=False))
    op.create_table("occupation_capabilities",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("occupation_id", sa.String(60), sa.ForeignKey("occupations.id"), index=True),
        sa.Column("capability_id", sa.String(60), sa.ForeignKey("capabilities.id"), index=True),
        sa.Column("relation", sa.String(20), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False))
    op.create_table("occupation_transitions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("from_occupation_id", sa.String(60), sa.ForeignKey("occupations.id"), index=True),
        sa.Column("to_occupation_id", sa.String(60), sa.ForeignKey("occupations.id"), index=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("evidence_note", sa.Text(), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False))
    op.create_table("industries",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("label", sa.String(120), nullable=False))
    op.create_table("problems",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("industries", sa.JSON(), nullable=False),
        sa.Column("solved_by_capabilities", sa.JSON(), nullable=False),
        sa.Column("evidence_note", sa.Text(), nullable=False))
    op.create_table("license_requirements",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("occupation_id", sa.String(60), sa.ForeignKey("occupations.id"), index=True),
        sa.Column("jurisdiction", sa.String(60), nullable=False),
        sa.Column("requirement", sa.String(200), nullable=False),
        sa.Column("restricted_activities", sa.JSON(), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=False))
    op.create_table("intelligence_sources",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("country_coverage", sa.JSON(), nullable=False),
        sa.Column("access_method", sa.String(30), nullable=False),
        sa.Column("refresh_policy", sa.String(60), nullable=False),
        sa.Column("ttl_hours", sa.Integer(), nullable=False),
        sa.Column("allowed_uses", sa.JSON(), nullable=False),
        sa.Column("attribution_required", sa.Boolean(), nullable=False),
        sa.Column("license_metadata", sa.JSON(), nullable=False),
        sa.Column("trust_score", sa.Float(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("compliance", sa.JSON(), nullable=False),
        sa.Column("cost_stats", sa.JSON(), nullable=False))
    op.create_table("apify_actor_configs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("source_id", sa.String(60), sa.ForeignKey("intelligence_sources.id"), index=True),
        sa.Column("actor_id", sa.String(120), nullable=False),
        sa.Column("actor_version", sa.String(30), nullable=False),
        sa.Column("input_template", sa.JSON(), nullable=False),
        sa.Column("dataset_schema_version", sa.String(20), nullable=False),
        sa.Column("refresh_strategy", sa.String(30), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False))
    op.create_table("intelligence_ingestion_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("source_id", sa.String(60), index=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("deduplicated_count", sa.Integer(), nullable=False),
        sa.Column("validation_failures", sa.Integer(), nullable=False),
        sa.Column("quality", sa.JSON(), nullable=False),
        sa.Column("normalization_version", sa.String(20), nullable=False),
        sa.Column("extractor_version", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True))
    op.create_table("source_observations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("source_id", sa.String(60), index=True),
        sa.Column("ingestion_run_id", sa.String(32), index=True),
        sa.Column("external_id", sa.String(200), nullable=True),
        sa.Column("content_hash", sa.String(64), index=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("geography", sa.String(60), nullable=False),
        sa.Column("geography_level", sa.String(20), nullable=False),
        sa.Column("occupation_refs", sa.JSON(), nullable=False),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("signal_type", sa.String(40), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("source_quality", sa.Float(), nullable=False),
        sa.Column("raw_reference", sa.String(400), nullable=True))
    op.create_table("market_signals",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("occupation_id", sa.String(60), index=True),
        sa.Column("construct", sa.String(40), nullable=False),
        sa.Column("geography", sa.String(60), nullable=False),
        sa.Column("geography_level", sa.String(20), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("source_diversity", sa.Integer(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("conflicts", sa.JSON(), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=True),
        sa.Column("window_end", sa.DateTime(), nullable=True),
        sa.Column("snapshot_version", sa.String(40), index=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("targeted_refresh_requests",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("occupation_id", sa.String(60), nullable=True),
        sa.Column("query_terms", sa.JSON(), nullable=False),
        sa.Column("geography", sa.String(60), nullable=False),
        sa.Column("reason", sa.String(60), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("opportunity_market_snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), index=True),
        sa.Column("recommendation_set_id", sa.String(32), nullable=True),
        sa.Column("profile_version_id", sa.String(32), nullable=True),
        sa.Column("market_snapshot_version", sa.String(40), nullable=False),
        sa.Column("ranking_model_version", sa.String(40), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))


def downgrade() -> None:
    for t in ("opportunity_market_snapshots", "targeted_refresh_requests", "market_signals",
              "source_observations", "intelligence_ingestion_runs", "apify_actor_configs",
              "intelligence_sources", "license_requirements", "problems", "industries",
              "occupation_transitions", "occupation_capabilities", "capabilities",
              "occupation_external_mappings", "occupation_aliases", "occupations"):
        op.drop_table(t)
