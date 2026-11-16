"""Allow two sibling follow-ups while preserving existing question order."""
from alembic import op
import sqlalchemy as sa

revision = '0004_interview_followups'
down_revision = '0003_interviews'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('interview_questions', sa.Column('position', sa.Integer(), nullable=True))
    # 0003 allowed only one question at each depth, so depth preserves old order.
    op.execute('UPDATE interview_questions SET position = depth WHERE position IS NULL')
    op.alter_column('interview_questions', 'position', nullable=False)
    op.drop_constraint('uq_iq_position', 'interview_questions', type_='unique')
    op.drop_constraint('ck_iq_position', 'interview_questions', type_='check')
    op.drop_constraint('ck_iq_parent', 'interview_questions', type_='check')
    op.create_unique_constraint('uq_iq_sequence', 'interview_questions', ['interview_id', 'main_number', 'position'])
    op.create_check_constraint('ck_iq_position_v2', 'interview_questions', 'main_number > 0 AND depth BETWEEN 0 AND 2 AND position BETWEEN 0 AND 2')
    op.create_check_constraint('ck_iq_parent', 'interview_questions', '(depth = 0 AND position = 0 AND parent_id IS NULL) OR (depth > 0 AND position > 0 AND parent_id IS NOT NULL)')


def downgrade():
    raise RuntimeError('降级会丢失并列追问语义，请先备份并人工处理数据')
