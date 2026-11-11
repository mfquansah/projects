"""ingest run log columns

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ingest_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('finished_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('rows_superseded', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('rows_unchanged', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('detail', sa.JSON(), nullable=True))
        # Alembic does not autogenerate CHECK constraints, so this one is added by hand.
        batch_op.create_check_constraint(
            'ck_ingest_runs_status', "status IN ('running', 'success', 'no_change', 'failed')")



def downgrade():
    with op.batch_alter_table('ingest_runs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_ingest_runs_status', type_='check')
        batch_op.drop_column('detail')
        batch_op.drop_column('rows_unchanged')
        batch_op.drop_column('rows_superseded')
        batch_op.drop_column('finished_at')

