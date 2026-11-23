"""无数据库的流式用量和验收预算测试。"""
import json
from concurrent.futures import ProcessPoolExecutor
import httpx
import pytest
from app.core.config import Settings
from app.llm.client import ModelError, stream_chat
from app.llm.test_ledger import operation_id, update_ledger


def reserve(path):
    try:
        update_ledger(path)
        return True
    except ValueError:
        return False


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / 'ledger.json'
    path.write_text('{"version":1,"limit":8,"requests":[]}', encoding='utf-8')
    path.chmod(0o600)
    return path


def settings(**kwargs):
    return Settings(_env_file=None, model_name='test', model_api_key='test-key', **kwargs)


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr('app.llm.client.httpx.AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler)))


def records(path):
    return json.loads(path.read_text(encoding='utf-8'))['requests']


@pytest.mark.asyncio
async def test_optional_parameters_and_usage(monkeypatch, ledger):
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, headers={'x-request-id': 'header-id'}, text=(
            'data: {"id":"provider-1","model":"qwen3.8-flash","choices":[{"delta":{"content":"你好"}}]}\n\n'
            'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":4,"total_tokens":16}}\n\n'
            'data: [DONE]\n\n'))
    transport(monkeypatch, handler)
    assert [x async for x in stream_chat(settings(), [])] == ['你好']
    assert seen[0] == {'model': 'test', 'messages': [], 'stream': True}
    cfg = settings(model_enable_thinking=False, model_test_include_usage=True, model_test_ledger_path=str(ledger))
    assert [x async for x in stream_chat(cfg, [])] == ['你好']
    assert seen[1]['enable_thinking'] is False and seen[1]['stream_options'] == {'include_usage': True}
    row = records(ledger)[0]
    assert (row['prompt_tokens'], row['completion_tokens'], row['total_tokens']) == (12, 4, 16)
    assert row['provider_id'] == 'provider-1' and row['provider_request_id'] == 'header-id'
    assert row['model'] == 'qwen3.8-flash' and row['status'] == 'complete'


@pytest.mark.asyncio
@pytest.mark.parametrize(('body', 'message', 'tokens'), [
    ('data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\ndata: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":10,"total_tokens":15}}\n\ndata: [DONE]\n\n', '输出超出预算', 15),
    ('data: {"choices":[{"delta":{"content":"partial"}}]}\n\n', '连接意外中断', None),
    ('data: invalid-json\n\n', '不兼容', None),
])
async def test_failure_records_usage_or_unknown(monkeypatch, ledger, body, message, tokens):
    transport(monkeypatch, lambda request: httpx.Response(200, text=body))
    cfg = settings(model_test_include_usage=True, model_test_ledger_path=str(ledger))
    with pytest.raises(ModelError, match=message):
        _ = [x async for x in stream_chat(cfg, [])]
    row = records(ledger)[0]
    assert row['status'] == 'failed' and row['total_tokens'] == tokens
    assert 'test-key' not in ledger.read_text()


@pytest.mark.asyncio
async def test_success_without_usage_is_unknown(monkeypatch, ledger):
    transport(monkeypatch, lambda request: httpx.Response(200, text='data: [DONE]\n\n'))
    token = operation_id.set('operation-123')
    try:
        _ = [x async for x in stream_chat(settings(model_test_include_usage=True, model_test_ledger_path=str(ledger)), [])]
    finally:
        operation_id.reset(token)
    assert records(ledger)[0]['total_tokens'] is None
    assert records(ledger)[0]['operation_id'] == 'operation-123'


@pytest.mark.asyncio
async def test_http_failure_consumes_budget(monkeypatch, ledger):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(401)
    transport(monkeypatch, handler)
    cfg = settings(model_test_include_usage=True, model_test_ledger_path=str(ledger))
    for _ in range(8):
        with pytest.raises(ModelError, match='认证失败'):
            _ = [x async for x in stream_chat(cfg, [])]
    with pytest.raises(ModelError, match='上限'):
        _ = [x async for x in stream_chat(cfg, [])]
    assert len(calls) == len(records(ledger)) == 8


def test_cross_process_limit(ledger):
    with ProcessPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, [str(ledger)] * 20))
    assert sum(results) == len(records(ledger)) == 8


@pytest.mark.asyncio
async def test_usage_requires_ledger_before_network(monkeypatch):
    transport(monkeypatch, lambda request: pytest.fail('不可发出请求'))
    with pytest.raises(ModelError, match='共享账本'):
        _ = [x async for x in stream_chat(settings(model_test_include_usage=True), [])]
