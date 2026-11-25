from datetime import datetime, timezone
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.db.base import Base
from app.models.interview import Interview, InterviewPreset, InterviewQuestionBank
from app.services.interview import InterviewService, InterviewConflict, recommended_rules

MATERIAL = {'objectives':'测试目标','key_points':['测试要点'],'anchors':{'complete':'完整','adequate':'基本','partial':'部分','insufficient':'不足'},'alternatives':['替代'],'misconceptions':['误区']}


@pytest.mark.asyncio
async def test_jd_selects_frozen_reviewed_bank_and_falls_back(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'selection.db'}")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add_all([InterviewPreset(id='bank', kind='bank', name='测试题库', active=True, version=1, config={}), InterviewPreset(id='role', kind='role', name='测试岗位', active=True, version=1, config={'bank_preset_id':'bank'})])
        await db.flush()
        for i, (title, diff) in enumerate([('数据库事务', 'basic'),('Redis 缓存', 'basic'),('Python 异步', 'basic'),('RAG 检索', 'intermediate')]):
            db.add(InterviewQuestionBank(id=f'q{i}', preset_id='bank', content=title, topic=title, version=1, active=True, content_code=f'T{i}', difficulty=diff, sort_order=i, review_status='approved', reviewed_by='test', reviewed_at=datetime.now(timezone.utc), review_material=MATERIAL))
        await db.commit()
        service=InterviewService(db,recommended_rules())
        async def make(key, jd, difficulty=None):
            return await service.create_from_preset(key=key, preset_id='role', mode='formal', limit_type='count', main_limit=3, duration_seconds=None, jd=jd, difficulty=difficulty)
        first=await make('one', '招聘 Redis 缓存工程师')
        second=await make('two', '招聘数据库事务工程师')
        async with factory() as read:
            a=await read.get(Interview, first['id']); b=await read.get(Interview, second['id'])
            assert a.config_snapshot['question_plan'][0]['id']=='q1'
            assert b.config_snapshot['question_plan'][0]['id']=='q0'
            assert all(q.get('digest') for q in a.config_snapshot['question_plan'])
            assert a.config_snapshot['evaluation_policy']=='reviewed-v1'
        fallback=await make('three','不相关需求')
        async with factory() as read:
            item=await read.get(Interview,fallback['id'])
            assert '未识别' in item.config_snapshot['selection_notice']
        with pytest.raises(InterviewConflict, match='不足'):
            await make('four','', 'intermediate')
        async with factory() as other:
            other.add_all([InterviewPreset(id='legacy-bank', kind='bank', name='旧版', active=True, version=1, config={}), InterviewPreset(id='bad-role', kind='role', name='不可用岗位', active=True, version=1, config={'bank_preset_id':'legacy-bank'})])
            await other.flush()
            other.add(InterviewQuestionBank(id='legacy-q', preset_id='legacy-bank', content='旧题', topic='旧题', version=1, active=True))
            await other.commit()
        with pytest.raises(InterviewConflict, match='必须全部经过审核'):
            await service.create_from_preset(key='bad-role', preset_id='bad-role', mode='formal', limit_type='count', main_limit=3, duration_seconds=None, jd='缓存')
    await engine.dispose()
