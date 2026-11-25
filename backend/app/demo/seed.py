"""向严格限定的演示数据库写入未审核的示例题，不修改正式题库。"""
import asyncio
import os
from datetime import datetime, timezone
from app.tools.import_interview_draft import load_manifest
from urllib.parse import urlsplit

from sqlalchemy.dialects.postgresql import insert
from app.db.session import get_engine, get_session_factory
from app.models.interview import InterviewPreset, InterviewQuestionBank


async def seed_demo():
    url = urlsplit(os.environ.get('DATABASE_URL', ''))
    if os.environ.get('ZHIMIAN_DEMO_ONLY') != 'true' or url.hostname != 'demo-db' or url.path != '/zhimian_demo' or url.username != 'zhimian_demo':
        raise RuntimeError('仅允许在独立演示数据库中初始化示例题')
    presets = [
        ('demo-python', 'bank', 'Python 后端演示题库（未审核）', [
            ('异步接口为什么不能直接执行耗时阻塞操作？', '异步编程'),
            ('如何避免接口重复提交导致重复处理？', '接口设计'),
            ('数据库事务失败后应如何处理？', '数据库'),
        ]),
        ('demo-ai', 'bank', 'AI 应用演示题库（未审核）', [
            ('检索增强生成中的检索环节有什么作用？', 'RAG'),
            ('如何检查模型输出是否符合预期格式？', '结构化输出'),
            ('模型回答缺少依据时可以如何排查？', '模型评估'),
        ]),
        ('demo-role', 'role', '岗位定向演示（支持 JD，未审核）', [
            ('请说明异步接口的阻塞风险。', '异步编程'),
            ('如何设计可重试的服务接口？', '接口设计'),
            ('如何在调用外部服务时保护数据库事务？', '数据库'),
        ]),
    ]
    async with get_session_factory()() as db:
        for preset_id, kind, name, questions in presets:
            await db.execute(insert(InterviewPreset).values(id=preset_id, kind=kind, name=name, version=1, active=True, config={}).on_conflict_do_nothing(index_elements=['id']))
            for index, (content, topic) in enumerate(questions, 1):
                await db.execute(insert(InterviewQuestionBank).values(id=(f'demo-{index:02d}' if preset_id == 'demo-python' else f'{preset_id}-{index:02d}'), preset_id=preset_id, content=content, topic=topic, version=1, active=True).on_conflict_do_nothing(index_elements=['id']))
        # 审核标记仅存在于演示数据库，用于验证冻结版本，不代表正式审核。
        presets_data, questions_data, _ = load_manifest('/demo-data/questions.json')
        mapping = {'bank-python-v1': 'demo-reviewed-python', 'bank-ai-v1': 'demo-reviewed-ai'}
        for preset in presets_data:
            demo_id = mapping[preset['id']]
            await db.execute(insert(InterviewPreset).values(id=demo_id, kind='bank', name='隔离测试审核 · ' + preset['name'], version=1, active=True, config={}).on_conflict_do_nothing(index_elements=['id']))
        for q in questions_data:
            await db.execute(insert(InterviewQuestionBank).values(id='demo-' + q['id'], preset_id=mapping[q['preset_id']], content=q['content'], topic=q['topic'], version=q['version'], active=True, content_code=q['code'], difficulty=q['difficulty'], sort_order=q['sort_order'], review_status='approved', reviewed_by='隔离测试标记', reviewed_at=datetime.now(timezone.utc), review_material=q['material']).on_conflict_do_nothing(index_elements=['id']))
        await db.execute(insert(InterviewPreset).values(id='demo-reviewed-role', kind='role', name='隔离测试 · Python 岗位（JD 匹配）', version=1, active=True, config={'bank_preset_id': 'demo-reviewed-python'}).on_conflict_do_nothing(index_elements=['id']))
        await db.commit()
    await get_engine().dispose()


if __name__ == '__main__':
    asyncio.run(seed_demo())
