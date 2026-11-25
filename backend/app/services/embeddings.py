"""独立的 OpenAI 兼容 embedding 客户端，默认不启用。"""
import math
import hashlib
import httpx
from app.core.config import get_settings, model_configuration_status


def embedding_index_key(settings) -> str:
    """区分不同供应商的同名模型，避免混用不兼容的向量空间。"""
    source = settings.embedding_base_url.rstrip('/') + '\0' + settings.embedding_model
    return 'v1:' + hashlib.sha256(source.encode()).hexdigest()


async def embed(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    if not settings.embedding_base_url or not settings.embedding_model or not settings.embedding_api_key.get_secret_value():
        raise ValueError('embedding 未配置')
    if model_configuration_status(settings.embedding_base_url, settings.embedding_model, settings.embedding_api_key) != 'configured':
        raise ValueError('embedding 服务地址无效')
    async with httpx.AsyncClient(timeout=settings.embedding_timeout, trust_env=False) as client:
        result = await client.post(settings.embedding_base_url.rstrip('/') + '/embeddings',
            headers={'Authorization': 'Bearer ' + settings.embedding_api_key.get_secret_value()},
            json={'model': settings.embedding_model, 'input': texts, 'dimensions': 384})
        result.raise_for_status()
        data = sorted(result.json()['data'], key=lambda item: item['index'])
        if [item['index'] for item in data] != list(range(len(texts))):
            raise ValueError('embedding 返回顺序无效')
    vectors = [item['embedding'] for item in data]
    if len(vectors) != len(texts) or any(len(v) != 384 or any(type(x) not in (int, float) or not math.isfinite(x) for x in v) or not any(v) for v in vectors):
        raise ValueError('embedding 维度或格式无效')
    return vectors
