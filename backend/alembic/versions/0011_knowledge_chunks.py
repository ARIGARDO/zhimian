"""Add a rebuildable pgvector index without altering source articles."""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = '0011_knowledge_chunks'
down_revision = '0010_chat_sources'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.create_table('knowledge_chunks',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('topic_id', sa.String(100), sa.ForeignKey('topics.id', ondelete='CASCADE'), nullable=False),
        sa.Column('section', sa.String(200), nullable=False),
        sa.Column('excerpt', sa.Text(), nullable=False),
        sa.Column('model', sa.String(150), nullable=False),
        sa.Column('embedding', Vector(384), nullable=False),
        sa.UniqueConstraint('topic_id', 'id', name='uq_chunk_topic_id'))
    op.create_index('ix_knowledge_chunks_topic_id', 'knowledge_chunks', ['topic_id'])


def downgrade():
    op.drop_table('knowledge_chunks')
