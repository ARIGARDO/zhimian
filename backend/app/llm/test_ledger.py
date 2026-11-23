"""隔离验收使用的本机共享调用账本；不记录请求或回答内容。"""
import fcntl
import json
import os
import stat
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

operation_id = ContextVar('model_test_operation_id', default=None)
LIMIT = 8


def update_ledger(path: str, request_id: str | None = None, details: dict | None = None) -> str:
    """锁住已预置账本，先认领额度，再记录结果；异常时禁止继续请求。"""
    if not os.path.isabs(path):
        raise ValueError('验收账本必须使用绝对路径')
    flags = os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, 'r+', encoding='utf-8') as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('验收账本权限不安全')
        fcntl.flock(file, fcntl.LOCK_EX)
        data = json.load(file)
        if not isinstance(data, dict) or data.get('version') != 1 or data.get('limit') != LIMIT or not isinstance(data.get('requests'), list):
            raise ValueError('验收账本格式无效')
        records = data['requests']
        if any(not isinstance(record, dict) for record in records):
            raise ValueError('验收账本记录无效')
        if request_id is None:
            if len(records) >= LIMIT:
                raise ValueError('验收模型请求已达 8 次上限')
            request_id = uuid4().hex
            records.append({'id': request_id, 'operation_id': operation_id.get(), 'status': 'started',
                            'started_at': datetime.now(timezone.utc).isoformat(),
                            'provider_id': None, 'provider_request_id': None, 'model': None, 'prompt_tokens': None,
                            'completion_tokens': None, 'total_tokens': None})
        else:
            record = next((r for r in records if r.get('id') == request_id), None)
            if record is None or record.get('status') != 'started':
                raise ValueError('验收账本记录不存在或已结束')
            record.update(details or {})
            record['finished_at'] = datetime.now(timezone.utc).isoformat()
        file.seek(0)
        json.dump(data, file, ensure_ascii=False, separators=(',', ':'))
        file.truncate()
        file.flush()
        os.fsync(file.fileno())
        return request_id
