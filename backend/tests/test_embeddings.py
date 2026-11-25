import httpx
import pytest
from pydantic import SecretStr
from app.core.config import Settings
from app.services.embeddings import embed


@pytest.mark.asyncio
async def test_embedding_validation_and_missing_configuration(monkeypatch):
    monkeypatch.setattr('app.services.embeddings.get_settings', lambda: Settings(_env_file=None))
    with pytest.raises(ValueError, match='未配置'):
        await embed(['test'])
    monkeypatch.setattr('app.services.embeddings.get_settings', lambda: Settings(_env_file=None, embedding_base_url='http://local', embedding_model='mock', embedding_api_key=SecretStr('fake')))
    original=httpx.AsyncClient
    def mocked(**_kwargs):
        return original(transport=httpx.MockTransport(lambda request: httpx.Response(200,json={'data':[{'index':0,'embedding':[1.0]*384}]})))
    monkeypatch.setattr('app.services.embeddings.httpx.AsyncClient', mocked)
    assert len((await embed(['test']))[0])==384
