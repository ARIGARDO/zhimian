"""真实交付隔离批次：只使用模拟供应商和临时账本。"""
import json
import httpx
import pytest

from app.core.config import Settings
from app.llm.client import ModelError, stream_chat
from app.llm.test_ledger import operation_id, operation_scope


@pytest.mark.asyncio
async def test_three_scoped_requests_and_failure_consume_budget(tmp_path, monkeypatch):
    path = tmp_path / 'ledger.json'
    path.write_text(json.dumps({'version': 2, 'batch_id': 'real-mvp-3', 'limit': 3, 'requests': [], 'allowed': [
        {'slot': 'rag', 'interview_id': 'conversation', 'kind': 'chat', 'target_id': 'rag'},
        {'slot': 'followup', 'interview_id': 'interview', 'kind': 'followup', 'target_id': 'answer'},
        {'slot': 'report', 'interview_id': 'report-interview', 'kind': 'report', 'target_id': 'full'},
    ]}))
    path.chmod(0o600)
    sent = []
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(401)
    original = httpx.AsyncClient
    monkeypatch.setattr('app.llm.client.httpx.AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler)))
    settings = Settings(_env_file=None, model_name='qwen3.8-flash',
        model_base_url='https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1', model_api_key='test-only',
        model_acceptance_mode=True, model_acceptance_isolated_account=True, model_enable_thinking=False,
        model_test_include_usage=True, model_test_ledger_path=str(path), model_acceptance_request_limit=3,
        model_acceptance_batch_id='real-mvp-3', model_ai_max_attempts=1, model_ai_max_output_tokens=1024)
    scopes = [('conversation', 'chat', 'rag'), ('interview', 'followup', 'answer'), ('report-interview', 'report', 'full')]
    async def attempt(scope):
        st = operation_scope.set(scope); ot = operation_id.set('test-operation')
        try:
            return [part async for part in stream_chat(settings, [], max_tokens=1024)]
        finally:
            operation_id.reset(ot); operation_scope.reset(st)
    with pytest.raises(ModelError, match='账本'):
        await attempt(('conversation', 'chat', 'other'))
    for scope in scopes:
        with pytest.raises(ModelError, match='认证失败'):
            await attempt(scope)
        with pytest.raises(ModelError, match='账本'):
            await attempt(scope)
    assert len(sent) == 3
    assert all(p['max_tokens'] == 1024 and p['enable_thinking'] is False for p in sent)
    assert len(json.loads(path.read_text())['requests']) == 3


def test_thinking_option_can_be_unset_or_disabled():
    assert Settings(_env_file=None, model_enable_thinking='').model_enable_thinking is None
    assert Settings(_env_file=None, model_enable_thinking='false').model_enable_thinking is False


def test_unbound_real_mvp_slot_is_invalid():
    from app.llm.test_ledger import _validate
    data = {'version': 2, 'batch_id': 'real-mvp-3', 'limit': 3, 'requests': [], 'allowed': [
        {'slot': 'rag', 'interview_id': 'conversation', 'kind': 'chat', 'target_id': 'rag'},
        {'slot': 'followup', 'interview_id': None, 'kind': 'followup', 'target_id': None},
        {'slot': 'report', 'interview_id': 'report-interview', 'kind': 'report', 'target_id': 'full'},
    ]}
    with pytest.raises(ValueError):
        _validate(data, 3, 'real-mvp-3')
