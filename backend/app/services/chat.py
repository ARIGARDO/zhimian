"""会话生成锁与历史预算。"""
import hashlib

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Message

# 开发测试使用 SQLite 时的进程内锁；生产 PostgreSQL 使用会话级 advisory lock。
_local: set[str] = set()


def lock_key(conversation_id: str) -> int:
    return int.from_bytes(hashlib.sha256(conversation_id.encode()).digest()[:8], 'big', signed=True)


async def acquire(db: AsyncSession, conversation_id: str) -> bool:
    if db.bind.dialect.name == 'postgresql':
        return bool(await db.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': lock_key(conversation_id)}))
    if conversation_id in _local:
        return False
    _local.add(conversation_id)
    return True


async def release(db: AsyncSession, conversation_id: str) -> None:
    if db.bind.dialect.name == 'postgresql':
        await db.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': lock_key(conversation_id)})
    else:
        _local.discard(conversation_id)


async def recover(db: AsyncSession, conversation_id: str) -> None:
    await db.execute(update(Message).where(Message.conversation_id == conversation_id, Message.status == 'streaming').values(status='cancelled'))
    await db.commit()


def bounded_history(messages: list[Message], budget: int = 24000) -> list[dict[str, str]]:
    # 字符预算不是 token 预算；始终保留最新用户提问，并优先保留最近上下文。
    result = []
    remaining = budget
    for message in reversed(messages):
        if remaining <= 0:
            break
        content = message.content[-remaining:]
        result.append({'role': message.role, 'content': content})
        remaining -= len(content)
    return list(reversed(result))
