"""专题章节检索：关键词与可选 pgvector 结果经 RRF 融合。"""
import hashlib
import re
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.models.knowledge import KnowledgeChunk
from app.models.learning import Topic
from app.services.embeddings import embed, embedding_index_key


def terms(text: str) -> set[str]:
    words = set(re.findall(r'[a-z0-9_]+', text.lower()))
    for sequence in re.findall(r'[\u4e00-\u9fff]+', text):
        words.update(sequence[i:i + 2] for i in range(len(sequence) - 1))
    return {word for word in words if len(word) >= 2}


def topic_chunks(topic: Topic) -> list[dict]:
    result = []
    for chunk in re.split(r'\n(?=#{1,3}\s)', topic.content_md):
        chunk = chunk.strip()
        if not chunk:
            continue
        section = re.sub(r'^#{1,3}\s*', '', chunk.split('\n', 1)[0]).strip()[:200] or topic.title
        excerpt = chunk[:3000]
        identifier = hashlib.sha256((topic.id + '\0' + excerpt).encode()).hexdigest()
        result.append({'id': identifier, 'topic_id': topic.id, 'title': topic.title, 'section': section, 'excerpt': excerpt})
    return result


async def retrieve(db: AsyncSession, query: str, topic_id: str | None) -> list[dict]:
    stmt = select(Topic).order_by(Topic.sort_order, Topic.id)
    if topic_id:
        stmt = stmt.where(Topic.id == topic_id)
    topics = (await db.scalars(stmt)).all()
    chunks = [chunk for topic in topics for chunk in topic_chunks(topic)]
    lookup = {chunk['id']: chunk for chunk in chunks}
    query_terms = terms(query)
    lexical = [(len(query_terms & terms(chunk['title'] + ' ' + chunk['excerpt'])), chunk['id']) for chunk in chunks]
    lexical = [id_ for score, id_ in sorted(lexical, key=lambda row: -row[0]) if score]
    vector = []
    settings = get_settings()
    if db.bind.dialect.name == 'postgresql' and settings.embedding_model:
        try:
            query_vector = (await embed([query], purpose='query'))[0]
            distance = KnowledgeChunk.embedding.cosine_distance(query_vector)
            stmt = select(KnowledgeChunk.id, distance.label('distance')).where(KnowledgeChunk.model == embedding_index_key(settings))
            if topic_id:
                stmt = stmt.where(KnowledgeChunk.topic_id == topic_id)
            async with db.begin_nested():
                rows = (await db.execute(stmt.order_by(distance).limit(50))).all()
            vector = [id_ for id_, dist in rows if id_ in lookup and dist is not None and dist < 0.9]
        except Exception:
            # 未配置、服务异常或索引缺失时退回关键词；不暴露服务地址或凭据。
            pass
    scores = {}
    for ranked in (lexical, vector):
        for rank, id_ in enumerate(ranked):
            scores[id_] = scores.get(id_, 0) + 1 / (60 + rank + 1)
    selected = sorted(scores, key=lambda id_: -scores[id_])[:3]
    if not selected and topic_id and chunks:
        selected = [chunks[0]['id']]
    return [lookup[id_] for id_ in selected]
