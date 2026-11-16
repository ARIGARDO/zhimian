import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.db.base import Base
from app.llm.client import ModelError
from app.models.interview import Interview, InterviewAIArtifact, InterviewOperation, InterviewQuestion
from app.services.interview import InterviewConflict, InterviewService, recommended_rules
from app.services.interview_ai import InterviewAIService, parse_result


@pytest_asyncio.fixture
async def env(tmp_path):
    engine=create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ai.db'}")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async def call(method,*args,**kwargs):
        async with factory() as db: return await getattr(InterviewService(db,recommended_rules()),method)(*args,**kwargs)
    async def make(mode='practice'):
        cid=await call('create',mode=mode,limit_type='count',main_limit=3,duration_seconds=None,preset_snapshot={},config_snapshot={})
        await call('start',cid,'start')
        q=await call('add_question',cid,'q1','问题')
        a=await call('answer',cid,'a1',q['id'],'不知道')
        return cid,q,a
    yield factory,call,make
    await engine.dispose()


def model_result(data):
    async def model(settings,messages,*,max_tokens=None):
        yield json.dumps(data,ensure_ascii=False)
    return model


@pytest.mark.asyncio
async def test_followup_retry_idempotency_and_limit(env):
    factory,call,make=env; cid,q,a=await make()
    ai=InterviewAIService(factory,model_result({'question':'为什么？'}))
    result=await ai.run(cid,'follow1','followup',a['id'])
    assert result['status']=='complete' and result['result']['depth']==1
    assert (await ai.run(cid,'follow1','followup',a['id']))['result']==result['result']
    with pytest.raises(InterviewConflict): await ai.run(cid,'different','followup',a['id'])
    answer=await call('answer',cid,'a2',result['result']['question_id'],'我不确定')
    second=await ai.run(cid,'follow2','followup',answer['id'])
    assert second['result']['depth']==2
    answer2=await call('answer',cid,'a3',second['result']['question_id'],'有待学习')
    with pytest.raises(InterviewConflict): await ai.run(cid,'follow3','followup',answer2['id'])
    async with factory() as db:
        item=await db.get(Interview,cid)
        assert item.main_count==1 and item.valid_main_count==1


@pytest.mark.asyncio
async def test_invalid_json_failure_retry_and_lease_recovery(env):
    factory,call,make=env; cid,q,a=await make()
    async def bad(settings,messages,*,max_tokens=None): yield 'not-json'
    ai=InterviewAIService(factory,bad)
    failed=await ai.run(cid,'feedback','feedback',a['id'])
    assert failed['status']=='failed' and '格式' in failed['error']
    good=InterviewAIService(factory,model_result({'feedback':'请补充思路'}))
    result=await good.run(cid,'feedback','feedback',a['id'])
    assert result['status']=='complete' and result['result']['feedback']=='请补充思路'
    assert (await good.get(cid,result['id']))['attempt_count']==2
    claimed=await good.claim(cid,'follow','followup',a['id'])
    async with factory() as db:
        async with db.begin():
            op=await db.get(InterviewOperation,claimed['id']); op.lease_until=datetime.now(timezone.utc)-timedelta(seconds=1)
    assert (await good.get(cid,claimed['id']))['status']=='failed'
    retried=await good.run(cid,'follow','followup',a['id'])
    assert retried['status']=='failed'  # feedback JSON is not a follow-up schema
    async with factory() as db:
        op=await db.get(InterviewOperation,claimed['id']); assert op.attempt_count==2


@pytest.mark.asyncio
async def test_state_change_during_model_rejects_result(env):
    factory,call,make=env; cid,q,a=await make()
    started=asyncio.Event(); resume=asyncio.Event()
    async def slow(settings,messages,*,max_tokens=None):
        started.set(); await resume.wait(); yield '{"question":"继续？"}'
    ai=InterviewAIService(factory,slow)
    task=asyncio.create_task(ai.run(cid,'follow','followup',a['id']))
    await started.wait()
    await call('end',cid,'end','terminated','主动结束')
    resume.set(); result=await task
    assert result['status']=='failed'
    async with factory() as db:
        assert len((await db.scalars(select(InterviewQuestion).where(InterviewQuestion.interview_id==cid))).all())==1
        assert len((await db.scalars(select(InterviewAIArtifact).where(InterviewAIArtifact.interview_id==cid))).all())==0


@pytest.mark.asyncio
async def test_formal_feedback_and_partial_report(env):
    factory,call,make=env; cid,q,a=await make('formal')
    ai=InterviewAIService(factory,model_result({'feedback':'不应显示'}))
    with pytest.raises(InterviewConflict): await ai.run(cid,'feedback','feedback',a['id'])
    with pytest.raises(InterviewConflict): await ai.get_report(cid)
    await call('end',cid,'end','terminated','提前结束')
    bad=InterviewAIService(factory,model_result({'summary':'得分八十分','items':[{'answer_id':a['id'],'review':'还可以'}]}))
    assert (await bad.run(cid,'report','report','partial'))['status']=='failed'
    good=InterviewAIService(factory,model_result({'summary':'可以进一步练习','items':[{'answer_id':a['id'],'review':'说明思路即可'}]}))
    done=await good.run(cid,'report','report','partial')
    assert done['status']=='complete' and 'overall_score' not in done['result']
    report=await good.get_report(cid)
    assert report['type']=='partial' and report['result']==done['result']
    with pytest.raises(InterviewConflict): await good.run(cid,'full','report','full')


@pytest.mark.asyncio
async def test_empty_and_full_report_reference_validation(env):
    factory,call,make=env
    async with factory() as db:
        cid=await InterviewService(db,recommended_rules()).create(mode='practice',limit_type='count',main_limit=3,duration_seconds=None,preset_snapshot={},config_snapshot={})
    await call('start',cid,'s'); await call('end',cid,'end','terminated','退出')
    ai=InterviewAIService(factory)
    assert (await ai.run(cid,'r','report','partial'))['status']=='no_content'
    assert (await ai.get_report(cid))['status']=='no_content'
    cid,q,a=await make(); ids=[a['id']]
    await call('close_main',cid,'c1')
    for n in (2,3):
        q=await call('add_question',cid,f'q{n}','问题')
        a=await call('answer',cid,f'a{n}',q['id'],'有效')
        ids.append(a['id']); await call('close_main',cid,f'c{n}')
    invalid=InterviewAIService(factory,model_result({'summary':'总结','overall_score':80.0,'items':[{'answer_id':'fabricated','review':'反馈'}]}))
    assert (await invalid.run(cid,'r','report','full'))['status']=='failed'
    good=InterviewAIService(factory,model_result({'summary':'总结','overall_score':80.0,'items':[{'answer_id':i,'review':'反馈'} for i in ids]}))
    done=await good.run(cid,'r','report','full')
    assert done['status']=='complete' and (await good.get_report(cid))['result']['overall_score']==80
    with pytest.raises(ModelError): parse_result('partial',json.dumps({'summary':'好','items':[{'answer_id':'a','review':'九十分'}]},ensure_ascii=False),{'a'})


@pytest.mark.asyncio
async def test_running_claim_race_expired_owner_and_timeout(env):
    factory,call,make=env; cid,q,a=await make()
    ai=InterviewAIService(factory,model_result({'question':'追问'}))
    first=await ai.claim(cid,'same','followup',a['id'])
    assert (await ai.claim(cid,'same','followup',a['id']))['status']=='running'
    with pytest.raises(InterviewConflict): await ai.claim(cid,'other','feedback',a['id'])
    async with factory() as db:
        async with db.begin():
            op=await db.get(InterviewOperation,first['id']); op.lease_until=datetime.now(timezone.utc)-timedelta(seconds=1)
    retry=await ai.claim(cid,'same','followup',a['id'])
    assert retry['owner']!=first['owner']
    with pytest.raises(InterviewConflict):
        await ai.finalize(cid,first['id'],first['owner'],'followup',a['id'],{'question':'旧结果'})
    result=await ai.finalize(cid,retry['id'],retry['owner'],'followup',a['id'],{'question':'新结果'})
    assert result['status']=='complete'


@pytest.mark.asyncio
async def test_model_failure_retains_answer_and_retry(env):
    factory,call,make=env; cid,q,a=await make()
    async def broken(settings,messages,*,max_tokens=None):
        yield '{'
        raise ModelError('模型服务请求超时')
    failed=await InterviewAIService(factory,broken).run(cid,'feedback','feedback',a['id'])
    assert failed['status']=='failed' and '超时' in failed['error']
    async with factory() as db:
        from app.models.interview import InterviewAnswer
        assert (await db.get(InterviewAnswer,a['id'])).content=='不知道'
    good=InterviewAIService(factory,model_result({'feedback':'请说明思路'}))
    assert (await good.run(cid,'feedback','feedback',a['id']))['status']=='complete'


@pytest.mark.asyncio
async def test_model_timeout_and_output_limit(env, monkeypatch):
    from types import SimpleNamespace
    factory,call,make=env; cid,q,a=await make(); received=[]
    async with factory() as db: before=(await db.get(Interview,cid)).last_activity_at
    monkeypatch.setattr('app.services.interview_ai.get_settings', lambda: SimpleNamespace(
        model_ai_max_attempts=3, model_ai_max_duration_seconds=0.01, model_ai_max_output_tokens=256))
    async def slow(settings,messages,*,max_tokens=None):
        received.append(max_tokens)
        await asyncio.sleep(1)
        yield '{}'
    result=await InterviewAIService(factory,slow).run(cid,'timeout','feedback',a['id'])
    assert result['status']=='failed' and '超时' in result['error']
    assert received==[256]
    async with factory() as db: assert (await db.get(Interview,cid)).last_activity_at==before


@pytest.mark.asyncio
async def test_http_feedback_and_formal_visibility(env, monkeypatch):
    import httpx
    from app.db.session import get_db
    from app.main import app
    factory,call,make=env
    async def override():
        async with factory() as db: yield db
    app.dependency_overrides[get_db]=override
    monkeypatch.setattr('app.api.v1.interviews.InterviewAIService', lambda: InterviewAIService(factory,model_result({'feedback':'请补充思路'})))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test/api/v1') as client:
            cid,q,a=await make()
            response=await client.post(f'/interviews/{cid}/ai/feedback',json={'answer_id':a['id']},headers={'Idempotency-Key':'feedback'})
            assert response.status_code==200 and response.json()['status']=='complete'
            op=response.json()['id']
            assert (await client.get(f'/interviews/{cid}/ai/operations/{op}')).json()['result']['feedback']=='请补充思路'
            formal,fq,fa=await make('formal')
            assert (await client.post(f'/interviews/{formal}/ai/feedback',json={'answer_id':fa['id']},headers={'Idempotency-Key':'formal'})).status_code==409
            assert (await client.get(f'/interviews/{formal}/ai/report')).status_code==409
    finally: app.dependency_overrides.clear()


def test_reject_scored_partial_and_evaluative_followup():
    with pytest.raises(ModelError):
        parse_result('partial',json.dumps({'summary':'百分之八十','items':[{'answer_id':'a','review':'建议复习'}]},ensure_ascii=False),{'a'})
    with pytest.raises(ModelError):
        parse_result('followup',json.dumps({'question':'你的回答不对，请给出原因？'},ensure_ascii=False),set())
    with pytest.raises(ModelError):
        parse_result('followup',json.dumps({'question':'先说明原理。'},ensure_ascii=False),set())


def test_partial_rejects_unicode_numeric_scores():
    with pytest.raises(ModelError):
        parse_result('partial',json.dumps({'summary':'Ⅷ 分','items':[{'answer_id':'a','review':'继续练习'}]},ensure_ascii=False),{'a'})


@pytest.mark.asyncio
async def test_model_result_after_deadline_is_discarded(env):
    factory,call,make=env
    async with factory() as db:
        cid=await InterviewService(db,recommended_rules()).create(mode='practice',limit_type='time',main_limit=None,duration_seconds=60,preset_snapshot={},config_snapshot={})
    await call('start',cid,'start')
    q=await call('add_question',cid,'q','问题')
    a=await call('answer',cid,'a',q['id'],'有效答案')
    started=asyncio.Event(); resume=asyncio.Event()
    async def slow(settings,messages,*,max_tokens=None):
        started.set(); await resume.wait(); yield '{"question":"为什么？"}'
    task=asyncio.create_task(InterviewAIService(factory,slow).run(cid,'follow','followup',a['id']))
    await started.wait()
    async with factory() as db:
        async with db.begin():
            item=await db.get(Interview,cid)
            item.deadline_at=datetime.now(timezone.utc)-timedelta(seconds=1)
    resume.set(); result=await task
    assert result['status']=='failed'
    async with factory() as db:
        assert (await db.get(Interview,cid)).status=='terminated'
        assert len((await db.scalars(select(InterviewAIArtifact).where(InterviewAIArtifact.interview_id==cid))).all())==0


@pytest.mark.parametrize('text', [
    'Python 3.12 与 FastAPI 0.115 的用法可进一步核对。',
    'HTTP 404 可检查路由，耗时约 80ms。',
    '可以复习 Python 3.12 分析与 HTTP/1.1。',
])
def test_partial_allows_technical_numbers(text):
    raw=json.dumps({'summary':text,'items':[{'answer_id':'a','review':'建议继续练习'}]},ensure_ascii=False)
    assert parse_result('partial',raw,{'a'})['summary']==text


@pytest.mark.parametrize('text', ['得分 80', '九十分', '评分：85/100', '百分之八十', '等级 B', '表现优秀', 'Ⅷ 分', 'score: 8/10'])
def test_partial_rejects_scoring_expressions(text):
    raw=json.dumps({'summary':text,'items':[{'answer_id':'a','review':'建议继续练习'}]},ensure_ascii=False)
    with pytest.raises(ModelError): parse_result('partial',raw,{'a'})


@pytest.mark.asyncio
async def test_model_success_failure_do_not_extend_user_activity_and_retry_budget(env):
    factory,call,make=env; cid,q,a=await make()
    async with factory() as db: before=(await db.get(Interview,cid)).last_activity_at
    async def bad(settings,messages,*,max_tokens=None): yield 'bad-json'
    ai=InterviewAIService(factory,bad)
    for key in ('try1','try2','try3'):
        assert (await ai.run(cid,key,'feedback',a['id']))['status']=='failed'
    with pytest.raises(InterviewConflict,match='最大尝试次数'):
        await ai.run(cid,'new-key','feedback',a['id'])
    async with factory() as db:
        item=await db.get(Interview,cid)
        assert item.last_activity_at==before and item.model_grace_until is None
    cid2,q2,a2=await make()
    async with factory() as db: before=(await db.get(Interview,cid2)).last_activity_at
    good=InterviewAIService(factory,model_result({'feedback':'说明思路'}))
    assert (await good.run(cid2,'ok','feedback',a2['id']))['status']=='complete'
    async with factory() as db:
        item=await db.get(Interview,cid2)
        assert item.last_activity_at==before and item.model_grace_until is None


@pytest.mark.asyncio
async def test_running_model_one_time_grace_does_not_repeat(env, monkeypatch):
    from app.services.interview import utc
    factory,call,make=env; cid,q,a=await make()
    base=datetime.now(timezone.utc)
    current=[base]
    async def fake_now(db): return current[0]
    monkeypatch.setattr('app.services.interview_ai.database_now',fake_now)
    async with factory() as db:
        async with db.begin():
            item=await db.get(Interview,cid); item.last_activity_at=base
    ai=InterviewAIService(factory,model_result({'feedback':'建议复习'}))
    first=await ai.claim(cid,'first','feedback',a['id'])
    current[0]=base+timedelta(minutes=31)
    async with factory() as db:
        async with db.begin():
            op=await db.get(InterviewOperation,first['id']); op.lease_until=current[0]+timedelta(seconds=90)
    async with factory() as db:
        service=InterviewService(db,recommended_rules(),fake_now)
        assert not await service.check_inactivity(cid)
    await ai.fail(cid,first['id'],first['owner'],'model_error')
    async with factory() as db:
        item=await db.get(Interview,cid)
        assert utc(item.last_activity_at)==base and utc(item.model_grace_until)==current[0]+timedelta(seconds=60)
    current[0]+=timedelta(seconds=30)
    retry=await ai.claim(cid,'second','feedback',a['id'])
    await ai.fail(cid,retry['id'],retry['owner'],'model_error')
    async with factory() as db:
        assert utc((await db.get(Interview,cid)).model_grace_until)==base+timedelta(minutes=32)
    current[0]+=timedelta(seconds=31)
    async with factory() as db:
        assert await InterviewService(db,recommended_rules(),fake_now).check_inactivity(cid)
    async with factory() as db: assert (await db.get(Interview,cid)).status=='interrupted'


@pytest.mark.asyncio
async def test_crashed_lease_grace_from_expiry_not_poll_time(env):
    from app.services.interview import utc
    factory,call,make=env; cid,q,a=await make(); base=datetime.now(timezone.utc)
    async with factory() as db:
        async with db.begin():
            item=await db.get(Interview,cid); item.last_activity_at=base
            db.add(InterviewOperation(interview_id=cid,kind='ai_followup',request_id='crash',request_hash='z'*64,status='running',lease_until=base+timedelta(minutes=30,seconds=10)))
    now=[base+timedelta(minutes=30,seconds=20)]
    async def clock(db): return now[0]
    async with factory() as db: assert not await InterviewService(db,recommended_rules(),clock).check_inactivity(cid)
    async with factory() as db: assert utc((await db.get(Interview,cid)).model_grace_until)==base+timedelta(minutes=31,seconds=10)
    now[0]=base+timedelta(minutes=31,seconds=11)
    async with factory() as db: assert await InterviewService(db,recommended_rules(),clock).check_inactivity(cid)


@pytest.mark.asyncio
async def test_poll_expired_lease_preserves_bounded_grace(env, monkeypatch):
    from app.services.interview import utc
    factory,call,make=env; cid,q,a=await make(); base=datetime.now(timezone.utc)
    async def fake_now(db): return base+timedelta(minutes=30,seconds=20)
    monkeypatch.setattr('app.services.interview_ai.database_now',fake_now)
    async with factory() as db:
        async with db.begin():
            item=await db.get(Interview,cid); item.last_activity_at=base
            op=InterviewOperation(interview_id=cid,kind='ai_feedback',request_id='stale',request_hash='x'*64,status='running',lease_until=base+timedelta(minutes=30,seconds=10))
            db.add(op); await db.flush(); op_id=op.id
    assert (await InterviewAIService(factory).get(cid,op_id))['status']=='failed'
    async with factory() as db:
        item=await db.get(Interview,cid)
        assert utc(item.model_grace_until)==base+timedelta(minutes=31,seconds=10)
