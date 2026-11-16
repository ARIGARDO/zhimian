"""Add model operation attempts and validated interview artifacts."""
from alembic import op
import sqlalchemy as sa

revision = '0006_interview_ai'
down_revision = '0005_interview_create_key'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('interview_operations', sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'))
    op.create_table('interview_ai_artifacts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('interview_id', sa.String(36), sa.ForeignKey('interviews.id', ondelete='CASCADE'), nullable=False),
        sa.Column('operation_id', sa.String(36), sa.ForeignKey('interview_operations.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('target_id', sa.String(36), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('followup','feedback','report')", name='ck_iai_kind'),
        sa.UniqueConstraint('interview_id','kind','target_id', name='uq_iai_target'))
    op.create_index('ix_interview_ai_artifacts_interview_id', 'interview_ai_artifacts', ['interview_id'])


def downgrade():
    raise RuntimeError('降级会删除 AI 评价数据，请先备份并人工处理')
