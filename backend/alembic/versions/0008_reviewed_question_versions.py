"""Add reviewed question versions without modifying existing interview data."""
from alembic import op
import sqlalchemy as sa

revision = '0008_reviewed_question_versions'
down_revision = '0007_interview_model_grace'
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column('content_code', sa.String(40)), sa.Column('difficulty', sa.String(16)),
        sa.Column('sort_order', sa.Integer()), sa.Column('review_status', sa.String(16)),
        sa.Column('review_material', sa.JSON()), sa.Column('reviewed_by', sa.String(100)),
        sa.Column('reviewed_at', sa.DateTime(timezone=True)),
    ): op.add_column('interview_question_bank', column)
    op.create_check_constraint('ck_iqb_review_fields', 'interview_question_bank', "content_code IS NULL OR (difficulty IS NOT NULL AND difficulty IN ('basic','intermediate','challenge') AND sort_order IS NOT NULL AND sort_order >= 0 AND review_status IS NOT NULL AND review_status IN ('draft','approved') AND review_material IS NOT NULL)")
    op.create_check_constraint('ck_iqb_active_approved', 'interview_question_bank', "content_code IS NULL OR NOT active OR (review_status = 'approved' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)")
    op.create_check_constraint('ck_iqb_review_audit', 'interview_question_bank', "content_code IS NULL OR review_status != 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)")
    op.create_unique_constraint('uq_iqb_content_version', 'interview_question_bank', ['preset_id','content_code','version'])
    op.create_index('uq_iqb_active_content', 'interview_question_bank', ['preset_id','content_code'], unique=True, postgresql_where=sa.text('active AND content_code IS NOT NULL'))
    # 已审核版本只允许切换 active；历史引用必须长期可读。
    op.execute('''CREATE FUNCTION protect_reviewed_question() RETURNS trigger AS $$
    BEGIN
      IF OLD.content_code IS NOT NULL AND OLD.review_status = 'approved' THEN
        IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'reviewed question is immutable'; END IF;
        IF (to_jsonb(NEW) - 'active') IS DISTINCT FROM (to_jsonb(OLD) - 'active') THEN
          RAISE EXCEPTION 'reviewed question is immutable';
        END IF;
      END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql''')
    op.execute('CREATE TRIGGER protect_reviewed_question BEFORE UPDATE OR DELETE ON interview_question_bank FOR EACH ROW EXECUTE FUNCTION protect_reviewed_question()')


def downgrade():
    raise RuntimeError('为保护已发布版本及历史引用，不支持自动降级')
