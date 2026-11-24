"""模拟模型验证评价提示词的来源约束，不代表模型语义可靠性。"""
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.interview import InterviewPreset, InterviewQuestionBank
from app.services.interview import InterviewService, recommended_rules
from app.services.interview_ai import InterviewAIService, parse_result


ANSWER = '阻塞数据库工作可以移到独立工作进程，事件循环通过队列或 RPC 等待结果；需要限制排队、配置超时，并承担额外部署和进程通信成本。'
MATERIAL = {
    'objectives': '理解阻塞与解决方案',
    'key_points': ['异步驱动或受控线程池'],
    'anchors': {'complete': '完整分析', 'adequate': '基本分析', 'partial': '部分分析', 'insufficient': '缺少分析'},
    'alternatives': ['独立工作进程'], 'misconceptions': ['无限创建线程'],
}


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['feedback', 'full', 'partial'])
async def test_review_sources_are_explicit_and_suggestions_remain_allowed(tmp_path, kind):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'source.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        async with db.begin():
            db.add(InterviewPreset(id='p', kind='bank', name='测试', version=1, active=True, config={}))
            await db.flush()
            for n in range(3):
                db.add(InterviewQuestionBank(id=f'q{n}', preset_id='p', content=f'测试题目{n}', topic='测试',
                    version=1, active=True, content_code=f'T{n}', difficulty='basic', sort_order=n,
                    review_status='approved', reviewed_by='test-only', reviewed_at=datetime.now(timezone.utc),
                    review_material=MATERIAL))
    async def call(name, *args, **kwargs):
        async with factory() as db:
            return await getattr(InterviewService(db, recommended_rules()), name)(*args, **kwargs)

    cid = (await call('create_from_preset', key='create', preset_id='p', mode='practice', limit_type='count',
                      main_limit=3, duration_seconds=None, jd=None))['id']
    await call('start', cid, 'start')
    answers = []
    first_id = None
    for n in range(3 if kind != 'feedback' else 1):
        q = await call('next_question', cid, f'next{n}')
        a = await call('answer', cid, f'answer{n}', q['id'], ANSWER if n == 0 else f'其他回答{n}')
        answers.append(a['id'])
        if n == 0: first_id = a['id']
        if kind != 'feedback' and (kind == 'full' or n < 2):
            await call('close_main', cid, f'close{n}', question_id=q['id'])
    if kind == 'partial':
        await call('end', cid, 'end', 'terminated', '测试主动终止')

    calls = []
    async def simulated_model(settings, messages, *, max_tokens=None):
        calls.append(1)
        system = messages[0]['content']
        assert 'answer 是判断候选人说过什么的唯一证据' in system
        assert '逐题评价只能依据对应 answer_id 的 answer' in system
        assert '不能描述为候选人已提出' in system
        records = json.loads(messages[1]['content'])
        assert [r['answer_id'] for r in records] == answers
        assert records[0]['answer'] == ANSWER and '线程池' not in records[0]['answer']
        assert records[0]['question'] == '测试题目0' and records[0]['review_material'] == MATERIAL
        review = '候选人提出独立工作进程，可补充考虑线程池；未解释阻塞事件循环的原因。'
        if kind == 'feedback':
            yield json.dumps({'feedback': review}, ensure_ascii=False)
        else:
            result = {'summary': '可继续说明技术原因', 'items': [
                {'answer_id': r['answer_id'], 'review': review if i == 0 else '回答包含实际作答'}
                for i, r in enumerate(records)]}
            if kind == 'full': result['overall_score'] = 68
            yield json.dumps(result, ensure_ascii=False)

    ai = InterviewAIService(factory, simulated_model)
    result = await ai.run(cid, 'evaluation', 'feedback' if kind == 'feedback' else 'report',
                          first_id if kind == 'feedback' else kind)
    assert result['status'] == 'complete' and calls == [1]
    review = result['result']['feedback'] if kind == 'feedback' else result['result']['items'][0]['review']
    assert '提出独立工作进程' in review and '补充考虑线程池' in review and '未解释阻塞' in review
    if kind == 'full': assert result['result']['overall_score'] == 68
    if kind == 'partial': assert 'overall_score' not in result['result']
    await engine.dispose()


def test_structure_validation_does_not_prove_attribution():
    # 历史问题说明：结构合法不等于可以证明模型的语义归因正确。
    raw = json.dumps({'feedback': '候选人提出了线程池方案'}, ensure_ascii=False)
    assert parse_result('feedback', raw, {'a'})['feedback'] == '候选人提出了线程池方案'
