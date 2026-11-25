import json
import pytest
from fastapi.testclient import TestClient
from app.demo.model import app
from app.demo.seed import seed_demo


def test_demo_report_and_chat_are_clearly_marked():
    with TestClient(app) as client:
        response = client.post('/v1/chat/completions', json={'messages': [{'role': 'system', 'content': '返回结构：{"items":[{"answer_id":"原回答ID"}]}'}, {'role': 'user', 'content': json.dumps([{'answer_id': 'a'}])}]})
        assert response.status_code == 200
        event = json.loads(response.text.splitlines()[0][6:])
        result = json.loads(event['choices'][0]['delta']['content'])
        assert result['items'][0]['answer_id'] == 'a'
        assert '模拟' in result['summary'] and 'overall_score' not in result
        response = client.post('/v1/chat/completions', json={'messages': [{'role': 'user', 'content': '你好'}]})
        assert '模拟回复' in response.text


@pytest.mark.asyncio
async def test_demo_seed_refuses_other_databases(monkeypatch):
    monkeypatch.setenv('ZHIMIAN_DEMO_ONLY', 'true')
    monkeypatch.setenv('DATABASE_URL', 'postgresql+asyncpg://other:password@localhost/zhimian')
    with pytest.raises(RuntimeError):
        await seed_demo()
