"""capacity_type is part of an observation's identity

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

BASE = ["metric", "entity_id", "period_start", "period_end", "period_type", "value_type"]
LIVE = sa.text("superseded_by IS NULL")


def upgrade():
    op.drop_index("uq_obs_live_fact", table_name="observations")
    op.create_index("uq_obs_live_fact", "observations",
                    BASE + [sa.text("coalesce(capacity_type, '')"), "source_id"], unique=True,
                    sqlite_where=LIVE, postgresql_where=LIVE)


def downgrade():
    op.drop_index("uq_obs_live_fact", table_name="observations")
    op.create_index("uq_obs_live_fact", "observations", BASE + ["source_id"], unique=True,
                    sqlite_where=LIVE, postgresql_where=LIVE)
