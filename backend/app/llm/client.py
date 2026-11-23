"""OpenAI 兼容的流式聊天接口。"""
import json
import re
from collections.abc import AsyncIterator

import httpx

from app.core.config import Settings
from app.llm.test_ledger import update_ledger


class ModelError(Exception):
    """不暴露上游响应和凭据的模型错误。"""


async def stream_chat(settings: Settings, messages: list[dict[str, str]], *, max_tokens: int | None = None) -> AsyncIterator[str]:
    key = settings.model_api_key.get_secret_value()
    if not key or not settings.model_name:
        raise ModelError("请先在服务端配置模型名称和 API Key")
    url = settings.model_base_url.rstrip("/") + "/chat/completions"
    payload = {"model": settings.model_name, "messages": messages, "stream": True}
    if settings.model_enable_thinking is not None:
        payload["enable_thinking"] = settings.model_enable_thinking
    if settings.model_test_include_usage:
        if not settings.model_test_ledger_path:
            raise ModelError("验收用量记录需要配置共享账本")
        payload["stream_options"] = {"include_usage": True}
    if max_tokens is not None:
        if max_tokens < 1: raise ModelError("模型输出上限配置无效")
        payload["max_tokens"] = max_tokens
    ticket = None
    details = {'status': 'failed', 'provider_id': None, 'provider_request_id': None, 'model': None,
               'prompt_tokens': None, 'completion_tokens': None, 'total_tokens': None}
    if settings.model_test_ledger_path:
        try:
            ticket = update_ledger(settings.model_test_ledger_path)
        except (OSError, ValueError, TypeError) as exc:
            raise ModelError("验收账本不可用或请求已达上限") from exc
    def identifier(value):
        return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', value) else None
    truncated = False
    try:
        async with httpx.AsyncClient(timeout=settings.model_timeout, trust_env=False) as client:
            async with client.stream("POST", url, headers={"Authorization": f"Bearer {key}"}, json=payload) as response:
                details['provider_request_id'] = identifier(response.headers.get('x-request-id'))
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        if truncated:
                            raise ModelError("模型输出超出预算，请调整输出上限后重试")
                        details['status'] = 'complete'
                        return
                    event = json.loads(data)
                    details['provider_id'] = identifier(event.get('id')) or details['provider_id']
                    details['model'] = identifier(event.get('model')) or details['model']
                    usage = event.get('usage')
                    if isinstance(usage, dict):
                        for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
                            value = usage.get(field)
                            if type(value) is int and value >= 0:
                                details[field] = value
                    choices = event.get("choices", [])
                    if choices:
                        if choices[0].get("finish_reason") == "length":
                            if not settings.model_test_include_usage:
                                raise ModelError("模型输出超出预算，请调整输出上限后重试")
                            truncated = True
                        content = choices[0].get("delta", {}).get("content")
                        if isinstance(content, str) and not truncated:
                            yield content
                if truncated:
                    raise ModelError("模型输出超出预算，请调整输出上限后重试")
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
    finally:
        if ticket:
            try:
                update_ledger(settings.model_test_ledger_path, ticket, details)
            except (OSError, ValueError, TypeError) as exc:
                raise ModelError("验收账本记录失败") from exc
