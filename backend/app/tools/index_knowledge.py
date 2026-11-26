"""显式构建向量索引；本地模型首次运行需下载，远程服务可能产生费用。"""
import asyncio
import argparse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.core.config import get_settings
from app.db.session import get_engine, get_session_factory
from app.models.knowledge import KnowledgeChunk
from app.models.learning import Topic
from app.services.embeddings import embed, embedding_index_key
from app.services.retrieval import topic_chunks


async def main(force: bool = False):
    settings = get_settings()
    if not settings.embedding_model or (settings.embedding_provider == 'openai' and not settings.embedding_base_url):
        raise RuntimeError('请先配置 embedding 服务；本命令可能产生模型调用费用')
    factory = get_session_factory()
    index_key = embedding_index_key(settings)
    async with factory() as db:
        topics = (await db.scalars(select(Topic))).all()
        chunks = [chunk for topic in topics for chunk in topic_chunks(topic)]
        existing = set((await db.scalars(select(KnowledgeChunk.id).where(KnowledgeChunk.model == index_key))).all())
    pending = [chunk for chunk in chunks if force or chunk['id'] not in existing]
    for chunk in pending:
        vector = (await embed([chunk['excerpt']], purpose='passage', allow_download=True))[0]
        async with factory() as db:
            stmt = insert(KnowledgeChunk).values(id=chunk['id'], topic_id=chunk['topic_id'], section=chunk['section'], excerpt=chunk['excerpt'], model=index_key, embedding=vector)
            stmt = stmt.on_conflict_do_update(index_elements=['id'], set_={'model': index_key, 'embedding': vector})
            await db.execute(stmt)
            await db.commit()
    await get_engine().dispose()
    print(f'已索引 {len(pending)} 个专题片段；已有 {len(existing)} 个。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force', action='store_true', help='重新索引所有片段；可能产生额外费用')
    asyncio.run(main(force=parser.parse_args().force))
