"""向严格限定的演示数据库写入未审核的示例题，不修改正式题库。"""
import asyncio
import os
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
        await db.commit()
    await get_engine().dispose()


if __name__ == '__main__':
    asyncio.run(seed_demo())
