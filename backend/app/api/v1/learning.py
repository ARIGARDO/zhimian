from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.learning import Overview, ProgressRead, ProgressUpdate, TopicDetail, TopicSummary
from app.services import learning

router = APIRouter(tags=["learning"])
Database = Annotated[AsyncSession, Depends(get_db)]


@router.get("/topics", response_model=list[TopicSummary])
async def list_topics(db: Database):
    return await learning.list_topics(db)


@router.get("/topics/{topic_id}", response_model=TopicDetail)
async def get_topic(topic_id: str, db: Database):
    return await learning.get_topic_detail(db, topic_id)


@router.get("/progress/{topic_id}", response_model=ProgressRead)
async def get_progress(topic_id: str, db: Database):
    return await learning.get_progress(db, topic_id)


@router.patch("/progress/{topic_id}", response_model=ProgressRead)
async def patch_progress(topic_id: str, body: ProgressUpdate, db: Database):
    return await learning.update_progress(db, topic_id, body)


@router.get("/overview", response_model=Overview)
async def overview(db: Database):
    return await learning.get_overview(db)
