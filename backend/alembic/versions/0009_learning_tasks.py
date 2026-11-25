"""Add explicitly confirmed learning tasks without changing existing data."""
from alembic import op
import sqlalchemy as sa

revision = '0009_learning_tasks'
down_revision = '0008_reviewed_question_versions'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'learning_tasks',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('interview_id', sa.String(36), sa.ForeignKey('interviews.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('answer_id', sa.String(36), sa.ForeignKey('interview_answers.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('topic_id', sa.String(100), sa.ForeignKey('topics.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='todo'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('todo', 'in_progress', 'completed')", name='ck_learning_task_status'),
        sa.UniqueConstraint('interview_id', 'answer_id', 'topic_id', name='uq_learning_task_source'),
    )


def downgrade():
    raise RuntimeError('学习任务包含用户数据，不支持自动降级')
