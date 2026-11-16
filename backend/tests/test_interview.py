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
    with pytest.raises(InterviewConflict): await call(svc(), 'add_report_placeholder', cid, 'partial')
    cid2 = await create(svc())
    await call(svc(), 'start', cid2, 's')
    q2 = await call(svc(), 'add_question', cid2, 'q', '问题')
    await call(svc(), 'answer', cid2, 'a', q2['id'], '有效回答')
    await call(svc(), 'end', cid2, 'end', 'interrupted', '异常')
    rid = await call(svc(), 'add_report_placeholder', cid2, 'partial')
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
    assert (await call(svc(), 'answer', cid, 'late', q['id'], '超时')) == {'status': 'completed', 'outcome': 'completed', 'end_reason': 'time_limit'}
    async with factory() as db:
        item = await db.get(Interview, cid)
        assert item.status == 'completed' and item.valid_main_count == 2
    cid2 = await create(svc(), limit_type='time'); await call(svc(), 'start', cid2, 's')
    clock[0] += timedelta(seconds=60)
    assert (await call(svc(), 'check_expiry', cid2)) == {'status': 'terminated', 'outcome': 'terminated'}
    with pytest.raises(InterviewConflict): await call(svc(), 'add_question', cid2, 'late', '问题')
    with pytest.raises(InterviewConflict): await call(svc(), 'end', cid2, 'end', 'interrupted', '人为确认异常')


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
    async with factory() as db: assert (await db.get(Interview, a)).status == 'interrupted'


@pytest.mark.asyncio
async def test_count_limit_with_insufficient_evidence(env):
    factory, clock, svc = env
    cid = await create(svc())
    await call(svc(), 'start', cid, 'start')
    for i in range(3):
        q = await call(svc(), 'add_question', cid, f'q{i}', '问题')
        await call(svc(), 'answer', cid, f'a{i}', q['id'], skip=True)
        result = await call(svc(), 'close_main', cid, f'close{i}')
    assert result == {'status': 'terminated', 'outcome': 'terminated'}
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
            await InterviewService(db, recommended_rules()).create(mode='practice', limit_type='time', main_limit=None, duration_seconds=60, preset_snapshot={'kind':'role'}, config_snapshot={}, jd='x' * 5001)
    cid = await create(svc(), limit_type='time')
    await call(svc(), 'start', cid, 's')
    q = await call(svc(), 'add_question', cid, 'q', '边界题')
    clock[0] += timedelta(seconds=59, milliseconds=999)
    assert (await call(svc(), 'answer', cid, 'a', q['id'], '及时提交'))['valid_main_count'] == 1
    clock[0] += timedelta(milliseconds=1)
    assert (await call(svc(), 'check_expiry', cid))['outcome'] == 'terminated'


@pytest.mark.asyncio
async def test_rule_snapshot_prevents_mid_session_changes(env):
    from dataclasses import replace
    factory, clock, svc = env
    cid = await create(svc())
    async with factory() as db:
        with pytest.raises(ValueError, match='规则'):
            InterviewService(db, replace(recommended_rules(), min_valid_main=1))
    assert (await call(svc(), 'start', cid, 'start'))['status'] == 'in_progress'


@pytest.mark.asyncio
async def test_reused_session_refreshes_terminal_status(env):
    factory, clock, svc = env
    cid = await create(svc())
    await call(svc(), 'start', cid, 's')
    async with factory() as stale:
        old = await stale.get(Interview, cid)
        await stale.commit()
        assert old.status == 'in_progress'
        await call(svc(), 'end', cid, 'end', 'terminated', '结束')
        async with stale:
            with pytest.raises(InterviewConflict):
                await InterviewService(stale, recommended_rules()).add_question(cid, 'late', '题目')


@pytest.mark.asyncio
@pytest.mark.parametrize('valid_count',[0, 1, 2])
@pytest.mark.parametrize('limit_type',['time','count'])
async def test_confirmed_completion_matrix(env, valid_count, limit_type):
    factory, clock, svc = env
    cid = await create(svc(), limit_type=limit_type)
    await call(svc(), 'start', cid, 'start')
    total = 3 if limit_type == 'count' else valid_count
    for i in range(total):
        q = await call(svc(), 'add_question', cid, f'q{i}', '问题')
        await call(svc(), 'answer', cid, f'a{i}', q['id'], '不知道' if i < valid_count else '', skip=i >= valid_count)
        result = await call(svc(), 'close_main', cid, f'c{i}')
    if limit_type == 'time':
        clock[0] += timedelta(seconds=60)
        result = await call(svc(), 'check_expiry', cid)
    assert result['status'] == ('completed' if valid_count == 2 else 'terminated')
    async with factory() as db:
        item = await db.get(Interview, cid)
        assert item.valid_main_count == valid_count
        assert item.end_reason == (f'{limit_type}_limit' if valid_count == 2 else f'{limit_type}_limit_insufficient_evidence')
    with pytest.raises(InterviewConflict): await call(svc(), 'add_question', cid, 'late', '迟到')


@pytest.mark.asyncio
@pytest.mark.parametrize(('text','valid'), [('   ',False),('！！！...？',False),('🙂',False),('不知道',True),('不会',True),('1+1=3',True),('A' * 12001,False),('a\x00',False)])
async def test_valid_answer_rules(env, text, valid):
    factory, clock, svc = env
    cid=await create(svc()); await call(svc(),'start',cid,'s')
    q=await call(svc(),'add_question',cid,'q','题')
    if valid:
        assert (await call(svc(),'answer',cid,'a',q['id'],text))['valid_main_count']==1
    else:
        with pytest.raises(InterviewConflict): await call(svc(),'answer',cid,'a',q['id'],text)


@pytest.mark.asyncio
async def test_two_sibling_followups_total_and_main_count(env):
    factory, clock, svc=env
    cid=await create(svc()); await call(svc(),'start',cid,'s')
    q=await call(svc(),'add_question',cid,'q','主问题')
    await call(svc(),'answer',cid,'a',q['id'],'不会')
    f1=await call(svc(),'add_question',cid,'f1','追问一',q['id'])
    assert f1['depth']==1
    assert (await call(svc(),'answer',cid,'a1',f1['id'],'补充'))['valid_main_count']==1
    f2=await call(svc(),'add_question',cid,'f2','追问二',q['id'])
    assert f2['depth']==1
    assert (await call(svc(),'answer',cid,'a2',f2['id'],'补充'))['valid_main_count']==1
    with pytest.raises(InterviewConflict): await call(svc(),'add_question',cid,'f3','追问三',f2['id'])
    async with factory() as db: assert (await db.get(Interview,cid)).main_count==1


@pytest.mark.asyncio
async def test_inactivity_poll_running_operation_and_legacy_snapshot(env):
    from app.models.interview import InterviewOperation
    factory, clock, svc=env
    cid=await create(svc()); await call(svc(),'start',cid,'s')
    clock[0] += timedelta(minutes=29, seconds=59)
    assert not await call(svc(),'check_inactivity',cid)
    assert not await call(svc(),'check_inactivity',cid)
    async with factory() as db:
        async with db.begin():
            db.add(InterviewOperation(interview_id=cid,kind='model',request_id='model',request_hash='x'*64,status='running',lease_until=clock[0]+timedelta(minutes=2)))
    clock[0] += timedelta(seconds=1)
    assert not await call(svc(),'check_inactivity',cid)
    async with factory() as db:
        async with db.begin():
            op=await db.scalar(__import__('sqlalchemy').select(InterviewOperation).where(InterviewOperation.interview_id==cid,InterviewOperation.request_id=='model'))
            op.status='complete'
    assert await call(svc(),'check_inactivity',cid)
    async with factory() as db:
        item=await db.get(Interview,cid)
        assert item.status=='interrupted' and item.end_reason=='inactivity_timeout'
    with pytest.raises(InterviewConflict): await call(svc(),'add_question',cid,'late','题')
    legacy=await create(svc())
    async with factory() as db:
        async with db.begin():
            item=await db.get(Interview,legacy)
            item.config_snapshot={'_rules': {'validity_policy_id':'nonempty-v1'}}
    with pytest.raises(InterviewConflict,match='快照'): await call(svc(),'start',legacy,'s')


@pytest.mark.asyncio
async def test_jd_unicode_boundaries(env):
    factory, clock, svc=env
    async with svc().db as db:
        service=InterviewService(db,recommended_rules())
        assert await service.create(mode='practice',limit_type='count',main_limit=3,duration_seconds=None,preset_snapshot={'kind':'role'},config_snapshot={},jd='面'*5000)
    async with svc().db as db:
        service=InterviewService(db,recommended_rules())
        with pytest.raises(InterviewConflict):
            await service.create(mode='practice',limit_type='count',main_limit=3,duration_seconds=None,preset_snapshot={'kind':'role'},config_snapshot={},jd='面'*5001)


@pytest.mark.asyncio
async def test_followup_without_main_answer_not_counted(env):
    from app.models.interview import InterviewAnswer, InterviewQuestion
    factory, clock, svc=env
    cid=await create(svc(),limit_type='time'); await call(svc(),'start',cid,'s')
    main=await call(svc(),'add_question',cid,'q','主问题')
    async with factory() as db:
        async with db.begin():
            follow=InterviewQuestion(interview_id=cid,parent_id=main['id'],main_number=1,depth=1,position=1,content='追问',source_snapshot={})
            db.add(follow); await db.flush()
            db.add(InterviewAnswer(interview_id=cid,question_id=follow.id,kind='answer',content='追问有效',request_id='direct-test',submitted_at=clock[0]))
    clock[0] += timedelta(seconds=60)
    assert (await call(svc(),'check_expiry',cid))['status']=='terminated'
    async with factory() as db: assert (await db.get(Interview,cid)).valid_main_count==0


@pytest.mark.asyncio
async def test_standard_question_bank_cannot_accept_jd(env):
    factory, clock, svc=env
    async with svc().db as db:
        with pytest.raises(InterviewConflict, match='岗位'):
            await InterviewService(db,recommended_rules()).create(mode='practice',limit_type='count',main_limit=3,duration_seconds=None,preset_snapshot={'kind':'bank'},config_snapshot={},jd='岗位要求')
