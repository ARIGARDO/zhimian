"""独立的 OpenAI 兼容 embedding 客户端，默认不启用。"""
import math
import httpx
from app.core.config import get_settings


async def embed(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    if not settings.embedding_base_url or not settings.embedding_model or not settings.embedding_api_key.get_secret_value():
        raise ValueError('embedding 未配置')
    async with httpx.AsyncClient(timeout=settings.embedding_timeout, trust_env=False) as client:
        result = await client.post(settings.embedding_base_url.rstrip('/') + '/embeddings',
            headers={'Authorization': 'Bearer ' + settings.embedding_api_key.get_secret_value()},
            json={'model': settings.embedding_model, 'input': texts, 'dimensions': 384})
        result.raise_for_status()
        data = sorted(result.json()['data'], key=lambda item: item['index'])
    vectors = [item['embedding'] for item in data]
    if len(vectors) != len(texts) or any(len(v) != 384 or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in v) for v in vectors):
        raise ValueError('embedding 维度或格式无效')
    return vectors
