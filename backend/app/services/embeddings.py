"""本地 E5 与可选 OpenAI 兼容 embedding。"""
import asyncio
from functools import lru_cache
import math
import hashlib
import threading
import httpx
from app.core.config import get_settings, model_configuration_status

_model_lock = threading.Lock()


def embedding_index_key(settings) -> str:
    """区分不同供应商的同名模型，避免混用不兼容的向量空间。"""
    if settings.embedding_provider == 'local':
        source = 'local-e5-mean-normalized-v1\0' + settings.embedding_model
    else:
        source = settings.embedding_base_url.rstrip('/') + '\0' + settings.embedding_model
    return 'v1:' + hashlib.sha256(source.encode()).hexdigest()


@lru_cache(maxsize=2)
def _local_model(model: str, cache_dir: str, allow_download: bool):
    if model != 'intfloat/multilingual-e5-small':
        raise ValueError('不支持的本地 embedding 模型')
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType
    with _model_lock:
        if not any(item['model'].lower() == model.lower() for item in TextEmbedding.list_supported_models()):
            TextEmbedding.add_custom_model(model=model, pooling=PoolingType.MEAN, normalization=True,
                                           sources=ModelSource(hf=model), dim=384, model_file='onnx/model.onnx')
    return TextEmbedding(model_name=model, cache_dir=cache_dir, local_files_only=not allow_download,
                         providers=['CPUExecutionProvider'])


def _local_embed(settings, texts, purpose, allow_download):
    model = _local_model(settings.embedding_model, settings.embedding_cache_dir, allow_download)
    return [vector.tolist() for vector in model.embed([f'{purpose}: {text}' for text in texts])]


async def embed(texts: list[str], *, purpose: str = 'passage', allow_download: bool = False) -> list[list[float]]:
    settings = get_settings()
    if purpose not in {'query', 'passage'}:
        raise ValueError('embedding 用途无效')
    if settings.embedding_provider == 'local':
        vectors = await asyncio.to_thread(_local_embed, settings, texts, purpose, allow_download)
    elif settings.embedding_provider == 'openai':
        vectors = await _remote_embed(settings, texts)
    else:
        raise ValueError('embedding provider 无效')
    if len(vectors) != len(texts) or any(len(v) != 384 or any(type(x) not in (int, float) or not math.isfinite(x) for x in v) or not any(v) for v in vectors):
        raise ValueError('embedding 维度或格式无效')
    return vectors


async def _remote_embed(settings, texts):
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
    return [item['embedding'] for item in data]
