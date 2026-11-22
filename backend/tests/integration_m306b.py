"""仅允许专用隔离 PostgreSQL；导入、人工审核模拟及 API 验收。"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from app.db.session import get_db
from app.main import app
from app.models.interview import Interview, InterviewPreset, InterviewQuestionBank
from app.services.question_version import question_digest, question_payload
from app.services.interview import InterviewService, recommended_rules
from app.tools.import_interview_draft import GUARD, import_draft, validate_url

url=os.environ['M306B_TEST_DATABASE_URL']; validate_url(url)
env=dict(os.environ,DATABASE_URL=url)
subprocess.run([sys.executable,'-m','alembic','upgrade','head'],env=env,check=True)
engine=create_async_engine(url,poolclass=NullPool); factory=async_sessionmaker(engine,expire_on_commit=False)
manifest='../docs/interview/M3-06A-question-manifest.json'
async def main():
    try:
        await import_draft(url,manifest)
        raise AssertionError('缺少隔离标记仍执行导入')
    except ValueError as exc:
        assert '隔离' in str(exc)
    async with engine.begin() as conn:
        await conn.execute(text('CREATE TABLE m306b_isolation_guard (marker text NOT NULL)'))
        await conn.execute(text('INSERT INTO m306b_isolation_guard VALUES (:marker)'),{'marker':GUARD})
    async with factory() as db:
        historic=await InterviewService(db,recommended_rules()).create(mode='practice',limit_type='count',main_limit=3,duration_seconds=None,preset_snapshot={},config_snapshot={})
    async with factory() as db:
        await InterviewService(db,recommended_rules()).start(historic,'start')
    first=await import_draft(url,manifest); second=await import_draft(url,manifest)
    assert first==second and len(first)==20
    async with factory() as db:
        presets=(await db.scalars(select(InterviewPreset))).all()
        questions=(await db.scalars(select(InterviewQuestionBank))).all()
        assert len(presets)==2 and len(questions)==20
        assert all(not p.active for p in presets)
        assert all(q.review_status=='draft' and not q.active for q in questions)
        assert all(sum(q.preset_id==p.id for q in questions)==10 for p in presets)
    # 仅对独立测试库模拟审核与启用；正式清单始终为草稿。
    async with factory() as db:
        async with db.begin():
            questions=(await db.scalars(select(InterviewQuestionBank))).all()
            for q in questions: q.review_status='approved'; q.reviewed_by='test-only'; q.reviewed_at=datetime.now(timezone.utc)
    async with factory() as db:
        assert not any((await db.scalars(select(InterviewQuestionBank.active))).all())
    async with factory() as db:
        async with db.begin():
            for p in (await db.scalars(select(InterviewPreset))).all(): p.active=True
            for q in (await db.scalars(select(InterviewQuestionBank))).all(): q.active=True
            for pid,kind in [('legacy','bank'),('legacyrole','role')]:
                db.add(InterviewPreset(id=pid,kind=kind,name=pid,version=1,active=True,config={}))
            await db.flush()
            for pid in ('legacy','legacyrole'):
                for n in range(3): db.add(InterviewQuestionBank(id=f'{pid}{n}',preset_id=pid,content='旧版测试题',topic='test',version=1,active=True))
    assert await import_draft(url,manifest)==first
    changed=json.loads(open(manifest,encoding='utf-8').read()); changed['questions'][0]['content']+='变更'
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',suffix='.json') as tmp:
        json.dump(changed,tmp,ensure_ascii=False); tmp.flush()
        try:
            await import_draft(url,tmp.name)
            raise AssertionError('同版本不同内容未拒绝')
        except ValueError as exc:
            assert '冲突' in str(exc)
    async with factory() as db:
        detail=await InterviewService(db,recommended_rules()).detail(historic)
        assert detail['status']=='in_progress'
    async def override():
        async with factory() as db: yield db
    app.dependency_overrides[get_db]=override
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test/api/v1') as c:
            for pid in ('bank-python-v1','bank-ai-v1','legacy','legacyrole'):
                body={'preset_id':pid,'mode':'practice','limit_type':'count','main_limit':3}
                if pid=='legacyrole': body['jd']='隔离测试 JD'
                res=await c.post('/interviews',json=body,headers={'Idempotency-Key':'create-'+pid}); assert res.status_code==201, res.text
                cid=res.json()['id']; path=f'/interviews/{cid}'
                assert (await c.post(path+'/start',headers={'Idempotency-Key':'start'})).status_code==200
                async with factory() as db:
                    item=await db.get(Interview,cid); plan=item.config_snapshot['question_plan']
                    if pid.startswith('bank-'):
                        rows=[await db.get(InterviewQuestionBank,x['id']) for x in plan]
                        assert len(rows)==10
                        assert [r.difficulty for r in rows]==['basic']*4+['intermediate']*5+['challenge']
                        assert all(question_digest(question_payload(row))==entry['digest'] for row,entry in zip(rows,plan))
                        assert item.config_snapshot['evaluation_policy']=='reviewed-v1'
                    else: assert item.config_snapshot['evaluation_policy']=='legacy-v1'
                meta=await c.get(f'/interview-presets/{pid}/questions'); detail=await c.get(path)
                assert 'key_points' not in meta.text+detail.text and 'anchors' not in meta.text+detail.text
                q=await c.post(path+'/questions/next',headers={'Idempotency-Key':'next'}); assert q.status_code==200
                assert 'review_material' not in q.text and 'anchors' not in q.text
                answer=await c.post(path+'/answers',json={'question_id':q.json()['id'],'content':'测试回答'},headers={'Idempotency-Key':'answer'}); assert answer.status_code==200
                assert (await c.get(path)).status_code==200
    finally:
        app.dependency_overrides.clear(); await engine.dispose()
    print('隔离验收通过：20 题、重复导入、审核启用分离、顺序快照、API 白名单、旧 bank/role')
asyncio.run(main())
