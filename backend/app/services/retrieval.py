"""对内置专题做轻量关键词检索；返回实际提供给模型的来源。"""
import re
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.learning import Topic


def terms(text: str) -> set[str]:
    words = set(re.findall(r'[a-z0-9_]+', text.lower()))
    for sequence in re.findall(r'[\u4e00-\u9fff]+', text):
        words.update(sequence[i:i + 2] for i in range(len(sequence) - 1))
    return {word for word in words if len(word) >= 2}


async def retrieve(db: AsyncSession, query: str, topic_id: str | None) -> list[dict]:
    stmt = select(Topic).order_by(Topic.sort_order, Topic.id)
    if topic_id:
        stmt = stmt.where(Topic.id == topic_id)
    topics = (await db.scalars(stmt)).all()
    query_terms = terms(query)
    candidates = []
    for topic in topics:
        chunks = [chunk.strip() for chunk in re.split(r'\n(?=#{1,3}\s)', topic.content_md) if chunk.strip()]
        for index, chunk in enumerate(chunks):
            passage = chunk[:3000]
            score = len(query_terms & terms(topic.title + ' ' + passage))
            if score:
                candidates.append((score, topic, index, passage))
    candidates.sort(key=lambda row: (-row[0], row[1].sort_order, row[1].id, row[2]))
    # 专题问答无关键词命中时仍提供当前专题的起始内容，明确标为来源。
    if not candidates and topic_id and topics:
        topic = topics[0]
        return [{'topic_id': topic.id, 'title': topic.title, 'excerpt': topic.content_md[:3000]}]
    return [{'topic_id': topic.id, 'title': topic.title, 'excerpt': passage} for _, topic, _, passage in candidates[:3]]
