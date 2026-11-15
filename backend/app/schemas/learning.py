from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TopicSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    category: str
    category_label: str
    title: str
    summary: str
    sort_order: int
    completed: bool = False
    reading_position: float = 0.0


class TopicDetail(TopicSummary):
    content_md: str


class ProgressRead(BaseModel):
    topic_id: str
    reading_position: float
    completed: bool
    updated_at: datetime | None = None


class ProgressUpdate(BaseModel):
    reading_position: float | None = Field(default=None, ge=0, le=1)
    completed: bool | None = None

    @model_validator(mode="after")
    def not_empty(self) -> "ProgressUpdate":
        if self.reading_position is None and self.completed is None:
            raise ValueError("必须提供阅读位置或完成状态")
        return self


class Overview(BaseModel):
    total_topics: int
    completed_topics: int
    started_topics: int
    next_topic_id: str | None = None
    next_topic_title: str | None = None
