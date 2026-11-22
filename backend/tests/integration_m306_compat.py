"""在专用 PostgreSQL 库核对创建面试的兼容性及材料容量。"""
import asyncio
import os
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit
import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from app.db.session import get_db
from app.main import app
from app.models.interview import Interview, InterviewPreset, InterviewQuestionBank

url=os.environ['M306_TEST_DATABASE_URL']
name=urlsplit(url).path.lstrip('/')
if not name.startswith('zhimian_m306_') or not name.replace('_','').isalnum(): raise ValueError('仅允许隔离数据库')
subprocess.run([sys.executable,'-m','alembic','upgrade','head'],env=dict(os.environ,DATABASE_URL=url),check=True)
engine=create_async_engine(url,poolclass=NullPool)
factory=async_sessionmaker(engine,expire_on_commit=False)
material={'objectives':'测试','key_points':['测试要点'],'anchors':{'complete':'完整','adequate':'基本','partial':'部分','insufficient':'不足'},'alternatives':['替代'],'misconceptions':['误区']}
async def main():
    async with factory() as db:
        async with db.begin():
            for pid,kind in [('legacy','bank'),('legacyrole','role'),('role','role'),('reviewed','bank'),('oversize','bank'),('mixed','bank')]:
                db.add(InterviewPreset(id=pid,kind=kind,name=pid,version=1,active=True,config={}))
            await db.flush()
            for pid in ('legacy','legacyrole','role','reviewed','oversize','mixed'):
                for n in range(3):
                    extra={} if pid in ('legacy','legacyrole') or (pid=='mixed' and n==0) else dict(content_code=f'T{n}',difficulty='basic',sort_order=n,review_status='approved',reviewed_by='test',reviewed_at=datetime.now(timezone.utc),review_material=({**material,'key_points':['界'*1201]} if pid=='oversize' else material))
                    db.add(InterviewQuestionBank(id=f'{pid}{n}',preset_id=pid,content='隔离测试题',topic='test',version=1,active=True,**extra))
    async def override():
        async with factory() as db: yield db
    app.dependency_overrides[get_db]=override
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test/api/v1') as c:
            for pid, expected in [('legacy',201),('legacyrole',201),('role',409),('reviewed',201),('oversize',409),('mixed',409)]:
                body={'preset_id':pid,'mode':'practice','limit_type':'count','main_limit':3}
                if pid=='legacyrole': body['jd']='测试岗位描述'
                res=await c.post('/interviews',json=body,headers={'Idempotency-Key':'create-'+pid})
                assert res.status_code==expected, (pid,res.status_code,res.text)
                assert '测试要点' not in res.text
                if expected==201:
                    async with factory() as db:
                        item=await db.get(Interview,res.json()['id'])
                        assert item.config_snapshot['evaluation_policy']==('reviewed-v1' if pid=='reviewed' else 'legacy-v1')
                        if pid=='legacyrole': assert item.jd=='测试岗位描述'
                    if pid in ('legacy','legacyrole'):
                        path='/interviews/'+res.json()['id']
                        assert (await c.post(path+'/start',headers={'Idempotency-Key':'s'})).status_code==200
                        q=(await c.post(path+'/questions/next',headers={'Idempotency-Key':'q'})).json()
                        a=(await c.post(path+'/answers',json={'question_id':q['id'],'content':'有效回答'},headers={'Idempotency-Key':'a'})).json()
                        from app.services.interview_ai import InterviewAIService
                        async with factory() as db:
                            item=await db.get(Interview,res.json()['id'])
                            records=await InterviewAIService(factory)._context(db,item,'feedback',a['id'])
                            assert records[0]['answer']=='有效回答' and 'review_material' not in records[0]
            print('PostgreSQL API：旧 bank/role 恢复，新版 bank 审核及容量约束、role 和混合版本保护：通过')
    finally:
        app.dependency_overrides.clear(); await engine.dispose()
asyncio.run(main())
