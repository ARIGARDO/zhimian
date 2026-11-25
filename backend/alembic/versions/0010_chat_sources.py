"""Keep the actual knowledge passages supplied to chat for later inspection."""
from alembic import op
import sqlalchemy as sa

revision = '0010_chat_sources'
down_revision = '0009_learning_tasks'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('messages', sa.Column('sources', sa.JSON(), nullable=True))


def downgrade():
    raise RuntimeError('引用包含历史消息的来源记录，不支持自动降级')
