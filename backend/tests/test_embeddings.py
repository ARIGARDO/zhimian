import json
import httpx
import pytest
from pydantic import SecretStr
from app.core.config import Settings
from app.services.embeddings import embed, embedding_index_key


@pytest.mark.asyncio
async def test_embedding_validation_and_missing_configuration(monkeypatch):
    monkeypatch.setattr('app.services.embeddings.get_settings', lambda: Settings(_env_file=None, embedding_provider='openai', embedding_model=''))
    with pytest.raises(ValueError, match='未配置'):
        await embed(['test'])
    monkeypatch.setattr('app.services.embeddings.get_settings', lambda: Settings(_env_file=None, embedding_provider='openai', embedding_base_url='http://local', embedding_model='mock', embedding_api_key=SecretStr('fake')))
    original=httpx.AsyncClient
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'data': [{'index': 0, 'embedding': [1.0] * 384}]})
    def mocked(**_kwargs):
        return original(transport=httpx.MockTransport(handler))
    monkeypatch.setattr('app.services.embeddings.httpx.AsyncClient', mocked)
    assert len((await embed(['test']))[0])==384
    assert requests == [{'model': 'mock', 'input': ['test'], 'dimensions': 384}]


@pytest.mark.asyncio
@pytest.mark.parametrize('vector', [[1.0] * 383, [0.0] * 384, [True] * 384])
async def test_embedding_rejects_invalid_dimensions_or_values(monkeypatch, vector):
    monkeypatch.setattr('app.services.embeddings.get_settings', lambda: Settings(_env_file=None, embedding_provider='openai', embedding_base_url='http://local', embedding_model='mock', embedding_api_key=SecretStr('fake')))
    original = httpx.AsyncClient
    monkeypatch.setattr('app.services.embeddings.httpx.AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'data': [{'index': 0, 'embedding': vector}]}))))
    with pytest.raises(ValueError):
        await embed(['test'])


def test_embedding_index_key_separates_providers_and_normalizes_url():
    one = Settings(_env_file=None, embedding_provider='openai', embedding_base_url='https://first.example/v1/', embedding_model='same')
    same = Settings(_env_file=None, embedding_provider='openai', embedding_base_url='https://first.example/v1', embedding_model='same')
    other = Settings(_env_file=None, embedding_provider='openai', embedding_base_url='https://second.example/v1', embedding_model='same')
    assert embedding_index_key(one) == embedding_index_key(same)
    assert embedding_index_key(one) != embedding_index_key(other)


@pytest.mark.asyncio
async def test_local_prefixes_and_validation(monkeypatch):
    from app.services import embeddings
    received = []
    class FakeModel:
        def embed(self, texts):
            received.extend(texts)
            class Vector:
                def tolist(self): return [1.0 / (384 ** 0.5)] * 384
            return [Vector() for _ in texts]
    monkeypatch.setattr(embeddings, '_local_model', lambda *args: FakeModel())
    monkeypatch.setattr(embeddings, 'get_settings', lambda: Settings(_env_file=None))
    await embed(['数据库事务'], purpose='passage')
    await embed(['事务是什么'], purpose='query')
    assert received == ['passage: 数据库事务', 'query: 事务是什么']


def test_local_and_remote_index_identity_differ():
    local = Settings(_env_file=None)
    remote = Settings(_env_file=None, embedding_provider='openai', embedding_model=local.embedding_model)
    assert embedding_index_key(local) != embedding_index_key(remote)
