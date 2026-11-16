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
            assert (await client.get(f"/api/v1/conversations/{topic['id']}/messages?topic_id=other")).status_code == 404
            assert (await client.get(f"/api/v1/conversations/{topic['id']}/messages")).status_code == 404
            assert (await client.post(f"/api/v1/conversations/{topic['id']}/messages/stream?topic_id=other", json={'content':'x'})).status_code == 404
            response = await client.post(f"/api/v1/conversations/{topic['id']}/messages/stream?topic_id=topic", json={'content': '解释一下'})
            assert response.status_code == 200 and 'event: done' in response.text and '"user_id"' in response.text
            assert '专题资料' in seen[0]['content'] and seen[-1]['content'] == '解释一下'
            messages = (await client.get(f"/api/v1/conversations/{topic['id']}/messages?topic_id=topic")).json()
            assert [(m['role'], m['content'], m['status']) for m in messages] == [('user', '解释一下', 'complete'), ('assistant', '你好世界', 'complete')]
            assert (await client.delete(f"/api/v1/conversations/{topic['id']}?topic_id=topic")).status_code == 204
            assert (await client.get(f"/api/v1/conversations/{topic['id']}/messages?topic_id=topic")).status_code == 404
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


def test_history_budget_keeps_latest():
    from app.models.chat import Message
    from app.services.chat import bounded_history
    history = [Message(role='user', content='a' * 9), Message(role='assistant', content='b' * 9), Message(role='user', content='latest')]
    result = bounded_history(history, budget=12)
    assert result == [{'role': 'assistant', 'content': 'b' * 6}, {'role': 'user', 'content': 'latest'}]


@pytest.mark.asyncio
async def test_lock_and_recover(tmp_path):
    from app.models.chat import Conversation, Message
    from app.services.chat import acquire, release, recover
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'locks.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(Conversation(id='c', title='test'))
        db.add(Message(id='m', conversation_id='c', role='assistant', content='partial', status='streaming'))
        await db.commit()
    async with factory() as first, factory() as second:
        assert await acquire(first, 'c')
        assert not await acquire(second, 'c')
        await release(first, 'c')
        assert await acquire(second, 'c')
        await recover(second, 'c')
        assert (await second.get(Message, 'm')).status == 'cancelled'
        await release(second, 'c')
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(('failure', 'expected'), [
    ('auth', '认证失败'), ('timeout', '超时'), ('network', '无法连接'), ('incompatible', '不兼容'),
])
async def test_model_error_categories(monkeypatch, failure, expected):
    async def handler(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('private details', request=request)
        if failure == 'network':
            raise httpx.ConnectError('private details', request=request)
        if failure == 'auth':
            return httpx.Response(401, text='secret upstream response')
        return httpx.Response(200, text='data: invalid-json\n\n')
    original = httpx.AsyncClient
    monkeypatch.setattr('app.llm.client.httpx.AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler)))
    with pytest.raises(ModelError, match=expected) as error:
        _ = [part async for part in stream_chat(Settings(model_name='test', model_api_key='private-key'), [])]
    assert 'private' not in str(error.value) and 'secret' not in str(error.value)


@pytest.mark.asyncio
async def test_model_token_limit_is_optional_and_explicit(monkeypatch):
    import json
    seen=[]
    async def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200,text='data: [DONE]\n\n')
    original=httpx.AsyncClient
    monkeypatch.setattr('app.llm.client.httpx.AsyncClient',lambda **kwargs: original(transport=httpx.MockTransport(handler)))
    settings=Settings(model_name='test',model_api_key='test-key')
    _=[v async for v in stream_chat(settings, [])]
    _=[v async for v in stream_chat(settings, [], max_tokens=321)]
    assert 'max_tokens' not in seen[0] and seen[1]['max_tokens']==321


@pytest.mark.asyncio
async def test_model_unsupported_token_parameter_is_visible(monkeypatch):
    async def handler(request): return httpx.Response(400, text='provider rejected parameter')
    original=httpx.AsyncClient
    monkeypatch.setattr('app.llm.client.httpx.AsyncClient',lambda **kwargs: original(transport=httpx.MockTransport(handler)))
    with pytest.raises(ModelError,match='不兼容'):
        _=[part async for part in stream_chat(Settings(model_name='test',model_api_key='test-key'),[],max_tokens=100)]
