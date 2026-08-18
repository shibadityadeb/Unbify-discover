"""pgvector support — postgres only, no-op on other dialects

Revision ID: 0002_pgvector
Revises: f11446d6b359
"""
from alembic import op

revision = "0002_pgvector"
down_revision = "f11446d6b359"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    conn.exec_driver_sql("ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS embedding_vec vector(384)")
    conn.exec_driver_sql("ALTER TABLE profile_versions ADD COLUMN IF NOT EXISTS embedding_vec vector(384)")
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_opportunities_embedding "
        "ON opportunities USING ivfflat (embedding_vec vector_cosine_ops) WITH (lists = 50)")


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    conn.exec_driver_sql("DROP INDEX IF EXISTS idx_opportunities_embedding")
    conn.exec_driver_sql("ALTER TABLE opportunities DROP COLUMN IF EXISTS embedding_vec")
    conn.exec_driver_sql("ALTER TABLE profile_versions DROP COLUMN IF EXISTS embedding_vec")
