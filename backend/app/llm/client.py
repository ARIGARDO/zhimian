"""OpenAI 兼容的流式聊天接口。"""
import json
from collections.abc import AsyncIterator

import httpx

from app.core.config import Settings


class ModelError(Exception):
    """不暴露上游响应和凭据的模型错误。"""


async def stream_chat(settings: Settings, messages: list[dict[str, str]]) -> AsyncIterator[str]:
    key = settings.model_api_key.get_secret_value()
    if not key or not settings.model_name:
        raise ModelError("请先在服务端配置模型名称和 API Key")
    url = settings.model_base_url.rstrip("/") + "/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=settings.model_timeout, trust_env=False) as client:
            async with client.stream("POST", url, headers={"Authorization": f"Bearer {key}"}, json={
                "model": settings.model_name, "messages": messages, "stream": True,
            }) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    event = json.loads(data)
                    choices = event.get("choices", [])
                    if choices:
                        content = choices[0].get("delta", {}).get("content")
                        if isinstance(content, str):
                            yield content
                raise ModelError("模型连接意外中断")
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise ModelError("模型服务请求失败，请检查服务端配置或稍后重试") from exc
