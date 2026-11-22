"""隔离 PostgreSQL 中的双进程 HTTP 集成测试；只写测试数据库。"""
import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.interview import Interview, InterviewPreset, InterviewQuestionBank

TEST_MATERIAL = {'objectives':'测试目标', 'key_points':['测试要点'], 'anchors':{'complete':'完整','adequate':'基本','partial':'部分','insufficient':'不足'}, 'alternatives':['替代'], 'misconceptions':['误区']}

test_db=os.environ['M303_TEST_DB']
if not test_db.startswith('zhimian_m303_') or not test_db.replace('_', '').isalnum():
    raise ValueError('仅允许专用的 zhimian_m303_ 临时测试数据库')
url=os.environ['DATABASE_URL'].rsplit('/',1)[0]+'/'+test_db
env=os.environ.copy(); env['DATABASE_URL']=url
subprocess.run(['alembic','upgrade','head'],env=env,check=True)
engine=create_async_engine(url, poolclass=NullPool); factory=async_sessionmaker(engine,expire_on_commit=False)
async def setup():
    async with factory() as db:
        db.add(InterviewPreset(id='m303-test-only',kind='bank',name='测试专用',version=1,active=True,config={}))
        await db.flush()
        for i in range(4): db.add(InterviewQuestionBank(id=f'm303-{i}',preset_id='m303-test-only',content=f'隔离测试题{i}',topic='test',version=1,active=True,content_code=f'T{i}',difficulty='basic',sort_order=i,review_status='approved',reviewed_by='test',reviewed_at=datetime.now(timezone.utc),review_material=TEST_MATERIAL))
        await db.commit()
asyncio.run(setup())
processes=[]

def start(port):
    p=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    processes.append(p)
    return p

async def main():
    p1=start(18831); p2=start(18832)
    async with httpx.AsyncClient(timeout=15,trust_env=False) as c:
        bases=['http://127.0.0.1:18831/api/v1','http://127.0.0.1:18832/api/v1']
        for base in bases:
            for _ in range(100):
                try:
                    if (await c.get(base+'/health')).status_code==200: break
                except httpx.HTTPError: pass
                await asyncio.sleep(.1)
            else: raise RuntimeError('测试后端未启动')
        def h(key): return {'Idempotency-Key':key}
        body={'preset_id':'m303-test-only','mode':'practice','limit_type':'count','main_limit':3}
        async def create(key,payload=body,base=bases[0]):
            return await c.post(base+'/interviews',json=payload,headers=h(key))
        pair=await asyncio.gather(create('create-race',base=bases[0]),create('create-race',base=bases[1]))
        assert all(x.status_code==201 for x in pair) and pair[0].json()['id']==pair[1].json()['id']
        cid=pair[0].json()['id']; paths=[b+f'/interviews/{cid}' for b in bases]
        assert (await create('create-race',{**body,'mode':'formal'})).status_code==409
        assert (await create('bad',{**body,'main_limit':2})).status_code==422
        starts=await asyncio.gather(*(c.post(path+'/start',headers=h('start-race')) for path in paths))
        assert all(x.status_code==200 for x in starts) and starts[0].json()==starts[1].json()
        q=(await c.post(paths[0]+'/questions/next',headers=h('q0'))).json(); assert q['content']=='隔离测试题0'
        answers=await asyncio.gather(*(c.post(path+'/answers',json={'question_id':q['id'],'content':'不会'},headers=h('a0')) for path in paths))
        assert all(x.status_code==200 for x in answers) and answers[0].json()==answers[1].json()
        assert (await c.post(paths[0]+'/answers',json={'question_id':q['id'],'content':'其他'},headers=h('a0'))).status_code==409
        assert (await c.post(paths[0]+'/questions/close',json={'question_id':q['id']},headers=h('c0'))).status_code==200
        q1=(await c.post(paths[0]+'/questions/next',headers=h('q1'))).json()
        assert (await c.post(paths[0]+'/answers',json={'question_id':q1['id'],'content':'有效'},headers=h('a1'))).status_code==200
        await c.post(paths[0]+'/questions/close',json={'question_id':q1['id']},headers=h('c1'))
        q2=(await c.post(paths[0]+'/questions/next',headers=h('q2'))).json()
        assert (await c.post(paths[0]+'/answers',json={'question_id':q2['id'],'skip':True},headers=h('a2'))).status_code==200
        assert (await c.post(paths[0]+'/questions/close',json={'question_id':q2['id']},headers=h('c2'))).json()['status']=='completed'
        assert (await c.post(paths[0]+'/answers',json={'question_id':q2['id'],'content':'late'},headers=h('late'))).status_code==409
        print('双进程重复创建、开始、作答及题数完成：通过')
        formal=(await create('formal',{**body,'mode':'formal'})).json()['id']; f=bases[0]+f'/interviews/{formal}'
        await c.post(f+'/start',headers=h('s')); fq=(await c.post(f+'/questions/next',headers=h('q'))).json()
        assert (await c.post(f+'/answers',json={'question_id':fq['id'],'skip':True},headers=h('skip'))).status_code==409
        assert (await c.post(f+'/answers',json={'question_id':q['id'],'content':'wrong'},headers=h('cross'))).status_code==404
        detail=(await c.get(f)).json(); assert 'question_plan' not in str(detail) and 'score' not in str(detail) and 'review' not in str(detail)
        print('正式模式跳题、跨场题目及评价隔离：通过')
        race=(await create('race')).json()['id']; paths=[b+f'/interviews/{race}' for b in bases]
        await c.post(paths[0]+'/start',headers=h('s')); rq=(await c.post(paths[0]+'/questions/next',headers=h('q'))).json()
        r=await asyncio.gather(c.post(paths[0]+'/terminate',headers=h('end')),c.post(paths[1]+'/answers',json={'question_id':rq['id'],'content':'回答'},headers=h('answer')))
        assert r[0].status_code==200 and r[1].status_code in (200,409)
        assert (await c.get(paths[0])).json()['status']=='terminated'
        print('并发结束和作答竞争：通过')
        for mode in ('time','count'):
            payload={**body,'limit_type':mode,'main_limit':3 if mode=='count' else None,'duration_seconds':2 if mode=='time' else None}
            iid=(await create('expiry-'+mode,payload)).json()['id']; path=bases[0]+f'/interviews/{iid}'
            await c.post(path+'/start',headers=h('s')); question=(await c.post(path+'/questions/next',headers=h('q'))).json()
            async with factory() as db:
                async with db.begin():
                    item=await db.get(Interview,iid)
                    if mode=='time': item.deadline_at=datetime.now(timezone.utc)-timedelta(seconds=1)
                    else: item.last_activity_at=datetime.now(timezone.utc)-timedelta(minutes=31)
            response=await c.post(path+'/answers',json={'question_id':question['id'],'content':'late'},headers=h('late'))
            assert response.status_code==409 and response.json()['status']==('terminated' if mode=='time' else 'interrupted')
            assert (await c.get(path)).json()['status']==response.json()['status']
            records=(await c.get(bases[0]+'/interviews',params={'status':'incomplete'})).json()
            assert any(item['id']==iid for item in records)
        print('真实 PostgreSQL 时限与无活动到期 HTTP：通过')

try: asyncio.run(main())
finally:
    for p in processes:
        if p.poll() is None: p.terminate()
        try: p.wait(timeout=5)
        except subprocess.TimeoutExpired: p.kill()
    asyncio.run(engine.dispose())
