"""Initial M1 topics and learning_progress tables.

Revision ID: 0001_m1
Revises:
Create Date: 2026-11-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_m1"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "topics",
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("category_label", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_topics_category", "topics", ["category"])
    op.create_table(
        "learning_progress",
        sa.Column("topic_id", sa.String(length=100), sa.ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("reading_position", sa.Float(), nullable=False, server_default="0"),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("reading_position >= 0 AND reading_position <= 1", name="ck_learning_progress_position"),
    )


def downgrade() -> None:
    op.drop_table("learning_progress")
    op.drop_index("ix_topics_category", table_name="topics")
    op.drop_table("topics")
    # 不删除 vector 扩展：它可能被后续迁移或其他 schema 使用。
