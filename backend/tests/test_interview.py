from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.interview import Interview, InterviewReport
from app.services.interview import InterviewConflict, InterviewService, recommended_rules


@pytest_asyncio.fixture
async def env(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'interview.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    async def now(db): return clock[0]
    def service(): return InterviewService(factory(), recommended_rules(), now)
    yield factory, clock, service
    await engine.dispose()


async def create(service, mode='practice', limit_type='count'):
    async with service.db:
        return await service.create(mode=mode, limit_type=limit_type, main_limit=3 if limit_type == 'count' else None, duration_seconds=60 if limit_type == 'time' else None, preset_snapshot={'version': 1}, config_snapshot={})


async def call(service, method, *args, **kwargs):
    async with service.db:
        return await getattr(service, method)(*args, **kwargs)


@pytest.mark.asyncio
async def test_count_followups_skip_and_idempotency(env):
    factory, clock, svc = env
    cid = await create(svc())
    first = await call(svc(), 'start', cid, 'start')
    clock[0] += timedelta(seconds=3)
    assert await call(svc(), 'start', cid, 'start') == first
    assert (await call(svc(), 'start', cid, 'start-again'))['started_at'] == first['started_at']
    q = await call(svc(), 'add_question', cid, 'q1', '主问题')
    ans = await call(svc(), 'answer', cid, 'a1', q['id'], '回答')
    assert await call(svc(), 'answer', cid, 'a1', q['id'], '回答') == ans
    with pytest.raises(InterviewConflict, match='不同请求'):
        await call(svc(), 'answer', cid, 'a1', q['id'], '不同回答')
    with pytest.raises(InterviewConflict): await call(svc(), 'answer', cid, 'a1-other', q['id'], '回答')
    follow = await call(svc(), 'add_question', cid, 'f1', '追问一', q['id'])
    assert follow['depth'] == 1 and follow['main_number'] == 1
    assert (await call(svc(), 'answer', cid, 'a2', follow['id'], '补充'))['valid_main_count'] == 1
    follow2 = await call(svc(), 'add_question', cid, 'f2', '追问二', follow['id'])
    await call(svc(), 'answer', cid, 'a3', follow2['id'], '补充二')
    with pytest.raises(InterviewConflict): await call(svc(), 'add_question', cid, 'f3', '追问三', follow2['id'])
    assert (await call(svc(), 'close_main', cid, 'close1'))['status'] == 'in_progress'
    q2 = await call(svc(), 'add_question', cid, 'q2', '第二题')
    await call(svc(), 'answer', cid, 'a4', q2['id'], '有效答案')
    await call(svc(), 'close_main', cid, 'close2')
    q3 = await call(svc(), 'add_question', cid, 'q3', '第三题')
    assert (await call(svc(), 'answer', cid, 'skip', q3['id'], skip=True))['valid_main_count'] == 2
    async with factory() as db: assert (await db.get(Interview, cid)).status == 'in_progress'
    result = await call(svc(), 'close_main', cid, 'close3')
    assert result == {'status': 'completed', 'outcome': 'completed'}
    with pytest.raises(InterviewConflict): await call(svc(), 'answer', cid, 'late', q3['id'], '迟到')
    with pytest.raises(InterviewConflict): await call(svc(), 'end', cid, 'end', 'terminated', '结束')
    await call(svc(), 'add_report_placeholder', cid, 'full')
    with pytest.raises(InterviewConflict): await call(svc(), 'add_report_placeholder', cid, 'partial')


@pytest.mark.asyncio
async def test_insufficient_and_formal_skip_and_report(env):
    factory, clock, svc = env
    cid = await create(svc(), mode='formal')
    with pytest.raises(InterviewConflict): await call(svc(), 'end', cid, 'before', 'terminated', '提前')
    await call(svc(), 'start', cid, 's')
    q = await call(svc(), 'add_question', cid, 'q', '主问题')
    with pytest.raises(InterviewConflict): await call(svc(), 'answer', cid, 'skip', q['id'], skip=True)
    with pytest.raises(InterviewConflict): await call(svc(), 'answer', cid, 'empty', q['id'], '  ')
    done = await call(svc(), 'end', cid, 'end', 'terminated', '主动结束')
    assert done == await call(svc(), 'end', cid, 'end', 'terminated', '主动结束')
    assert (await call(svc(), 'end', cid, 'end2', 'terminated', '重复'))['status'] == 'terminated'
    with pytest.raises(InterviewConflict): await call(svc(), 'end', cid, 'other', 'interrupted', '异常')
    with pytest.raises(InterviewConflict): await call(svc(), 'start', cid, 'restart')
    with pytest.raises(InterviewConflict): await call(svc(), 'add_report_placeholder', cid, 'full')
    rid = await call(svc(), 'add_report_placeholder', cid, 'partial')
    async with factory() as db:
        report = await db.get(InterviewReport, rid)
        assert report.overall_score is None and report.text_review is None and report.status == 'not_requested'


@pytest.mark.asyncio
async def test_time_expiry_boundary_and_evidence(env):
    factory, clock, svc = env
    cid = await create(svc(), limit_type='time')
    await call(svc(), 'start', cid, 's')
    for i in range(2):
        q = await call(svc(), 'add_question', cid, f'q{i}', '问题')
        clock[0] += timedelta(seconds=10)
        await call(svc(), 'answer', cid, f'a{i}', q['id'], '有效回答')
        await call(svc(), 'close_main', cid, f'c{i}')
    q = await call(svc(), 'add_question', cid, 'q3', '问题')
    clock[0] = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=60)
    assert (await call(svc(), 'answer', cid, 'late', q['id'], '超时')) == {'status': 'completed', 'outcome': 'completed'}
    async with factory() as db:
        item = await db.get(Interview, cid)
        assert item.status == 'completed' and item.valid_main_count == 2
    cid2 = await create(svc(), limit_type='time'); await call(svc(), 'start', cid2, 's')
    clock[0] += timedelta(seconds=60)
    assert (await call(svc(), 'check_expiry', cid2)) == {'status': 'in_progress', 'outcome': 'expired_insufficient_evidence'}
    assert (await call(svc(), 'add_question', cid2, 'late', '问题'))['outcome'] == 'expired_insufficient_evidence'
    assert (await call(svc(), 'end', cid2, 'end', 'interrupted', '人为确认异常'))['status'] == 'interrupted'


@pytest.mark.asyncio
async def test_cross_interview_parent_and_inactivity(env):
    factory, clock, svc = env
    a = await create(svc()); b = await create(svc())
    await call(svc(), 'start', a, 'start'); await call(svc(), 'start', b, 'start')
    qa = await call(svc(), 'add_question', a, 'q', '甲')
    await call(svc(), 'answer', a, 'a', qa['id'], '甲答案')
    await call(svc(), 'add_question', b, 'q', '乙')
    with pytest.raises(InterviewConflict): await call(svc(), 'add_question', b, 'x', '跨场追问', qa['id'])
    with pytest.raises(InterviewConflict): await call(svc(), 'answer', b, 'x', qa['id'], '跨场回答')
    clock[0] += timedelta(minutes=30)
    assert await call(svc(), 'check_inactivity', a)
    async with factory() as db: assert (await db.get(Interview, a)).status == 'in_progress'


@pytest.mark.asyncio
async def test_count_limit_with_insufficient_evidence(env):
    factory, clock, svc = env
    cid = await create(svc())
    await call(svc(), 'start', cid, 'start')
    for i in range(3):
        q = await call(svc(), 'add_question', cid, f'q{i}', '问题')
        await call(svc(), 'answer', cid, f'a{i}', q['id'], skip=True)
        result = await call(svc(), 'close_main', cid, f'close{i}')
    assert result == {'status': 'in_progress', 'outcome': 'insufficient_evidence'}
    async with factory() as db:
        item = await db.get(Interview, cid)
        assert item.main_count == 3 and item.valid_main_count == 0
    with pytest.raises(InterviewConflict): await call(svc(), 'add_question', cid, 'extra', '超额题')
    with pytest.raises(InterviewConflict): await call(svc(), 'add_report_placeholder', cid, 'full')


@pytest.mark.asyncio
async def test_config_validation_and_just_before_deadline(env):
    factory, clock, svc = env
    with pytest.raises(InterviewConflict):
        async with svc().db as db:
            await InterviewService(db, recommended_rules()).create(mode='practice', limit_type='count', main_limit=2, duration_seconds=None, preset_snapshot={}, config_snapshot={})
    with pytest.raises(InterviewConflict):
        async with svc().db as db:
            await InterviewService(db, recommended_rules()).create(mode='practice', limit_type='time', main_limit=None, duration_seconds=60, preset_snapshot={}, config_snapshot={}, jd='x' * 5001)
    cid = await create(svc(), limit_type='time')
    await call(svc(), 'start', cid, 's')
    q = await call(svc(), 'add_question', cid, 'q', '边界题')
    clock[0] += timedelta(seconds=59, milliseconds=999)
    assert (await call(svc(), 'answer', cid, 'a', q['id'], '及时提交'))['valid_main_count'] == 1
    clock[0] += timedelta(milliseconds=1)
    assert (await call(svc(), 'check_expiry', cid))['outcome'] == 'expired_insufficient_evidence'


@pytest.mark.asyncio
async def test_rule_snapshot_prevents_mid_session_changes(env):
    from dataclasses import replace
    factory, clock, svc = env
    cid = await create(svc())
    async with factory() as db:
        service = InterviewService(db, replace(recommended_rules(), min_valid_main=1))
        with pytest.raises(InterviewConflict, match='快照'):
            await service.start(cid, 'start')
    assert (await call(svc(), 'start', cid, 'start'))['status'] == 'in_progress'
