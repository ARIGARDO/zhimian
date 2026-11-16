"""Track one recovery grace window without changing user activity time."""
from alembic import op
import sqlalchemy as sa

revision = '0007_interview_model_grace'
down_revision = '0006_interview_ai'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('interviews', sa.Column('model_grace_until', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('interviews', 'model_grace_until')
