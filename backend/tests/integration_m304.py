"""隔离 PostgreSQL 中的双进程 AI HTTP 验证。"""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from app.models.interview import Interview, InterviewPreset, InterviewQuestionBank, InterviewOperation

TEST_MATERIAL = {'objectives':'测试目标', 'key_points':['测试要点'], 'anchors':{'complete':'完整','adequate':'基本','partial':'部分','insufficient':'不足'}, 'alternatives':['替代'], 'misconceptions':['误区']}
from sqlalchemy import select
from datetime import datetime, timedelta, timezone

name=os.environ['M304_TEST_DB']
if not name.startswith('zhimian_m304_') or not name.replace('_','').isalnum(): raise ValueError('仅允许隔离测试数据库')
url=os.environ['DATABASE_URL'].rsplit('/',1)[0]+'/'+name
env=os.environ.copy(); env.update(DATABASE_URL=url, MODEL_BASE_URL='http://127.0.0.1:18910/v1', MODEL_NAME='test', MODEL_API_KEY='test-only', MODEL_TIMEOUT='15')
subprocess.run(['alembic','upgrade','head'],env=env,check=True)
engine=create_async_engine(url,poolclass=NullPool); factory=async_sessionmaker(engine,expire_on_commit=False)
async def setup():
    async with factory() as db:
        db.add(InterviewPreset(id='test-only',kind='bank',name='测试题库',version=1,active=True,config={}))
        await db.flush()
        for i in range(3): db.add(InterviewQuestionBank(id=f'test-{i}',preset_id='test-only',content=f'隔离测试题{i}',topic='test',version=1,active=True,content_code=f'T{i}',difficulty='basic',sort_order=i,review_status='approved',reviewed_by='test',reviewed_at=datetime.now(timezone.utc),review_material=TEST_MATERIAL))
        await db.commit()
asyncio.run(setup())

calls={}; lock=threading.Lock()
class MockModel(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert data.get('max_tokens') == 1024
        messages=data['messages']; instruction=messages[0]['content']; records=json.loads(messages[1]['content'])
        marker=records[-1]['answer']
        with lock:
            calls[marker]=calls.get(marker,0)+1; attempt=calls[marker]
        if marker in ('slow', 'crash'): time.sleep(3)
        if marker=='invalid-always' or (marker=='invalid' and attempt==1): output='invalid-json'
        elif 'overall_score' in instruction:
            output=json.dumps({'summary':'总结','overall_score':80.0,'items':[{'answer_id':r['answer_id'],'review':'建议继续练习'} for r in records]},ensure_ascii=False)
        elif '"items"' in instruction:
            output=json.dumps({'summary':'建议继续练习','items':[{'answer_id':r['answer_id'],'review':'建议补充思路'} for r in records]},ensure_ascii=False)
        elif '"feedback"' in instruction: output=json.dumps({'feedback':'建议补充思路'},ensure_ascii=False)
        else: output=json.dumps({'question':'请解释原因？'},ensure_ascii=False)
        try:
            self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.end_headers()
            self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':output}}]},ensure_ascii=False)+'\n\ndata: [DONE]\n\n').encode()); self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError): pass

server=ThreadingHTTPServer(('127.0.0.1',18910),MockModel)
threading.Thread(target=server.serve_forever,daemon=True).start()
processes=[]
def start(port):
    p=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); processes.append(p); return p

async def main():
    start(18911); start(18912)
    async with httpx.AsyncClient(timeout=30,trust_env=False) as c:
        bases=['http://127.0.0.1:18911/api/v1','http://127.0.0.1:18912/api/v1']
        for b in bases:
            for _ in range(100):
                try:
                    if (await c.get(b+'/health')).status_code==200: break
                except httpx.HTTPError: pass
                await asyncio.sleep(.1)
            else: raise RuntimeError('测试服务未启动')
        def h(k): return {'Idempotency-Key':k}
        async def create(mode='practice',answer='有效回答'):
            body={'preset_id':'test-only','mode':mode,'limit_type':'count','main_limit':3}
            r=await c.post(bases[0]+'/interviews',json=body,headers=h('create-'+str(time.time_ns()))); r.raise_for_status(); cid=r.json()['id']; path=bases[0]+f'/interviews/{cid}'
            await c.post(path+'/start',headers=h('start'))
            q=(await c.post(path+'/questions/next',headers=h('q'))).json()
            a=(await c.post(path+'/answers',json={'question_id':q['id'],'content':answer},headers=h('a'))).json()
            return cid,q,a
        cid,q,a=await create(answer='slow'); paths=[b+f'/interviews/{cid}' for b in bases]
        reqs=[c.post(p+'/ai/followup',json={'answer_id':a['id']},headers=h('same')) for p in paths]
        responses=await asyncio.gather(*reqs); assert all(r.status_code==200 for r in responses)
        values=[r.json() for r in responses]
        assert sorted(x['status'] for x in values)==['complete','running'] and calls['slow']==1
        ready=next(x for x in values if x['status']=='complete')
        again=(await c.post(paths[1]+'/ai/followup',json={'answer_id':a['id']},headers=h('same'))).json()
        assert again['result']==ready['result']
        print('双进程同键追问、租约与幂等落库：通过')
        cid,q,a=await create(answer='invalid'); path=bases[0]+f'/interviews/{cid}'
        bad=(await c.post(path+'/ai/feedback',json={'answer_id':a['id']},headers=h('retry'))).json()
        assert bad['status']=='failed'
        good=(await c.post(path+'/ai/feedback',json={'answer_id':a['id']},headers=h('retry'))).json()
        assert good['status']=='complete' and bad['id']==good['id']
        assert (await c.get(path+'/ai/operations/'+good['id'])).json()['attempt_count']==2
        print('无效 JSON、同键重试及操作状态：通过')
        cid,q,a=await create(answer='invalid-always'); path=bases[0]+f'/interviews/{cid}'
        async with factory() as db: original=(await db.get(Interview,cid)).last_activity_at
        for index in range(3):
            result=(await c.post(path+'/ai/feedback',json={'answer_id':a['id']},headers=h(f'budget-{index}'))).json()
            assert result['status']=='failed'
        assert (await c.post(path+'/ai/feedback',json={'answer_id':a['id']},headers=h('budget-extra'))).status_code==409
        async with factory() as db: assert (await db.get(Interview,cid)).last_activity_at==original
        assert calls['invalid-always']==3
        print('跨幂等键累计尝试上限及失败不刷新活动：通过')
        cid,q,a=await create(mode='formal'); path=bases[0]+f'/interviews/{cid}'
        assert (await c.post(path+'/ai/feedback',json={'answer_id':a['id']},headers=h('forbidden'))).status_code==409
        await c.post(path+'/terminate',headers=h('terminate'))
        partial=(await c.post(path+'/ai/report',json={'type':'partial'},headers=h('report'))).json()
        assert partial['status']=='complete' and 'overall_score' not in partial['result']
        report=(await c.get(path+'/ai/report')).json(); assert report['type']=='partial' and report['status']=='ready'
        print('正式模式隔离及部分报告不含分数：通过')
        cid,q,a=await create(answer='slow'); paths=[b+f'/interviews/{cid}' for b in bases]
        running=asyncio.create_task(c.post(paths[0]+'/ai/followup',json={'answer_id':a['id']},headers=h('end-race')))
        await asyncio.sleep(.7)
        terminate=await c.post(paths[1]+'/terminate',headers=h('end')); assert terminate.status_code==200
        result=(await running).json(); assert result['status']=='failed'
        assert len((await c.get(paths[1])).json()['questions'])==1
        print('模型运行中提前终止，迟到结果不落库：通过')
        cid,q,a=await create(answer='slow'); paths=[b+f'/interviews/{cid}' for b in bases]
        running=asyncio.create_task(c.post(paths[0]+'/ai/followup',json={'answer_id':a['id']},headers=h('idle-race')))
        await asyncio.sleep(.7)
        original=datetime.now(timezone.utc)-timedelta(minutes=31)
        async with factory() as db:
            async with db.begin():
                item=await db.get(Interview,cid)
                item.last_activity_at=original
        assert (await c.get(paths[1])).json()['status']=='in_progress'
        assert (await running).json()['status']=='complete'
        assert (await c.get(paths[1])).json()['status']=='in_progress'
        async with factory() as db:
            item=await db.get(Interview,cid)
            assert item.last_activity_at==original and item.model_grace_until is not None
            grace=item.model_grace_until
        feedback=(await c.post(paths[1]+'/ai/feedback',json={'answer_id':a['id']},headers=h('grace-retry'))).json()
        assert feedback['status']=='complete'
        async with factory() as db: assert (await db.get(Interview,cid)).model_grace_until==grace
        print('有效租约与一次性宽限保护，模型成功不刷新活动：通过')
        cid,q,a=await create(answer='crash'); paths=[b+f'/interviews/{cid}' for b in bases]
        running=asyncio.create_task(c.post(paths[0]+'/ai/followup',json={'answer_id':a['id']},headers=h('crash-key')))
        await asyncio.sleep(.8)
        async with factory() as db:
            op=await db.scalar(select(InterviewOperation).where(InterviewOperation.interview_id==cid,InterviewOperation.request_id=='crash-key'))
            assert op and op.status=='running'; operation_id=op.id
        processes[0].kill(); processes[0].wait(timeout=5)
        try: await running
        except httpx.HTTPError: pass
        async with factory() as db:
            async with db.begin():
                op=await db.get(InterviewOperation,operation_id)
                op.lease_until=datetime.now(timezone.utc)-timedelta(seconds=1)
        recovered=(await c.post(paths[1]+'/ai/followup',json={'answer_id':a['id']},headers=h('crash-key'))).json()
        assert recovered['status']=='complete' and recovered['id']==operation_id
        assert (await c.get(paths[1]+'/ai/operations/'+operation_id)).json()['attempt_count']==2
        print('生成进程崩溃、租约过期及同键恢复：通过')

try: asyncio.run(main())
finally:
    for p in processes:
        if p.poll() is None: p.terminate()
        try: p.wait(timeout=5)
        except subprocess.TimeoutExpired: p.kill()
    server.shutdown(); asyncio.run(engine.dispose())
