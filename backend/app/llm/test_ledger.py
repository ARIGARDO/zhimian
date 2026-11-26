"""隔离验收共享调用账本；不记录请求或回答内容。"""
import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

operation_id = ContextVar('model_test_operation_id', default=None)
operation_scope = ContextVar('model_test_operation_scope', default=None)
LIMIT = 8


def _check_file(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError('验收账本权限不安全')


@contextmanager
def _locked(path):
    # 独立锁文件在账本原子替换后保持 inode 不变。
    if not os.path.isabs(path):
        raise ValueError('验收账本必须使用绝对路径')
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path + '.lock', flags, 0o600)
    with os.fdopen(fd, 'r+') as lock:
        _check_file(lock.fileno())
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _read(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'r', encoding='utf-8') as file:
        _check_file(file.fileno())
        content = file.read()
    return json.loads(content), hashlib.sha256(content.encode('utf-8')).hexdigest()


def _write(path, data):
    # 同目录临时文件 fsync 后替换；锁独立于被替换的文件。
    directory = os.path.dirname(path)
    fd, temporary = tempfile.mkstemp(prefix='.ledger-', dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, separators=(',', ':'))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _valid_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z0-9._:-]{1,100}', value))


def _validate(data, expected_limit, expected_batch=None):
    if (not isinstance(data, dict) or data.get('version') not in (1, 2)
            or type(data.get('limit')) is not int or data['limit'] != expected_limit
            or not isinstance(data.get('requests'), list) or len(data['requests']) > expected_limit
            or any(not isinstance(record, dict) for record in data['requests'])):
        raise ValueError('验收账本格式或上限不匹配')
    if data['version'] == 1 and (expected_limit != LIMIT or expected_batch is not None):
        raise ValueError('旧版账本上限或批次不匹配')
    if data['version'] == 2:
        slots = data.get('allowed')
        if not _valid_id(expected_batch) or data.get('batch_id') != expected_batch:
            raise ValueError('验收账本批次不匹配')
        if not isinstance(slots, list) or len(slots) != expected_limit:
            raise ValueError('验收操作列表无效')
        names = [slot.get('slot') for slot in slots if isinstance(slot, dict)]
        if len(names) != len(slots) or len(set(names)) != len(slots) or not all(_valid_id(name) for name in names):
            raise ValueError('验收操作列表无效')
        if expected_batch == 'm306b-3c' and (expected_limit != 3 or set(names) != {'ai2', 'ai1', 'formal_followup'}):
            raise ValueError('验收操作列表无效')
        if expected_batch == 'real-mvp-3' and (expected_limit != 3 or set(names) != {'rag', 'followup', 'report'}):
            raise ValueError('验收操作列表无效')
        bound = []
        for slot in slots:
            interview, kind, target = slot.get('interview_id'), slot.get('kind'), slot.get('target_id')
            permitted = ('report', 'followup', 'chat') if expected_batch == 'real-mvp-3' else ('report', 'followup')
            if kind not in permitted or (interview is None) != (target is None):
                raise ValueError('验收操作绑定无效')
            if expected_batch == 'real-mvp-3':
                if (interview is None or target is None or
                        (slot['slot'], kind) not in {('rag', 'chat'), ('followup', 'followup'), ('report', 'report')} or
                        (slot['slot'] == 'rag' and target != 'rag') or
                        (slot['slot'] == 'report' and target != 'full')):
                    raise ValueError('验收操作绑定无效')
            if expected_batch == 'm306b-3c' and slot['slot'] == 'ai2' and (kind != 'report' or target != 'partial'):
                raise ValueError('验收操作绑定无效')
            if expected_batch == 'm306b-3c' and slot['slot'] == 'ai1' and (kind != 'report' or target != 'full'):
                raise ValueError('验收操作绑定无效')
            if expected_batch == 'm306b-3c' and slot['slot'] == 'formal_followup' and kind != 'followup':
                raise ValueError('验收操作绑定无效')
            if interview is not None:
                if not _valid_id(interview) or not _valid_id(target): raise ValueError('验收操作绑定无效')
                bound.append(interview)
        if len(set(bound)) != len(bound): raise ValueError('验收操作绑定重复')
        for record in data['requests']:
            if record.get('slot') not in names: raise ValueError('验收账本记录无效')
        if len({record['slot'] for record in data['requests']}) != len(data['requests']):
            raise ValueError('验收操作记录重复')


def initialize_three_call_ledger(path, expected_sha256, ai2_id, ai1_id):
    """仅将摘要匹配且无请求的 0/8 新账本转换为有审计记录的 0/3。"""
    if not _valid_id(ai2_id) or not _valid_id(ai1_id) or ai1_id == ai2_id:
        raise ValueError('验收场次无效')
    with _locked(path):
        data, digest = _read(path)
        if data != {'version': 1, 'limit': 8, 'requests': []} or digest != expected_sha256:
            raise ValueError('新账本不是经确认的空账本')
        new = {'version': 2, 'batch_id': 'm306b-3c', 'limit': 3, 'requests': [],
               'initialization': {'previous_sha256': digest, 'previous_limit': 8, 'previous_requests': 0,
                                  'reason': 'approved_empty_ledger_limit_change',
                                  'changed_at': datetime.now(timezone.utc).isoformat()},
               'allowed': [
                   {'slot': 'ai2', 'interview_id': ai2_id, 'kind': 'report', 'target_id': 'partial'},
                   {'slot': 'ai1', 'interview_id': ai1_id, 'kind': 'report', 'target_id': 'full'},
                   {'slot': 'formal_followup', 'interview_id': None, 'kind': 'followup', 'target_id': None},
               ]}
        _validate(new, 3, 'm306b-3c')
        _write(path, new)


def bind_formal_followup(path, interview_id, answer_id):
    """调用前将新建正式场次和目标回答一次性绑定到未使用的追问槽位。"""
    if not _valid_id(interview_id) or not _valid_id(answer_id): raise ValueError('验收场次或回答无效')
    with _locked(path):
        data, _ = _read(path)
        _validate(data, 3, 'm306b-3c')
        if data['version'] != 2: raise ValueError('验收账本版本不支持绑定')
        slot = next((x for x in data['allowed'] if x['slot'] == 'formal_followup'), None)
        if not slot or any(x.get('slot') == 'formal_followup' for x in data['requests']):
            raise ValueError('追问槽位不可绑定')
        if slot['interview_id'] is not None:
            if (slot['interview_id'], slot['target_id']) == (interview_id, answer_id): return
            raise ValueError('追问槽位已经绑定')
        slot.update(interview_id=interview_id, target_id=answer_id, bound_at=datetime.now(timezone.utc).isoformat())
        _validate(data, 3, 'm306b-3c')
        _write(path, data)


def update_ledger(path: str, request_id: str | None = None, details: dict | None = None, *, expected_limit=8, expected_batch=None) -> str:
    """在发出请求前认领额度，结束时只补充状态和供应商用量。"""
    with _locked(path):
        data, _ = _read(path)
        _validate(data, expected_limit, expected_batch)
        records = data['requests']
        if request_id is None:
            if len(records) >= expected_limit: raise ValueError('验收模型请求已达上限')
            slot_name = None
            if data['version'] == 2:
                scope = operation_scope.get()
                if not _valid_id(operation_id.get()) or not isinstance(scope, tuple) or len(scope) != 3:
                    raise ValueError('缺少验收操作身份或范围')
                match = [slot for slot in data['allowed'] if (slot['interview_id'], slot['kind'], slot['target_id']) == scope]
                if len(match) != 1: raise ValueError('操作不在验收允许列表中')
                slot_name = match[0]['slot']
                if any(record.get('slot') == slot_name for record in records): raise ValueError('验收操作已认领')
            request_id = uuid4().hex
            row = {'id': request_id, 'operation_id': operation_id.get(), 'status': 'started',
                   'started_at': datetime.now(timezone.utc).isoformat(), 'provider_id': None,
                   'provider_request_id': None, 'model': None, 'prompt_tokens': None,
                   'completion_tokens': None, 'total_tokens': None}
            if slot_name: row['slot'] = slot_name
            records.append(row)
        else:
            record = next((r for r in records if r.get('id') == request_id), None)
            if record is None or record.get('status') != 'started': raise ValueError('验收账本记录不存在或已结束')
            record.update(details or {})
            record['finished_at'] = datetime.now(timezone.utc).isoformat()
        _write(path, data)
        return request_id
