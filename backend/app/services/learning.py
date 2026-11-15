from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning import LearningProgress, Topic
from app.schemas.learning import Overview, ProgressRead, ProgressUpdate, TopicDetail, TopicSummary


def topic_summary(topic: Topic, progress: LearningProgress | None) -> TopicSummary:
    return TopicSummary(
        id=topic.id,
        category=topic.category,
        category_label=topic.category_label,
        title=topic.title,
        summary=topic.summary,
        sort_order=topic.sort_order,
        completed=progress.completed if progress else False,
        reading_position=progress.reading_position if progress else 0.0,
    )


async def get_topic_or_404(db: AsyncSession, topic_id: str) -> Topic:
    topic = await db.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="专题不存在")
    return topic


async def list_topics(db: AsyncSession) -> list[TopicSummary]:
    result = await db.execute(
        select(Topic, LearningProgress)
        .outerjoin(LearningProgress, Topic.id == LearningProgress.topic_id)
        .order_by(Topic.sort_order, Topic.id)
    )
    return [topic_summary(topic, progress) for topic, progress in result.all()]


async def get_topic_detail(db: AsyncSession, topic_id: str) -> TopicDetail:
    topic = await get_topic_or_404(db, topic_id)
    progress = await db.get(LearningProgress, topic_id)
    return TopicDetail(**topic_summary(topic, progress).model_dump(), content_md=topic.content_md)


def progress_response(topic_id: str, progress: LearningProgress | None) -> ProgressRead:
    return ProgressRead(
        topic_id=topic_id,
        reading_position=progress.reading_position if progress else 0.0,
        completed=progress.completed if progress else False,
        updated_at=progress.updated_at if progress else None,
    )


async def get_progress(db: AsyncSession, topic_id: str) -> ProgressRead:
    await get_topic_or_404(db, topic_id)
    return progress_response(topic_id, await db.get(LearningProgress, topic_id))


async def update_progress(
    db: AsyncSession, topic_id: str, body: ProgressUpdate
) -> ProgressRead:
    await get_topic_or_404(db, topic_id)
    values: dict[str, object] = {"topic_id": topic_id}
    update_values: dict[str, object] = {}
    if body.reading_position is not None:
        values["reading_position"] = body.reading_position
        update_values["reading_position"] = body.reading_position
    if body.completed is not None:
        values["completed"] = body.completed
        update_values["completed"] = body.completed
    update_values["updated_at"] = func.now()
    statement = (
        insert(LearningProgress)
        .values(**values)
        .on_conflict_do_update(index_elements=[LearningProgress.topic_id], set_=update_values)
        .returning(LearningProgress)
    )
    try:
        result = await db.execute(statement)
        progress = result.scalar_one()
        await db.commit()
        await db.refresh(progress)
        return progress_response(topic_id, progress)
    except Exception:
        await db.rollback()
        raise


async def get_overview(db: AsyncSession) -> Overview:
    topics = await list_topics(db)
    unfinished = next((topic for topic in topics if not topic.completed), None)
    return Overview(
        total_topics=len(topics),
        completed_topics=sum(topic.completed for topic in topics),
        started_topics=sum(topic.reading_position > 0 or topic.completed for topic in topics),
        next_topic_id=unfinished.id if unfinished else None,
        next_topic_title=unfinished.title if unfinished else None,
    )
