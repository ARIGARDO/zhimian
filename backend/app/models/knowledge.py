"""可重建的专题章节向量索引；原始文章仍为数据源。"""
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from app.db.base import Base


class KnowledgeChunk(Base):
    __tablename__ = 'knowledge_chunks'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey('topics.id', ondelete='CASCADE'), nullable=False, index=True)
    section: Mapped[str] = mapped_column(String(200), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(150), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    __table_args__ = (UniqueConstraint('topic_id', 'id', name='uq_chunk_topic_id'),)
