"""用户确认后的学习任务，来源为已经生成的面试复盘。"""
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.interview import InterviewAnswer
from app.models.learning import LearningTask, Topic
from app.services.interview_ai import InterviewAIService

router = APIRouter(tags=['learning tasks'])
Database = Annotated[AsyncSession, Depends(get_db)]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    interview_id: str = Field(min_length=1, max_length=36)
    answer_id: str = Field(min_length=1, max_length=36)
    topic_id: str = Field(min_length=1, max_length=100)


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['todo', 'in_progress', 'completed']


def serialize(task: LearningTask, topic: Topic) -> dict:
    return {'id': task.id, 'interview_id': task.interview_id, 'answer_id': task.answer_id,
            'topic_id': task.topic_id, 'topic_title': topic.title, 'status': task.status,
            'created_at': task.created_at}


@router.get('/tasks')
async def list_tasks(db: Database):
    rows = (await db.execute(select(LearningTask, Topic).join(Topic).order_by(LearningTask.created_at.desc(), LearningTask.id))).all()
    return [serialize(task, topic) for task, topic in rows]


@router.post('/tasks', status_code=201)
async def create_task(body: TaskCreate, db: Database):
    # 只接受真实复盘中的回答，用户明确选择专题才创建任务。
    report = await InterviewAIService().get_report(body.interview_id)
    if report.get('status') != 'ready' or body.answer_id not in {item['answer_id'] for item in report['result']['items']}:
        raise HTTPException(409, '该回答尚无可用复盘')
    answer = await db.get(InterviewAnswer, body.answer_id)
    topic = await db.get(Topic, body.topic_id)
    if not answer or answer.interview_id != body.interview_id or not topic:
        raise HTTPException(404, '回答或专题不存在')
    insert = pg_insert if db.bind.dialect.name == 'postgresql' else sqlite_insert
    statement = insert(LearningTask).values(id=str(uuid4()), **body.model_dump(), status='todo').on_conflict_do_nothing(index_elements=['interview_id', 'answer_id', 'topic_id'])
    await db.execute(statement)
    await db.commit()
    task = await db.scalar(select(LearningTask).where(LearningTask.interview_id == body.interview_id, LearningTask.answer_id == body.answer_id, LearningTask.topic_id == body.topic_id))
    return serialize(task, topic)


@router.patch('/tasks/{task_id}')
async def update_task(task_id: str, body: TaskUpdate, db: Database):
    task = await db.get(LearningTask, task_id)
    if not task:
        raise HTTPException(404, '任务不存在')
    task.status = body.status
    await db.commit()
    return serialize(task, await db.get(Topic, task.topic_id))
