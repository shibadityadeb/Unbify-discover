"""profile growth intelligence: posting descriptions for capability penetration

Revision ID: 0012_profile_growth
Revises: 0011_opportunity_intelligence
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_profile_growth"
down_revision = "0011_opportunity_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("market_postings", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("market_postings", "description")
