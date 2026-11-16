"""面试 HTTP 接口；状态变更统一委托 InterviewService。"""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.interview import Interview, InterviewPreset, InterviewQuestionBank
from app.services.interview import InterviewService, recommended_rules

router = APIRouter(tags=['interviews'])
Database = Annotated[AsyncSession, Depends(get_db)]
Key = Annotated[str, Header(alias='Idempotency-Key', min_length=1, max_length=100, pattern=r'^[A-Za-z0-9._:-]+$')]


class CreateInterview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    preset_id: str = Field(min_length=1, max_length=36)
    mode: Literal['practice', 'formal']
    limit_type: Literal['count', 'time']
    main_limit: int | None = Field(default=None, ge=3, strict=True)
    duration_seconds: int | None = Field(default=None, gt=0, strict=True)
    jd: str | None = Field(default=None, max_length=5000)


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question_id: str = Field(min_length=1, max_length=36)
    content: str = Field(default='', max_length=12000)
    skip: bool = Field(default=False, strict=True)


class CloseRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question_id: str = Field(min_length=1, max_length=36)


def service(db: AsyncSession) -> InterviewService:
    return InterviewService(db, recommended_rules())


def state_result(result: dict) -> dict:
    # 到期结果已在服务层提交；使用响应对象避免抛异常引起事务回滚。
    if result.get('end_reason'):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=409, content=result)
    return result


@router.get('/interview-presets')
async def presets(db: Database):
    items = (await db.scalars(select(InterviewPreset).where(InterviewPreset.active.is_(True)).order_by(InterviewPreset.name, InterviewPreset.id))).all()
    return [{'id': p.id, 'kind': p.kind, 'name': p.name, 'version': p.version} for p in items]


@router.get('/interview-presets/{preset_id}/questions')
async def preset_questions(preset_id: str, db: Database):
    preset = await db.get(InterviewPreset, preset_id)
    if not preset or not preset.active: raise HTTPException(404, '预设不存在或不可用')
    items = (await db.scalars(select(InterviewQuestionBank).where(InterviewQuestionBank.preset_id == preset_id, InterviewQuestionBank.active.is_(True)).order_by(InterviewQuestionBank.id))).all()
    return [{'id': q.id, 'topic': q.topic, 'version': q.version} for q in items]


@router.post('/interviews', status_code=201)
async def create_interview(body: CreateInterview, db: Database, key: Key):
    return await service(db).create_from_preset(key=key, **body.model_dump())


@router.get('/interviews')
async def list_interviews(db: Database, status: Literal['completed','incomplete','pending','in_progress'] | None = None, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    stmt = select(Interview).order_by(Interview.created_at.desc(), Interview.id.desc()).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(Interview.status.in_(['terminated','interrupted']) if status == 'incomplete' else Interview.status == status)
    items = (await db.scalars(stmt)).all()
    return [{'id': i.id, 'status': i.status, 'mode': i.mode, 'preset': i.preset_snapshot, 'created_at': i.created_at, 'ended_at': i.ended_at} for i in items]


@router.get('/interviews/{interview_id}')
async def interview_detail(interview_id: str, db: Database):
    return await service(db).detail(interview_id)


@router.post('/interviews/{interview_id}/start')
async def start(interview_id: str, db: Database, key: Key):
    return state_result(await service(db).start(interview_id, key))


@router.post('/interviews/{interview_id}/questions/next')
async def next_question(interview_id: str, db: Database, key: Key):
    return state_result(await service(db).next_question(interview_id, key))


@router.post('/interviews/{interview_id}/answers')
async def answer(interview_id: str, body: AnswerRequest, db: Database, key: Key):
    return state_result(await service(db).answer(interview_id, key, **body.model_dump()))


@router.post('/interviews/{interview_id}/questions/close')
async def close_question(interview_id: str, body: CloseRequest, db: Database, key: Key):
    # 正常关闭最后一题可能完成或终止，是成功的操作。
    return state_result(await service(db).close_main(interview_id, key, question_id=body.question_id))


@router.post('/interviews/{interview_id}/terminate')
async def terminate(interview_id: str, db: Database, key: Key):
    return state_result(await service(db).end(interview_id, key, 'terminated', 'user_terminated'))
