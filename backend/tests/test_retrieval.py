import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.db.base import Base
from app.models.learning import Topic
from app.services.retrieval import retrieve


@pytest.mark.asyncio
async def test_retrieval_scope_and_no_match(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'retrieval.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        for id_, text in [('python', '# 异步编程\n事件循环处理异步任务'), ('ai', '# 检索增强\n向量检索文档')]:
            db.add(Topic(id=id_, title=id_, category=id_, category_label=id_, summary=id_, content_md=text, sort_order=1))
        await db.commit()
        found = await retrieve(db, '如何进行向量检索', None)
        assert found and all(item['topic_id'] == 'ai' for item in found)
        scoped = await retrieve(db, '向量检索', 'python')
        assert scoped and all(item['topic_id'] == 'python' for item in scoped)
        assert await retrieve(db, 'unmatchedkeyword', None) == []
    await engine.dispose()


def test_sections_have_stable_ids_and_source_labels():
    from app.services.retrieval import topic_chunks
    topic=Topic(id='x', title='标题', content_md='# 标题\n前言\n## 事务\n事务内容')
    first=topic_chunks(topic)
    assert first == topic_chunks(topic)
    assert first[-1]['section']=='事务' and first[-1]['topic_id']=='x'
    assert first[-1]['excerpt'].startswith('## 事务')
