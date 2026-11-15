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
