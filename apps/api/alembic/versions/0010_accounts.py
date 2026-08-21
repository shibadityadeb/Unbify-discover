"""accounts: auth columns on users, opaque bearer tokens

Revision ID: 0010_accounts
Revises: 0009_quote_intelligence
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_accounts"
down_revision = "0009_quote_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("name", sa.String(120), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(256), nullable=True))
    op.add_column("users", sa.Column("google_sub", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    op.create_table("auth_tokens",
        sa.Column("token", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))


def downgrade() -> None:
    op.drop_table("auth_tokens")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "google_sub")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "name")
