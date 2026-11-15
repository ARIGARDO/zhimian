import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.base import Base
from app.db.session import get_db
from app.llm.client import ModelError, stream_chat
from app.main import app
from app.models.learning import Topic


@pytest.mark.asyncio
async def test_chat_scopes_and_stream(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(Topic(id='topic', category='x', category_label='方向', title='专题', summary='摘要', content_md='专题资料', sort_order=0))
        await db.commit()

    async def db_override():
        async with factory() as db:
            yield db

    seen = []
    async def fake_stream(settings, messages):
        seen.extend(messages)
        yield '你好'
        yield '世界'

    monkeypatch.setattr('app.db.session.get_session_factory', lambda: factory)
    monkeypatch.setattr('app.llm.client.stream_chat', fake_stream)
    app.dependency_overrides[get_db] = db_override
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            general = (await client.post('/api/v1/conversations', json={'title': '普通'})).json()
            topic = (await client.post('/api/v1/conversations', json={'title': '专题', 'topic_id': 'topic'})).json()
            assert (await client.post('/api/v1/conversations', json={'title': 'x', 'topic_id': 'missing'})).status_code == 404
            assert [c['id'] for c in (await client.get('/api/v1/conversations')).json()] == [general['id']]
            assert [c['id'] for c in (await client.get('/api/v1/conversations?topic_id=topic')).json()] == [topic['id']]
            response = await client.post(f"/api/v1/conversations/{topic['id']}/messages/stream", json={'content': '解释一下'})
            assert response.status_code == 200 and 'event: done' in response.text
            assert '专题资料' in seen[0]['content'] and seen[-1]['content'] == '解释一下'
            messages = (await client.get(f"/api/v1/conversations/{topic['id']}/messages")).json()
            assert [(m['role'], m['content'], m['status']) for m in messages] == [('user', '解释一下', 'complete'), ('assistant', '你好世界', 'complete')]
            assert (await client.delete(f"/api/v1/conversations/{topic['id']}")).status_code == 204
            assert (await client.get(f"/api/v1/conversations/{topic['id']}/messages")).status_code == 404
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_model_configuration_error():
    with pytest.raises(ModelError, match='配置'):
        _ = [part async for part in stream_chat(Settings(model_name='', model_api_key=''), [])]


@pytest.mark.asyncio
async def test_adapter_reads_openai_events(monkeypatch):
    async def handler(request):
        assert request.headers['authorization'] == 'Bearer test-key'
        assert request.url.path == '/v1/chat/completions'
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"测试"}}]}\n\ndata: [DONE]\n\n')

    original = httpx.AsyncClient
    monkeypatch.setattr('app.llm.client.httpx.AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler)))
    settings = Settings(model_name='test', model_api_key='test-key')
    assert [part async for part in stream_chat(settings, [{'role': 'user', 'content': 'hi'}])] == ['测试']
