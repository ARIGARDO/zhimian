"""显式构建向量索引。运行会调用配置的 embedding 服务，可能产生费用。"""
import asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.core.config import get_settings
from app.db.session import get_engine, get_session_factory
from app.models.knowledge import KnowledgeChunk
from app.models.learning import Topic
from app.services.embeddings import embed
from app.services.retrieval import topic_chunks


async def main():
    settings = get_settings()
    if not settings.embedding_model or not settings.embedding_base_url:
        raise RuntimeError('请先配置 embedding 服务；本命令可能产生模型调用费用')
    factory = get_session_factory()
    async with factory() as db:
        topics = (await db.scalars(select(Topic))).all()
        chunks = [chunk for topic in topics for chunk in topic_chunks(topic)]
        existing = set((await db.scalars(select(KnowledgeChunk.id).where(KnowledgeChunk.model == settings.embedding_model))).all())
    pending = [chunk for chunk in chunks if chunk['id'] not in existing]
    for chunk in pending:
        vector = (await embed([chunk['excerpt']]))[0]
        async with factory() as db:
            stmt = insert(KnowledgeChunk).values(id=chunk['id'], topic_id=chunk['topic_id'], section=chunk['section'], excerpt=chunk['excerpt'], model=settings.embedding_model, embedding=vector)
            stmt = stmt.on_conflict_do_update(index_elements=['id'], set_={'model': settings.embedding_model, 'embedding': vector})
            await db.execute(stmt)
            await db.commit()
    await get_engine().dispose()
    print(f'已索引 {len(pending)} 个专题片段；已有 {len(existing)} 个。')


if __name__ == '__main__':
    asyncio.run(main())
