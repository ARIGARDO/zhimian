import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.learning import Topic
from app.services.interview import InterviewService, recommended_rules
from app.services.interview_ai import InterviewAIService


@pytest_asyncio.fixture
async def setup_tasks(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tasks.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add(Topic(id='python', category='python', category_label='Python', title='Python 专题', summary='简介', content_md='# 专题', sort_order=1))
        await db.commit()
        service = InterviewService(db, recommended_rules())
        interview = await service.create(mode='practice', limit_type='count', main_limit=3, duration_seconds=None, preset_snapshot={}, config_snapshot={})
        await service.start(interview, 'start')
        question = await service.add_question(interview, 'question', '问题')
        answer = await service.answer(interview, 'answer', question['id'], '有效回答')
        await service.end(interview, 'end', 'terminated', 'user_terminated')

    async def db_override():
        async with factory() as db:
            yield db

    async def report(_self, interview_id):
        assert interview_id == interview
        return {'status': 'ready', 'type': 'partial', 'result': {'items': [{'answer_id': answer['id'], 'review': '建议继续学习'}]}}

    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(InterviewAIService, 'get_report', report)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        yield client, interview, answer['id']
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_confirmed_task_is_idempotent_and_persists(setup_tasks):
    client, interview, answer = setup_tasks
    body = {'interview_id': interview, 'answer_id': answer, 'topic_id': 'python'}
    assert (await client.get('/api/v1/tasks')).json() == []
    first = await client.post('/api/v1/tasks', json=body)
    assert first.status_code == 201
    assert (await client.post('/api/v1/tasks', json=body)).json()['id'] == first.json()['id']
    task_id = first.json()['id']
    assert (await client.patch('/api/v1/tasks/' + task_id, json={'status': 'completed'})).json()['status'] == 'completed'
    tasks = (await client.get('/api/v1/tasks')).json()
    assert len(tasks) == 1 and tasks[0]['topic_title'] == 'Python 专题' and tasks[0]['status'] == 'completed'
    assert (await client.post('/api/v1/tasks', json={**body, 'answer_id': 'other'})).status_code == 409
    assert (await client.patch('/api/v1/tasks/' + task_id, json={'status': 'unknown'})).status_code == 422
