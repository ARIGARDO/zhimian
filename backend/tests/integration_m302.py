"""PostgreSQL 并发验收：仅创建并删除本脚本自己的测试场次。"""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import get_engine
from app.models.interview import Interview, InterviewAnswer, InterviewQuestion, InterviewReport
from app.services.interview import InterviewConflict, InterviewService, recommended_rules


async def main():
    engine = get_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = []
    clock = [datetime.now(timezone.utc)]
    async def now(db): return clock[0]
    async def call(method, *args, **kwargs):
        async with factory() as db:
            return await getattr(InterviewService(db, recommended_rules(), now), method)(*args, **kwargs)
    async def make(mode='practice', limit_type='count'):
        cid = await call('create', mode=mode, limit_type=limit_type, main_limit=3 if limit_type == 'count' else None, duration_seconds=60 if limit_type == 'time' else None, preset_snapshot={'test': str(uuid4())}, config_snapshot={})
        ids.append(cid)
        return cid
    async def outcome(awaitable):
        try: return await awaitable
        except InterviewConflict: return 'conflict'
    try:
        cid = await make()
        start = await asyncio.gather(call('start', cid, 'start'), call('start', cid, 'start'))
        assert start[0] == start[1]
        q = await call('add_question', cid, 'q', '并发测试题')
        answers = await asyncio.gather(call('answer', cid, 'a', q['id'], '同一答案'), call('answer', cid, 'a', q['id'], '同一答案'))
        assert answers[0] == answers[1]
        mismatch = await outcome(call('answer', cid, 'a', q['id'], '不同请求体'))
        assert mismatch == 'conflict'
        async with factory() as db:
            assert await db.scalar(select(func.count(InterviewAnswer.id)).where(InterviewAnswer.interview_id == cid)) == 1
        print('PostgreSQL 并发开始、同键提交与不同请求体：通过')

        cid = await make(); await call('start', cid, 's'); q = await call('add_question', cid, 'q', '竞争题')
        result = await asyncio.gather(outcome(call('answer', cid, 'a1', q['id'], '甲')), outcome(call('answer', cid, 'a2', q['id'], '乙')))
        assert sum(x == 'conflict' for x in result) == 1
        async with factory() as db:
            assert await db.scalar(select(func.count(InterviewAnswer.id)).where(InterviewAnswer.interview_id == cid)) == 1
        print('PostgreSQL 同题不同键并发提交：通过')

        cid = await make(); await call('start', cid, 's'); q = await call('add_question', cid, 'q', '终止竞争题')
        result = await asyncio.gather(outcome(call('end', cid, 'end', 'terminated', '测试')), outcome(call('answer', cid, 'a', q['id'], '回答')))
        async with factory() as db:
            item=await db.get(Interview, cid)
            assert item.status == 'terminated'
            count=await db.scalar(select(func.count(InterviewAnswer.id)).where(InterviewAnswer.interview_id == cid))
            assert count in (0, 1)
        assert await outcome(call('answer', cid, 'late', q['id'], '迟到')) == 'conflict'
        print('PostgreSQL 终止与提交竞争、终态拒绝后续写入：通过')

        cid = await make(limit_type='time'); await call('start', cid, 's')
        for i in range(2):
            q=await call('add_question', cid, f'q{i}', '时间题')
            await call('answer', cid, f'a{i}', q['id'], '有效')
            await call('close_main', cid, f'c{i}')
        q=await call('add_question', cid, 'q3', '边界题')
        clock[0] += timedelta(seconds=60)
        result=await asyncio.gather(outcome(call('answer', cid, 'late', q['id'], '边界回答')), outcome(call('check_expiry', cid)))
        async with factory() as db:
            assert (await db.get(Interview,cid)).status == 'completed'
            assert await db.scalar(select(func.count(InterviewAnswer.id)).where(InterviewAnswer.question_id == q['id'])) == 0
        print('PostgreSQL 截止瞬间提交与到期竞争：通过')

        # 单独用数据库时钟验证过期提交与惰性到期检查竞争。
        async def real_call(method, *args, **kwargs):
            async with factory() as db:
                return await getattr(InterviewService(db, recommended_rules()), method)(*args, **kwargs)
        real_id=await real_call('create', mode='practice', limit_type='time', main_limit=None, duration_seconds=60, preset_snapshot={'test': str(uuid4())}, config_snapshot={})
        ids.append(real_id)
        await real_call('start', real_id, 's')
        for i in range(2):
            rq=await real_call('add_question', real_id, f'q{i}', '真实时钟题')
            await real_call('answer', real_id, f'a{i}', rq['id'], '有效')
            await real_call('close_main', real_id, f'c{i}')
        rq=await real_call('add_question', real_id, 'q3', '到期题')
        async with factory() as db:
            async with db.begin():
                item=await db.get(Interview, real_id)
                item.deadline_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        await asyncio.gather(outcome(real_call('answer', real_id, 'late', rq['id'], '超时')), outcome(real_call('check_expiry', real_id)))
        async with factory() as db:
            assert (await db.get(Interview,real_id)).status == 'completed'
            assert await db.scalar(select(func.count(InterviewAnswer.id)).where(InterviewAnswer.question_id == rq['id'])) == 0
        print('PostgreSQL 数据库时钟到期与提交竞争：通过')

        other=await make(); await call('start', other, 's')
        other_q=await call('add_question', other, 'q', '其他场题')
        target=await make(); await call('start', target, 's')
        await call('add_question', target, 'q', '目标场题')
        assert await outcome(call('add_question', target, 'bad', '跨场追问', other_q['id'])) == 'conflict'
        async with factory() as db:
            try:
                async with db.begin():
                    db.add(InterviewQuestion(interview_id=target, parent_id=other_q['id'], main_number=1, depth=1, content='跨场', source_snapshot={}))
                    await db.flush()
            except IntegrityError: pass
            else: raise AssertionError('跨场父题外键约束失效')
        async with factory() as db:
            try:
                async with db.begin():
                    db.add(InterviewReport(interview_id=other, type='partial', status='ready', overall_score=1.0))
                    await db.flush()
            except IntegrityError: pass
            else: raise AssertionError('部分报告分数约束失效')
        print('PostgreSQL 跨场题目及部分报告评分约束：通过')
    finally:
        async with factory() as db:
            async with db.begin(): await db.execute(delete(Interview).where(Interview.id.in_(ids)))
        await engine.dispose()
        print('本次 PostgreSQL 测试场次已清理')

asyncio.run(main())
