"""request latency samples for p50/p95/p99 monitoring

Revision ID: 0008_latency
Revises: 0007_realtime_intelligence
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_latency"
down_revision = "0007_realtime_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("request_latency",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), nullable=True, index=True),
        sa.Column("kind", sa.String(40), index=True),
        sa.Column("total_ms", sa.Integer(), nullable=False),
        sa.Column("phases", sa.JSON(), nullable=False),
        sa.Column("over_budget", sa.JSON(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True))


def downgrade() -> None:
    op.drop_table("request_latency")
