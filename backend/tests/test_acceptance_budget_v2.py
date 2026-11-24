"""新批次三次硬上限与授权操作：全部使用模拟 HTTP 和临时账本。"""
import hashlib
import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.llm.client import ModelError, stream_chat
from app.llm.test_ledger import bind_formal_followup, initialize_three_call_ledger, operation_id, operation_scope, update_ledger


@pytest.fixture
def ledger(tmp_path):
    path=tmp_path/'ledger.json'
    path.write_text('{"version":1,"limit":8,"requests":[]}',encoding='utf-8')
    path.chmod(0o600)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    initialize_three_call_ledger(str(path),digest,'interview-ai2','interview-ai1')
    return path


def read(path):
    return json.loads(path.read_text())


def reserve_task(args):
    path,scope=args
    token=operation_scope.set(scope); id_token=operation_id.set(f'process-{os.getpid()}')
    try:
        update_ledger(path,expected_limit=3,expected_batch='m306b-3c')
        return True
    except ValueError:
        return False
    finally:
        operation_id.reset(id_token)
        operation_scope.reset(token)


def reserve_then_crash(path):
    operation_scope.set(('interview-ai2','report','partial'))
    operation_id.set('crashed-operation')
    update_ledger(path,expected_limit=3,expected_batch='m306b-3c')
    os._exit(17)


def test_atomic_conversion_and_old_ledger_unchanged(tmp_path):
    old=tmp_path/'old.json';new=tmp_path/'new.json'
    old.write_text(json.dumps({'version':1,'limit':8,'requests':[{'id':str(i)} for i in range(8)]}));old.chmod(0o600)
    new.write_text('{"version":1,"limit":8,"requests":[]}');new.chmod(0o600)
    old_before=old.read_bytes();initial=hashlib.sha256(new.read_bytes()).hexdigest()
    initialize_three_call_ledger(str(new),initial,'ai2-id','ai1-id')
    data=read(new)
    assert data['version']==2 and data['limit']==3 and data['requests']==[]
    assert data['initialization']['previous_sha256']==initial and old.read_bytes()==old_before
    with pytest.raises(ValueError): initialize_three_call_ledger(str(new),initial,'ai2-id','ai1-id')
    with pytest.raises(ValueError): initialize_three_call_ledger(str(old),hashlib.sha256(old_before).hexdigest(),'ai2-id','ai1-id')
    assert old.read_bytes()==old_before


def test_atomic_failure_does_not_replace_original(tmp_path, monkeypatch):
    import app.llm.test_ledger as module
    path=tmp_path/'ledger.json';path.write_text('{"version":1,"limit":8,"requests":[]}');path.chmod(0o600)
    original=path.read_bytes();digest=hashlib.sha256(original).hexdigest()
    def fail_replace(*args): raise OSError('模拟替换失败')
    monkeypatch.setattr(module.os,'replace',fail_replace)
    with pytest.raises(OSError): initialize_three_call_ledger(str(path),digest,'ai2-id','ai1-id')
    assert path.read_bytes()==original


def test_authorized_slots_and_binding(ledger):
    path=str(ledger)
    for scope in [('interview-ai2','report','full'), ('interview-ai1','report','partial'),
                  ('other','report','full'), ('interview-ai2','followup','answer')]:
        assert not reserve_task((path,scope))
    assert not reserve_task((path,('formal','followup','answer')))
    bind_formal_followup(path,'formal','answer')
    bind_formal_followup(path,'formal','answer')
    with pytest.raises(ValueError): bind_formal_followup(path,'different','answer')
    scopes=[('interview-ai2','report','partial'),('interview-ai1','report','full'),('formal','followup','answer')]
    for scope in scopes:
        assert reserve_task((path,scope))
        assert not reserve_task((path,scope))
    assert len(read(ledger)['requests'])==3
    assert not reserve_task((path,('formal','followup','answer')))


def test_cross_process_competition_and_restart(ledger):
    bind_formal_followup(str(ledger),'formal','answer')
    scopes=[('interview-ai2','report','partial'),('interview-ai1','report','full'),('formal','followup','answer')]
    with ProcessPoolExecutor(max_workers=4) as pool:
        result=list(pool.map(reserve_task,[(str(ledger),scopes[n%3]) for n in range(30)]))
    assert sum(result)==3 and len(read(ledger)['requests'])==3
    with ProcessPoolExecutor(max_workers=1) as pool:
        assert list(pool.map(reserve_task,[(str(ledger),scopes[0])]))==[False]


def test_crash_after_reservation_keeps_slot(ledger):
    process=multiprocessing.Process(target=reserve_then_crash,args=(str(ledger),))
    process.start();process.join(10)
    assert process.exitcode==17 and read(ledger)['requests'][0]['status']=='started'
    assert not reserve_task((str(ledger),('interview-ai2','report','partial')))
    assert len(read(ledger)['requests'])==1


def test_other_batch_can_use_a_different_limit(tmp_path):
    path=tmp_path/'other.json'
    path.write_text(json.dumps({'version':2,'batch_id':'other-batch','limit':2,'requests':[],
        'allowed':[{'slot':'one','interview_id':'first','kind':'report','target_id':'full'},
                   {'slot':'two','interview_id':'second','kind':'report','target_id':'partial'}]}))
    path.chmod(0o600)
    for index,scope in enumerate([('first','report','full'),('second','report','partial')]):
        scope_token=operation_scope.set(scope);id_token=operation_id.set(f'op-{index}')
        try: update_ledger(str(path),expected_limit=2,expected_batch='other-batch')
        finally: operation_id.reset(id_token);operation_scope.reset(scope_token)
    assert len(read(path)['requests'])==2
    with pytest.raises(ValueError): update_ledger(str(path),expected_limit=2,expected_batch='other-batch')


@pytest.mark.asyncio
async def test_failed_requests_and_retries_cannot_bypass_budget(ledger, monkeypatch):
    bind_formal_followup(str(ledger),'formal','answer')
    seen=[]
    def handler(request):
        seen.append(request)
        return httpx.Response(401)
    original=httpx.AsyncClient
    monkeypatch.setattr('app.llm.client.httpx.AsyncClient',lambda **kw: original(transport=httpx.MockTransport(handler)))
    settings=Settings(_env_file=None,model_name='qwen3.8-flash',model_base_url='https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1',model_api_key='test-only',model_acceptance_mode=True,model_acceptance_isolated_account=True,model_enable_thinking=False,model_test_include_usage=True,model_test_ledger_path=str(ledger),model_acceptance_request_limit=3,model_acceptance_batch_id='m306b-3c',model_ai_max_attempts=1,model_ai_max_output_tokens=1024)
    scopes=[('interview-ai2','report','partial'),('interview-ai1','report','full'),('formal','followup','answer')]
    for i,scope in enumerate(scopes):
        scope_token=operation_scope.set(scope); id_token=operation_id.set(f'operation-{i}')
        try:
            with pytest.raises(ModelError,match='认证失败'):
                _=[x async for x in stream_chat(settings,[],max_tokens=1024)]
        finally:
            operation_id.reset(id_token);operation_scope.reset(scope_token)
        if i == 0:
            # 更换操作 ID 重试同一场次，也必须在第二次网络发送之前失败。
            scope_token=operation_scope.set(scope); id_token=operation_id.set('changed-operation-id')
            try:
                with pytest.raises(ModelError,match='账本'):
                    _=[x async for x in stream_chat(settings,[],max_tokens=1024)]
            finally:
                operation_id.reset(id_token);operation_scope.reset(scope_token)
            assert len(seen)==1
    scope_token=operation_scope.set(scopes[0]);id_token=operation_id.set('different-operation')
    try:
        with pytest.raises(ModelError,match='账本'):
            _=[x async for x in stream_chat(settings,[],max_tokens=1024)]
    finally:
        operation_id.reset(id_token);operation_scope.reset(scope_token)
    assert len(seen)==3 and len(read(ledger)['requests'])==3
    assert all(r['status']=='failed' for r in read(ledger)['requests'])


@pytest.mark.asyncio
async def test_timeout_keeps_reserved_slot(ledger, monkeypatch):
    calls=[]
    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout('模拟超时',request=request)
    original=httpx.AsyncClient
    monkeypatch.setattr('app.llm.client.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler)))
    cfg=Settings(_env_file=None,model_name='qwen3.8-flash',model_base_url='https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1',model_api_key='test-only',model_acceptance_mode=True,model_acceptance_isolated_account=True,model_enable_thinking=False,model_test_include_usage=True,model_test_ledger_path=str(ledger),model_acceptance_request_limit=3,model_acceptance_batch_id='m306b-3c',model_ai_max_attempts=1,model_ai_max_output_tokens=1024)
    scope_token=operation_scope.set(('interview-ai2','report','partial'));id_token=operation_id.set('timeout-op')
    try:
        with pytest.raises(ModelError,match='超时'):
            _=[x async for x in stream_chat(cfg,[],max_tokens=1024)]
        with pytest.raises(ModelError,match='账本'):
            _=[x async for x in stream_chat(cfg,[],max_tokens=1024)]
    finally:
        operation_id.reset(id_token);operation_scope.reset(scope_token)
    assert calls==[1] and len(read(ledger)['requests'])==1 and read(ledger)['requests'][0]['status']=='failed'


@pytest.mark.asyncio
async def test_mismatched_limit_and_missing_scope_do_not_send(ledger, monkeypatch):
    def handler(request): pytest.fail('不应发送请求')
    original=httpx.AsyncClient
    monkeypatch.setattr('app.llm.client.httpx.AsyncClient',lambda **kw: original(transport=httpx.MockTransport(handler)))
    settings=Settings(_env_file=None,model_name='qwen3.8-flash',model_base_url='https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1',model_api_key='test-only',model_acceptance_mode=True,model_acceptance_isolated_account=True,model_enable_thinking=False,model_test_include_usage=True,model_test_ledger_path=str(ledger),model_ai_max_attempts=1,model_ai_max_output_tokens=1024)
    with pytest.raises(ModelError,match='账本'):
        _=[x async for x in stream_chat(settings,[],max_tokens=1024)]
    settings.model_acceptance_request_limit=3
    settings.model_acceptance_batch_id='wrong-batch'
    scope_token=operation_scope.set(('interview-ai2','report','partial'));id_token=operation_id.set('operation')
    try:
        with pytest.raises(ModelError,match='账本'):
            _=[x async for x in stream_chat(settings,[],max_tokens=1024)]
    finally:
        operation_id.reset(id_token);operation_scope.reset(scope_token)
    settings.model_acceptance_batch_id='m306b-3c'
    with pytest.raises(ModelError,match='账本'):
        _=[x async for x in stream_chat(settings,[],max_tokens=1024)]
    assert read(ledger)['requests']==[]


@pytest.mark.asyncio
async def test_batch_config_needs_acceptance_mode_and_matching_batch(tmp_path, monkeypatch):
    path=tmp_path/'legacy.json';path.write_text('{"version":1,"limit":8,"requests":[]}');path.chmod(0o600)
    def handler(request): pytest.fail('不应发送请求')
    original=httpx.AsyncClient
    monkeypatch.setattr('app.llm.client.httpx.AsyncClient',lambda **kw: original(transport=httpx.MockTransport(handler)))
    settings=Settings(_env_file=None,model_name='qwen3.8-flash',model_base_url='https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1',model_api_key='test-only',model_acceptance_isolated_account=True,model_enable_thinking=False,model_test_include_usage=True,model_test_ledger_path=str(path),model_acceptance_batch_id='m306b-3c',model_ai_max_attempts=1,model_ai_max_output_tokens=1024)
    with pytest.raises(ModelError,match='必须启用验收模式'):
        _=[x async for x in stream_chat(settings,[],max_tokens=1024)]
    settings.model_acceptance_mode=True
    with pytest.raises(ModelError,match='账本'):
        _=[x async for x in stream_chat(settings,[],max_tokens=1024)]
    assert read(path)['requests']==[]


@pytest.mark.asyncio
async def test_validator_rejection_consumes_slot_across_service_restart(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.db.base import Base
    from app.services.interview import InterviewConflict, InterviewService, recommended_rules
    from app.services.interview_ai import InterviewAIService
    engine=create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'state.db'}")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async def call(name,*args,**kwargs):
        async with factory() as db: return await getattr(InterviewService(db,recommended_rules()),name)(*args,**kwargs)
    cid=await call('create',mode='formal',limit_type='count',main_limit=3,duration_seconds=None,preset_snapshot={},config_snapshot={})
    await call('start',cid,'start');q=await call('add_question',cid,'q','测试题');a=await call('answer',cid,'a',q['id'],'有效回答');await call('end',cid,'end','terminated','测试')
    path=tmp_path/'ledger.json';path.write_text('{"version":1,"limit":8,"requests":[]}');path.chmod(0o600)
    initialize_three_call_ledger(str(path),hashlib.sha256(path.read_bytes()).hexdigest(),cid,'other-interview')
    settings=Settings(_env_file=None,model_name='qwen3.8-flash',model_base_url='https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1',model_api_key='test-only',model_acceptance_mode=True,model_acceptance_isolated_account=True,model_enable_thinking=False,model_test_include_usage=True,model_test_ledger_path=str(path),model_acceptance_request_limit=3,model_acceptance_batch_id='m306b-3c',model_ai_max_attempts=1,model_ai_max_output_tokens=1024)
    monkeypatch.setattr('app.services.interview_ai.get_settings',lambda:settings)
    calls=[]
    def handler(request):
        calls.append(1)
        body=json.dumps({'summary':'候选人表现良好','items':[{'answer_id':a['id'],'review':'已作答'}]},ensure_ascii=False)
        event=json.dumps({'choices':[{'delta':{'content':body}}]},ensure_ascii=False)
        return httpx.Response(200,text='data: '+event+'\n\ndata: [DONE]\n\n')
    original=httpx.AsyncClient
    monkeypatch.setattr('app.llm.client.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler)))
    result=await InterviewAIService(factory,stream_chat).run(cid,'first-key','report','partial')
    assert result['status']=='failed' and result['retryable'] is False
    assert len(read(path)['requests'])==1 and read(path)['requests'][0]['slot']=='ai2'
    with pytest.raises(InterviewConflict):
        await InterviewAIService(factory,stream_chat).run(cid,'new-key','report','partial')
    assert calls==[1] and len(read(path)['requests'])==1
    await engine.dispose()


@pytest.mark.asyncio
async def test_three_call_followup_rejects_practice_mode(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.db.base import Base
    from app.services.interview import InterviewConflict, InterviewService, recommended_rules
    from app.services.interview_ai import InterviewAIService
    engine=create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'practice.db'}")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async def call(name,*args,**kwargs):
        async with factory() as db: return await getattr(InterviewService(db,recommended_rules()),name)(*args,**kwargs)
    cid=await call('create',mode='practice',limit_type='count',main_limit=3,duration_seconds=None,preset_snapshot={},config_snapshot={})
    await call('start',cid,'start');q=await call('add_question',cid,'q','测试题');a=await call('answer',cid,'a',q['id'],'有效回答')
    settings=Settings(_env_file=None,model_acceptance_mode=True,model_acceptance_request_limit=3,model_acceptance_batch_id='m306b-3c')
    monkeypatch.setattr('app.services.interview_ai.get_settings',lambda:settings)
    with pytest.raises(InterviewConflict,match='仅允许正式面试'):
        await InterviewAIService(factory).claim(cid,'key','followup',a['id'])
    await engine.dispose()
