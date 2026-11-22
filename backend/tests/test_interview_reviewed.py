import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.db.base import Base
from app.models.interview import Interview, InterviewAnswer, InterviewPreset, InterviewQuestion, InterviewQuestionBank
from app.services.interview import InterviewConflict, InterviewService, recommended_rules
from app.services.interview_ai import InterviewAIService

MATERIAL = {'objectives':'验证目标', 'key_points':['私有参考要点'], 'anchors':{'complete':'完整','adequate':'基本','partial':'部分','insufficient':'不足'}, 'alternatives':['替代答案'], 'misconceptions':['常见误区']}

@pytest.mark.asyncio
async def test_reviewed_snapshot_and_model_context(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'review.db'}")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        async with db.begin():
            db.add(InterviewPreset(id='p', kind='bank', name='测试', version=1, active=True, config={}))
            await db.flush()
            for n, difficulty in enumerate(('challenge','basic','intermediate')):
                db.add(InterviewQuestionBank(id=f'q{n}',preset_id='p',content=f'问题{n}',topic='test',version=1,active=True,content_code=f'P{n}',difficulty=difficulty,sort_order=n,review_status='approved',reviewed_by='test',reviewed_at=datetime.now(timezone.utc),review_material=MATERIAL))
    async def call(name,*args,**kw):
        async with factory() as db: return await getattr(InterviewService(db,recommended_rules()),name)(*args,**kw)
    cid=(await call('create_from_preset',key='create',preset_id='p',mode='practice',limit_type='count',main_limit=3,duration_seconds=None,jd=None))['id']
    await call('start',cid,'start'); q=await call('next_question',cid,'next'); assert q['content']=='问题1'
    answer=await call('answer',cid,'answer',q['id'],'答'*5001)
    async with factory() as db:
        item=await db.get(Interview,cid); assert item.config_snapshot['evaluation_policy']=='reviewed-v1'
        feedback=await InterviewAIService(factory)._context(db,item,'feedback',answer['id'])
        follow=await InterviewAIService(factory)._context(db,item,'followup',answer['id'])
        assert len(feedback[0]['answer'])==5001 and feedback[0]['review_material']==MATERIAL
        assert 'review_material' not in follow[0]
    # 新版场次的引用丢失不得被当作旧版场次。
    async with factory() as db:
        async with db.begin():
            item=await db.get(Interview,cid)
            item.config_snapshot={**item.config_snapshot, 'question_plan':[]}
    async with factory() as db:
        item=await db.get(Interview,cid)
        with pytest.raises(InterviewConflict,match='缺失'): await InterviewAIService(factory)._context(db,item,'feedback',answer['id'])
    async with factory() as db:
        async with db.begin():
            item=await db.get(Interview,cid)
            main=await db.get(InterviewQuestion,q['id'])
            item.config_snapshot={**item.config_snapshot, 'question_plan':[main.source_snapshot]}
    # 摘要不符必须失败，不得退回旧版或最新版。
    async with factory() as db:
        async with db.begin():
            row=await db.get(InterviewQuestionBank,'q1'); row.content='被篡改'
    async with factory() as db:
        item=await db.get(Interview,cid)
        with pytest.raises(InterviewConflict,match='摘要不匹配'): await InterviewAIService(factory)._context(db,item,'feedback',answer['id'])
    async with factory() as db:
        assert (await db.get(InterviewAnswer,answer['id'])).content=='答'*5001
    await engine.dispose()

@pytest.mark.asyncio
@pytest.mark.parametrize('count',[3,5,10])
async def test_budget_never_truncates_or_discards_answers(tmp_path,count):
    engine=create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'budget.db'}")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async def call(name,*args,**kw):
        async with factory() as db: return await getattr(InterviewService(db,recommended_rules()),name)(*args,**kw)
    cid=await call('create',mode='practice',limit_type='count',main_limit=count,duration_seconds=None,preset_snapshot={},config_snapshot={})
    await call('start',cid,'start')
    for n in range(count):
        q=await call('add_question',cid,f'q{n}','问题')
        await call('answer',cid,f'a{n}',q['id'],'答'*9000)
        await call('close_main',cid,f'c{n}')
    async with factory() as db:
        item=await db.get(Interview,cid)
        with pytest.raises(InterviewConflict,match='预算'): await InterviewAIService(factory)._context(db,item,'report','full')
        answers=(await db.scalars(select(InterviewAnswer).where(InterviewAnswer.interview_id==cid))).all()
        assert len(answers)==count and all(len(a.content)==9000 for a in answers)
    await engine.dispose()

@pytest.mark.asyncio
@pytest.mark.parametrize('count',[3,5,10])
async def test_budget_counts_all_followups(tmp_path,count):
    engine=create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'followups.db'}")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async def call(name,*args,**kw):
        async with factory() as db: return await getattr(InterviewService(db,recommended_rules()),name)(*args,**kw)
    cid=await call('create',mode='practice',limit_type='count',main_limit=count,duration_seconds=None,preset_snapshot={},config_snapshot={})
    await call('start',cid,'start')
    for n in range(count):
        q=await call('add_question',cid,f'q{n}','主问题')
        await call('answer',cid,f'a{n}',q['id'],'有效')
        for f in range(2):
            q=await call('add_question',cid,f'f{n}-{f}','追问',parent_id=q['id'])
            await call('answer',cid,f'fa{n}-{f}',q['id'],'有效')
        await call('close_main',cid,f'c{n}')
    async with factory() as db:
        item=await db.get(Interview,cid)
        records=await InterviewAIService(factory)._context(db,item,'report','full')
        assert len(records)==count*3
    await engine.dispose()

@pytest.mark.asyncio
async def test_review_material_counts_towards_budget_without_calling_model(tmp_path, monkeypatch):
    engine=create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'material.db'}")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    large={**MATERIAL,'key_points':['参考'*12500]}
    async with factory() as db:
        async with db.begin():
            db.add(InterviewPreset(id='p',kind='bank',name='测试',version=1,active=True,config={}))
            await db.flush()
            for n in range(3):
                db.add(InterviewQuestionBank(id=f'q{n}',preset_id='p',content='题',topic='test',version=1,active=True,content_code=f'T{n}',difficulty='basic',sort_order=n,review_status='approved',reviewed_by='test',reviewed_at=datetime.now(timezone.utc),review_material=large))
    async def call(name,*args,**kw):
        async with factory() as db: return await getattr(InterviewService(db,recommended_rules()),name)(*args,**kw)
    # 模拟旧数据或绕过发布检查，验证评价时仍有完整预算防线。
    monkeypatch.setattr('app.services.question_version.validate_review_capacity', lambda _: None)
    cid=(await call('create_from_preset',key='create',preset_id='p',mode='practice',limit_type='count',main_limit=3,duration_seconds=None,jd=None))['id']
    await call('start',cid,'start'); q=await call('next_question',cid,'q'); a=await call('answer',cid,'a',q['id'],'有效回答')
    calls=[]
    async def model(*args,**kwargs):
        calls.append(1)
        yield '{}'
    with pytest.raises(InterviewConflict,match='预算'):
        await InterviewAIService(factory,model).run(cid,'feedback','feedback',a['id'])
    async with factory() as db: assert (await db.get(InterviewAnswer,a['id'])).content=='有效回答'
    assert not calls
    await engine.dispose()

@pytest.mark.parametrize('count',[3,5,10])
def test_incomplete_output_cannot_be_saved_as_full_report(count):
    from app.llm.client import ModelError
    from app.services.interview_ai import parse_result
    ids={f'a{i}' for i in range(count*3)}
    raw=json.dumps({'summary':'总结','overall_score':70.0,'items':[{'answer_id':'a0','review':'反馈'}]})
    with pytest.raises(ModelError,match='格式'):
        parse_result('full',raw,ids)


def test_material_capacity_unicode_boundaries():
    from app.services.question_version import MAX_REVIEW_MATERIAL_CHARS, validate_review_capacity
    overhead=len(json.dumps({'note':''},ensure_ascii=False,sort_keys=True,separators=(',', ':')))
    limit=MAX_REVIEW_MATERIAL_CHARS-overhead
    validate_review_capacity({'material':{'note':'界'*limit}})
    with pytest.raises(InterviewConflict,match='发布容量'):
        validate_review_capacity({'material':{'note':'界'*(limit+1)}})


@pytest.mark.asyncio
async def test_oversized_approved_material_rejects_new_interview(tmp_path):
    engine=create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'limit.db'}")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async with factory() as db:
        async with db.begin():
            db.add(InterviewPreset(id='p',kind='bank',name='测试',version=1,active=True,config={}))
            await db.flush()
            for n in range(3):
                db.add(InterviewQuestionBank(id=f'q{n}',preset_id='p',content='题',topic='test',version=1,active=True,content_code=f'T{n}',difficulty='basic',sort_order=n,review_status='approved',reviewed_by='test',reviewed_at=datetime.now(timezone.utc),review_material={**MATERIAL,'key_points':['界'*1201]}))
    async with factory() as db:
        with pytest.raises(InterviewConflict,match='发布容量'):
            await InterviewService(db,recommended_rules()).create_from_preset(key='create',preset_id='p',mode='practice',limit_type='count',main_limit=3,duration_seconds=None,jd=None)
    async with factory() as db:
        assert not (await db.scalars(select(Interview))).all()
    await engine.dispose()
