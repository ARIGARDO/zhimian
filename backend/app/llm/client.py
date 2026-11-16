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
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            raise ModelError("模型服务认证失败，请检查密钥和权限") from exc
        if exc.response.status_code in (400, 404, 405, 422):
            raise ModelError("模型接口或请求不兼容，请检查地址和模型名称") from exc
        raise ModelError("模型服务返回错误，请稍后重试") from exc
    except httpx.TimeoutException as exc:
        raise ModelError("模型服务请求超时") from exc
    except httpx.RequestError as exc:
        raise ModelError("无法连接模型服务，请检查网络和服务地址") from exc
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ModelError("模型接口返回的数据不兼容") from exc
