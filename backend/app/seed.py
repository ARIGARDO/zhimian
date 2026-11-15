"""运行 `python -m app.seed` 插入 M1 内置学习文章，重复运行不会覆盖已有数据。"""
import asyncio

from sqlalchemy.dialects.postgresql import insert

from app.content.seed_topics import TOPICS
from app.db.session import get_session_factory, get_engine
from app.models.learning import Topic


async def seed() -> None:
    async with get_session_factory()() as db:
        for item in TOPICS:
            stmt = insert(Topic).values(**item).on_conflict_do_nothing(index_elements=[Topic.id])
            await db.execute(stmt)
        await db.commit()
    await get_engine().dispose()
    print(f"已确保 {len(TOPICS)} 个内置专题存在。")


if __name__ == "__main__":
    asyncio.run(seed())
