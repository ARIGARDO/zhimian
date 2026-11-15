from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    category: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    category_label: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)

    progress: Mapped["LearningProgress | None"] = relationship(
        back_populates="topic", uselist=False, cascade="all, delete-orphan"
    )


class LearningProgress(Base):
    __tablename__ = "learning_progress"

    # M1 为单实例单人数据。公网共享使用前必须改为可认证的用户隔离设计。
    topic_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True
    )
    reading_position: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    topic: Mapped[Topic] = relationship(back_populates="progress")
