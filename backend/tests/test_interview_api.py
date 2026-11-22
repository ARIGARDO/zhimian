from datetime import datetime, timedelta, timezone
import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.interview import Interview, InterviewPreset, InterviewQuestionBank

TEST_MATERIAL = {'objectives':'测试目标', 'key_points':['测试要点'], 'anchors':{'complete':'完整','adequate':'基本','partial':'部分','insufficient':'不足'}, 'alternatives':['替代'], 'misconceptions':['误区']}


@pytest.mark.asyncio
async def test_api_flow_scope_idempotency_and_visibility(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(InterviewPreset(id='test-only', kind='bank', name='测试专用', version=1, active=True, config={}))
        await db.flush()
        for n in range(3):
            db.add(InterviewQuestionBank(id=f'test-q{n}', preset_id='test-only', content=f'测试题{n}', topic='test', version=1, active=True, content_code=f'T{n}', difficulty='basic', sort_order=n, review_status='approved', reviewed_by='test', reviewed_at=datetime.now(timezone.utc), review_material=TEST_MATERIAL))
        await db.commit()
    async def override():
        async with factory() as db: yield db
    app.dependency_overrides[get_db] = override
    def h(key): return {'Idempotency-Key': key}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test/api/v1') as c:
            assert len((await c.get('/interview-presets')).json()) == 1
            question_list = (await c.get('/interview-presets/test-only/questions')).json()
            assert 'content' not in question_list[0] and '测试要点' not in str(question_list)
            body={'preset_id':'test-only','mode':'practice','limit_type':'count','main_limit':3}
            assert (await c.post('/interviews',json=body)).status_code == 422
            assert (await c.post('/interviews',json={**body,'main_limit':2},headers=h('bad'))).status_code == 422
            assert (await c.post('/interviews',json={**body,'preset_id':'missing'},headers=h('missing'))).status_code == 404
            first=await c.post('/interviews',json=body,headers=h('create'))
            assert first.status_code==201
            cid=first.json()['id']
            assert (await c.post('/interviews',json=body,headers=h('create'))).json()['id']==cid
            assert (await c.post('/interviews',json={**body,'mode':'formal'},headers=h('create'))).status_code==409
            url=f'/interviews/{cid}'
            assert (await c.post(url+'/questions/next',headers=h('early'))).status_code==409
            start=await c.post(url+'/start',headers=h('start')); assert start.status_code==200
            assert (await c.post(url+'/start',headers=h('start'))).json()==start.json()
            q=(await c.post(url+'/questions/next',headers=h('q1'))).json()
            assert q['content']=='测试题0'
            assert (await c.post(url+'/questions/next',headers=h('bad-next'))).status_code==409
            assert (await c.post(url+'/questions/close',json={'question_id':q['id']},headers=h('bad-close'))).status_code==409
            assert (await c.post(url+'/answers',json={'question_id':'wrong','content':'x'},headers=h('wrong'))).status_code==404
            assert (await c.post(url+'/answers',json={'question_id':q['id'],'content':'！！！'},headers=h('invalid'))).status_code==422
            a=await c.post(url+'/answers',json={'question_id':q['id'],'content':'不会'},headers=h('a1')); assert a.status_code==200
            assert (await c.post(url+'/answers',json={'question_id':q['id'],'content':'不会'},headers=h('a1'))).json()==a.json()
            assert (await c.post(url+'/answers',json={'question_id':q['id'],'content':'其他'},headers=h('a1'))).status_code==409
            assert (await c.post(url+'/answers',json={'question_id':q['id'],'content':'其他'},headers=h('a2'))).status_code==409
            assert (await c.post(url+'/questions/close',json={'question_id':q['id']},headers=h('c1'))).status_code==200
            q2=(await c.post(url+'/questions/next',headers=h('q2'))).json()
            assert (await c.post(url+'/answers',json={'question_id':q2['id'],'skip':True},headers=h('skip'))).status_code==200
            assert (await c.post(url+'/terminate',headers=h('end'))).json()['status']=='terminated'
            assert (await c.post(url+'/answers',json={'question_id':q2['id'],'content':'x'},headers=h('late'))).status_code==409
            assert (await c.get('/interviews?status=incomplete')).json()[0]['id']==cid
            assert (await c.get('/interviews/not-found')).status_code==404
            formal=(await c.post('/interviews',json={**body,'mode':'formal'},headers=h('formal'))).json()['id']
            await c.post(f'/interviews/{formal}/start',headers=h('start2'))
            fq=(await c.post(f'/interviews/{formal}/questions/next',headers=h('fq'))).json()
            assert (await c.post(f'/interviews/{formal}/answers',json={'question_id':fq['id'],'skip':True},headers=h('fskip'))).status_code==409
            detail=(await c.get(f'/interviews/{formal}')).json()
            assert 'score' not in str(detail) and 'review' not in str(detail) and 'question_plan' not in str(detail) and '测试要点' not in str(detail)
            async with factory() as db:
                async with db.begin():
                    item=await db.get(Interview,formal)
                    item.last_activity_at=datetime.now(timezone.utc)-timedelta(minutes=31)
            history=(await c.get('/interviews?status=incomplete')).json()
            assert any(x['id']==formal and x['status']=='interrupted' for x in history)
    finally:
        app.dependency_overrides.clear(); await engine.dispose()


@pytest.mark.asyncio
async def test_api_internal_errors_are_sanitized(monkeypatch):
    async def fail(self, interview_id):
        raise RuntimeError('private diagnostic')
    monkeypatch.setattr('app.services.interview.InterviewService.detail', fail)
    async def override():
        yield None
    app.dependency_overrides[get_db] = override
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test/api/v1') as c:
            result=await c.get('/interviews/test')
            assert result.status_code == 500 and result.json()=={'detail':'服务器内部错误'}
    finally:
        app.dependency_overrides.clear()
