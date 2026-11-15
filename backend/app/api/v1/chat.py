from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.chat import Conversation, Message
from app.models.learning import Topic

router = APIRouter(tags=["chat"])
Database = Annotated[AsyncSession, Depends(get_db)]


class ConversationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    topic_id: str | None = None


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    topic_id: str | None


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    role: str
    content: str
    status: str


async def conversation_or_404(db: AsyncSession, conversation_id: str) -> Conversation:
    item = await db.get(Conversation, conversation_id)
    if item is None:
        raise HTTPException(404, "会话不存在")
    return item


@router.get('/conversations', response_model=list[ConversationRead])
async def list_conversations(db: Database, topic_id: str | None = Query(default=None)):
    scope = Conversation.topic_id == topic_id if topic_id else Conversation.topic_id.is_(None)
    return (await db.scalars(select(Conversation).where(scope).order_by(Conversation.updated_at.desc()))).all()


@router.post('/conversations', response_model=ConversationRead, status_code=201)
async def create_conversation(body: ConversationCreate, db: Database):
    if body.topic_id and not await db.get(Topic, body.topic_id):
        raise HTTPException(404, "专题不存在")
    item = Conversation(title=body.title.strip(), topic_id=body.topic_id)
    if not item.title:
        raise HTTPException(422, "标题不能为空")
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch('/conversations/{conversation_id}', response_model=ConversationRead)
async def update_conversation(conversation_id: str, body: ConversationUpdate, db: Database):
    item = await conversation_or_404(db, conversation_id)
    item.title = body.title.strip()
    if not item.title:
        raise HTTPException(422, "标题不能为空")
    await db.commit()
    return item


@router.delete('/conversations/{conversation_id}', status_code=204)
async def delete_conversation(conversation_id: str, db: Database):
    item = await conversation_or_404(db, conversation_id)
    await db.delete(item)
    await db.commit()


@router.get('/conversations/{conversation_id}/messages', response_model=list[MessageRead])
async def list_messages(conversation_id: str, db: Database):
    await conversation_or_404(db, conversation_id)
    return (await db.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at, Message.id))).all()


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=12000)


# 单进程内拒绝同一会话的并发生成；部署时使用单 worker。
_active: set[str] = set()


@router.post('/conversations/{conversation_id}/messages/stream')
async def send_message(conversation_id: str, body: MessageCreate, db: Database):
    import asyncio
    import json
    from datetime import datetime, timezone
    from fastapi.responses import StreamingResponse
    from app.core.config import get_settings
    from app.llm.client import ModelError, stream_chat

    content = body.content.strip()
    if not content:
        raise HTTPException(422, "消息不能为空")
    item = await conversation_or_404(db, conversation_id)
    if conversation_id in _active:
        raise HTTPException(409, "该会话正在生成回复")
    _active.add(conversation_id)
    try:
        user = Message(conversation_id=item.id, role="user", content=content, status="complete", created_at=datetime.now(timezone.utc))
        reply = Message(conversation_id=item.id, role="assistant", content="", status="streaming", created_at=datetime.now(timezone.utc))
        db.add_all([user, reply])
        item.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(reply)
        history = (await db.scalars(select(Message).where(
            Message.conversation_id == item.id, Message.id != reply.id,
            Message.status == "complete").order_by(Message.created_at, Message.id))).all()
        messages = [{"role": m.role, "content": m.content} for m in history]
    except BaseException:
        _active.discard(conversation_id)
        raise

    def event(kind: str, data: dict) -> str:
        return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    async def generate():
        parts: list[str] = []
        status = "cancelled"
        try:
            yield event("start", {"id": reply.id})
            async for chunk in stream_chat(get_settings(), messages):
                parts.append(chunk)
                yield event("delta", {"content": chunk})
            status = "complete"
            yield event("done", {})
        except ModelError as exc:
            status = "error"
            yield event("error", {"message": str(exc)})
        except asyncio.CancelledError:
            raise
        finally:
            # 独立 session 保存部分回复，避免流中断时丢失内容。
            from app.db.session import get_session_factory
            try:
                async with get_session_factory()() as save_db:
                    saved = await save_db.get(Message, reply.id)
                    if saved:
                        saved.content = ''.join(parts)
                        saved.status = status
                        await save_db.commit()
            finally:
                _active.discard(conversation_id)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
