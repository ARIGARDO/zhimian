"""Persist idempotency for interview creation."""
from alembic import op
import sqlalchemy as sa

revision = '0005_interview_create_key'
down_revision = '0004_interview_followups'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('interviews', sa.Column('create_key', sa.String(100), nullable=True))
    op.add_column('interviews', sa.Column('create_hash', sa.String(64), nullable=True))
    op.create_unique_constraint('uq_interviews_create_key', 'interviews', ['create_key'])


def downgrade():
    op.drop_constraint('uq_interviews_create_key', 'interviews', type_='unique')
    op.drop_column('interviews', 'create_hash')
    op.drop_column('interviews', 'create_key')
