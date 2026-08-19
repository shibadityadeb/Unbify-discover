"""materialization: material objects, experiments, product routes, snapshots

Revision ID: 0006_materialization
Revises: 0005_world_intelligence
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_materialization"
down_revision = "0005_world_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("material_objects",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("discover_sessions.id"), index=True),
        sa.Column("kind", sa.String(30), index=True),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("saved", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("dismissal_reason", sa.String(200), nullable=True),
        sa.Column("materialization_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("uq_material_key", "material_objects",
                    ["session_id", "kind", "key"], unique=True)
    op.create_table("experiment_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("discover_sessions.id"), index=True),
        sa.Column("material_object_id", sa.String(32), nullable=True),
        sa.Column("direction_key", sa.String(120), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("teaches", sa.Text(), nullable=False),
        sa.Column("effort", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("outcome", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True))
    op.create_table("product_routes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("discover_sessions.id"), index=True),
        sa.Column("capability", sa.String(30), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("prerequisite_states", sa.JSON(), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column("explanation_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("user_need", sa.Text(), nullable=False),
        sa.Column("gap", sa.Text(), nullable=False),
        sa.Column("shown_at", sa.DateTime(), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("materialization_snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("discover_sessions.id"), index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("profile_version_id", sa.String(32), nullable=True),
        sa.Column("recommendation_set_id", sa.String(32), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))


def downgrade() -> None:
    for t in ("materialization_snapshots", "product_routes", "experiment_runs", "material_objects"):
        op.drop_table(t)
