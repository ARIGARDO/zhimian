"""面试状态及答案事务；不调用模型，也不提供 HTTP 接口。"""
import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview import Interview, InterviewAnswer, InterviewOperation, InterviewQuestion, InterviewReport, InterviewPreset, InterviewQuestionBank


@dataclass(frozen=True)
class InterviewRules:
    # 已确认值集中管理；规则版本写入面试快照。
    min_valid_main: int
    min_count_questions: int
    inactivity_seconds: int
    jd_max_chars: int
    valid_answer: Callable[[str], bool]
    validity_policy_id: str = "substantive-v2"
    rules_version: str = "m302-fix-v1"
    max_answer_chars: int = 12000


def valid_submission(text: str) -> bool:
    # 至少包含 Unicode 字母或数字，标点、空白、符号不能独立构成作答。
    return (any(unicodedata.category(c)[0] in {'L', 'N'} for c in text)
            and all(unicodedata.category(c) != 'Cs' and (unicodedata.category(c) != 'Cc' or c in '\n\r\t') for c in text))


# R01～R04 的已确认值在此集中维护；变更需新增规则版本。
CONFIRMED_RULES = (2, 3, 30 * 60, 5000, 'substantive-v2', 'm302-fix-v1')


def recommended_rules() -> InterviewRules:
    valid_main, count, inactivity, jd, policy_id, version = CONFIRMED_RULES
    return InterviewRules(valid_main, count, inactivity, jd, valid_submission, policy_id, version)


MAX_FOLLOWUPS = 2  # 已确认的每道主问题追问上限。
MODEL_RECOVERY_GRACE_SECONDS = 60  # 同一次用户活动最多一次模型恢复宽限。
TERMINAL = {'completed', 'terminated', 'interrupted'}


def public_preset(snapshot: dict) -> dict:
    return {key: snapshot[key] for key in ('id', 'kind', 'name', 'version') if key in snapshot}


class InterviewConflict(ValueError):
    pass


class InterviewNotFound(InterviewConflict):
    pass


class InterviewValidation(InterviewConflict):
    pass


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


async def database_now(db: AsyncSession) -> datetime:
    if db.bind.dialect.name == 'postgresql':
        return utc(await db.scalar(select(func.clock_timestamp())))
    return datetime.now(timezone.utc)


class InterviewService:
    def __init__(self, db: AsyncSession, rules: InterviewRules, clock: Callable[[AsyncSession], Awaitable[datetime]] = database_now):
        self.db, self.rules, self.clock = db, rules, clock
        if (rules.min_valid_main, rules.min_count_questions, rules.inactivity_seconds, rules.jd_max_chars,
            rules.validity_policy_id, rules.rules_version) != CONFIRMED_RULES or rules.valid_answer is not valid_submission or rules.max_answer_chars <= 0:
            raise ValueError('面试规则与已确认版本不一致')

    def _rules_snapshot(self) -> dict:
        return {'min_valid_main': self.rules.min_valid_main, 'min_count_questions': self.rules.min_count_questions,
                'inactivity_seconds': self.rules.inactivity_seconds, 'jd_max_chars': self.rules.jd_max_chars,
                'validity_policy_id': self.rules.validity_policy_id, 'rules_version': self.rules.rules_version,
                'max_answer_chars': self.rules.max_answer_chars}

    async def _lock(self, interview_id: str) -> Interview:
        item = await self.db.scalar(select(Interview).where(Interview.id == interview_id).with_for_update().execution_options(populate_existing=True))
        if item is None:
            raise InterviewNotFound('面试不存在')
        if item.config_snapshot.get('_rules') != self._rules_snapshot():
            raise InterviewConflict('面试规则与创建时快照不一致')
        return item

    async def _previous(self, item: Interview, key: str, kind: str, payload: dict) -> tuple[str, dict | None]:
        if not key or len(key) > 100:
            raise InterviewConflict('幂等键无效')
        digest = hashlib.sha256(json.dumps({'kind': kind, 'payload': payload}, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        op = await self.db.scalar(select(InterviewOperation).where(InterviewOperation.interview_id == item.id, InterviewOperation.request_id == key))
        if op:
            if op.request_hash != digest or op.kind != kind:
                raise InterviewConflict('幂等键已用于不同请求')
            return digest, op.result
        return digest, None

    def _record(self, item: Interview, key: str, kind: str, digest: str, result: dict) -> dict:
        self.db.add(InterviewOperation(interview_id=item.id, kind=kind, request_id=key, request_hash=digest, status='complete', result=result))
        return result

    @staticmethod
    def _running(item: Interview) -> None:
        if item.status != 'in_progress':
            raise InterviewConflict('面试不可继续作答')

    async def _count_valid_main(self, item: Interview) -> int:
        return await self.db.scalar(select(func.count(distinct(InterviewQuestion.id)))
            .join(InterviewAnswer, InterviewAnswer.question_id == InterviewQuestion.id)
            .where(InterviewAnswer.interview_id == item.id, InterviewAnswer.kind == 'answer', InterviewQuestion.depth == 0))

    def model_finished(self, item: Interview, finished_at: datetime) -> None:
        # 只在模型跨越用户活动期限时创建一次宽限，不改用户活动时间。
        if (item.status == 'in_progress' and item.limit_type == 'count' and item.last_activity_at
                and finished_at >= utc(item.last_activity_at) + timedelta(seconds=self.rules.inactivity_seconds)
                and item.model_grace_until is None):
            item.model_grace_until = finished_at + timedelta(seconds=MODEL_RECOVERY_GRACE_SECONDS)

    async def _expire(self, item: Interview, now: datetime) -> str | None:
        if item.limit_type == 'time' and item.deadline_at and now >= utc(item.deadline_at):
            item.valid_main_count = await self._count_valid_main(item)
            enough = item.valid_main_count >= self.rules.min_valid_main
            item.status = 'completed' if enough else 'terminated'
            item.ended_at = now
            item.end_reason = 'time_limit' if enough else 'time_limit_insufficient_evidence'
        elif item.limit_type == 'count' and item.last_activity_at and now >= utc(item.last_activity_at) + timedelta(seconds=self.rules.inactivity_seconds):
            deadline = utc(item.last_activity_at) + timedelta(seconds=self.rules.inactivity_seconds)
            active = await self.db.scalar(select(InterviewOperation.id).where(
                InterviewOperation.interview_id == item.id, InterviewOperation.status == 'running',
                InterviewOperation.lease_until.is_not(None), InterviewOperation.lease_until > now).limit(1))
            if active:
                return None
            # 崩溃后的宽限从租约截止起算，而非从下一次访问起算。
            if item.model_grace_until is None:
                expired_lease = await self.db.scalar(select(func.max(InterviewOperation.lease_until)).where(
                    InterviewOperation.interview_id == item.id, InterviewOperation.status == 'running',
                    InterviewOperation.kind.like('ai_%'), InterviewOperation.lease_until >= deadline,
                    InterviewOperation.lease_until <= now))
                if expired_lease:
                    item.model_grace_until = utc(expired_lease) + timedelta(seconds=MODEL_RECOVERY_GRACE_SECONDS)
            if item.model_grace_until and now < utc(item.model_grace_until):
                return None
            item.status, item.ended_at, item.end_reason = 'interrupted', now, 'inactivity_timeout'
        else:
            return None
        item.version += 1
        return item.status

    def _validate_configuration(self, mode: str, limit_type: str, main_limit: int | None, duration_seconds: int | None, preset_snapshot: dict, config_snapshot: dict, jd: str | None) -> dict:
        if (mode not in {'practice', 'formal'} or not isinstance(preset_snapshot, dict)
                or not isinstance(config_snapshot, dict) or (jd is not None and not isinstance(jd, str))
                or len(jd or '') > self.rules.jd_max_chars):
            raise InterviewValidation('面试模式或 JD 无效')
        if jd and preset_snapshot.get('kind') != 'role':
            raise InterviewValidation('仅岗位模式支持 JD')
        if limit_type == 'count':
            if main_limit is None or main_limit < self.rules.min_count_questions or duration_seconds is not None:
                raise InterviewValidation('主问题数量无效')
        elif limit_type == 'time':
            if duration_seconds is None or duration_seconds <= 0 or main_limit is not None:
                raise InterviewValidation('面试时长无效')
        else:
            raise InterviewValidation('限制类型无效')
        if '_rules' in config_snapshot:
            raise InterviewValidation('配置使用了保留字段')
        snapshot = {**config_snapshot, '_rules': self._rules_snapshot()}
        return snapshot

    async def create(self, *, mode: str, limit_type: str, main_limit: int | None, duration_seconds: int | None, preset_snapshot: dict, config_snapshot: dict, jd: str | None = None) -> str:
        snapshot = self._validate_configuration(mode, limit_type, main_limit, duration_seconds, preset_snapshot, config_snapshot, jd)
        async with self.db.begin():
            item = Interview(status='pending', mode=mode, limit_type=limit_type, main_limit=main_limit, duration_seconds=duration_seconds, preset_snapshot=preset_snapshot, config_snapshot=snapshot, jd=jd, main_count=0, valid_main_count=0, version=0)
            self.db.add(item); await self.db.flush()
            return item.id

    async def create_from_preset(self, *, key: str, preset_id: str, mode: str, limit_type: str, main_limit: int | None, duration_seconds: int | None, jd: str | None) -> dict:
        payload = {'preset_id': preset_id, 'mode': mode, 'limit_type': limit_type, 'main_limit': main_limit, 'duration_seconds': duration_seconds, 'jd': jd}
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if not key or len(key) > 100: raise InterviewValidation('幂等键无效')
        async with self.db.begin():
            if self.db.bind.dialect.name == 'postgresql':
                lock_id = int.from_bytes(hashlib.sha256(('interview-create:' + key).encode()).digest()[:8], 'big', signed=True)
                await self.db.execute(text('SELECT pg_advisory_xact_lock(:lock_id)'), {'lock_id': lock_id})
            previous = await self.db.scalar(select(Interview).where(Interview.create_key == key))
            if previous:
                if previous.create_hash != digest: raise InterviewConflict('幂等键已用于不同请求')
                return {'id': previous.id, 'status': 'pending'}
            preset = await self.db.get(InterviewPreset, preset_id)
            if not preset or not preset.active: raise InterviewNotFound('预设不存在或不可用')
            questions = (await self.db.scalars(select(InterviewQuestionBank).where(InterviewQuestionBank.preset_id == preset.id, InterviewQuestionBank.active.is_(True)).order_by(InterviewQuestionBank.id))).all()
            self._validate_configuration(mode, limit_type, main_limit, duration_seconds, {'kind': preset.kind}, {}, jd)
            if not questions: raise InterviewConflict('题库暂无可用题目')
            if limit_type == 'count' and main_limit is not None and main_limit > len(questions): raise InterviewConflict('题库可用主问题不足')
            preset_snapshot = {'id': preset.id, 'kind': preset.kind, 'name': preset.name, 'version': preset.version}
            config_snapshot = {'question_plan': [{'id': q.id, 'content': q.content, 'topic': q.topic, 'version': q.version} for q in questions]}
            snapshot = self._validate_configuration(mode, limit_type, main_limit, duration_seconds, preset_snapshot, config_snapshot, jd)
            item = Interview(status='pending', create_key=key, create_hash=digest, preset_id=preset.id, mode=mode, limit_type=limit_type, main_limit=main_limit, duration_seconds=duration_seconds, preset_snapshot=preset_snapshot, config_snapshot=snapshot, jd=jd, main_count=0, valid_main_count=0, version=0)
            self.db.add(item); await self.db.flush()
            return {'id': item.id, 'status': item.status}

    async def next_question(self, interview_id: str, key: str) -> dict:
        async with self.db.begin():
            item = await self._lock(interview_id)
            digest, prior = await self._previous(item, key, 'next_question', {})
            now = await self.clock(self.db)
            expired = await self._expire(item, now) if item.status == 'in_progress' else None
            if prior is not None: return prior
            if expired: return self._record(item, key, 'next_question', digest, {'status': item.status, 'outcome': expired, 'end_reason': item.end_reason})
            self._running(item)
            if item.main_count:
                last = await self.db.scalar(select(InterviewQuestion).where(InterviewQuestion.interview_id == item.id, InterviewQuestion.main_number == item.main_count, InterviewQuestion.depth == 0))
                if not last or not last.closed_at: raise InterviewConflict('当前主问题尚未结束')
            if item.main_limit is not None and item.main_count >= item.main_limit: raise InterviewConflict('已达到主问题数量限制')
            plan = item.config_snapshot.get('question_plan', [])
            if item.main_count >= len(plan): raise InterviewConflict('题库已无可用主问题')
            source = plan[item.main_count]
            item.main_count += 1
            q = InterviewQuestion(interview_id=item.id, main_number=item.main_count, depth=0, position=0, content=source['content'], source_snapshot=source)
            self.db.add(q); await self.db.flush(); item.version += 1
            return self._record(item, key, 'next_question', digest, {'id': q.id, 'main_number': q.main_number, 'depth': 0, 'content': q.content})

    async def list_history(self, status: str | None, limit: int, offset: int) -> list[dict]:
        async with self.db.begin():
            # 锁顺序固定，先惰性结算当前规则版本的过期场次，再按终态过滤。
            active = (await self.db.scalars(select(Interview).where(Interview.status == 'in_progress').order_by(Interview.id).with_for_update())).all()
            now = await self.clock(self.db)
            for item in active:
                if item.config_snapshot.get('_rules') == self._rules_snapshot():
                    await self._expire(item, now)
            await self.db.flush()
            stmt = select(Interview).order_by(Interview.created_at.desc(), Interview.id.desc()).limit(limit).offset(offset)
            if status:
                stmt = stmt.where(Interview.status.in_(['terminated', 'interrupted']) if status == 'incomplete' else Interview.status == status)
            items = (await self.db.scalars(stmt)).all()
            return [{'id': i.id, 'status': i.status, 'mode': i.mode, 'preset': public_preset(i.preset_snapshot), 'created_at': i.created_at, 'ended_at': i.ended_at} for i in items]

    async def detail(self, interview_id: str) -> dict:
        async with self.db.begin():
            item = await self._lock(interview_id)
            if item.status == 'in_progress': await self._expire(item, await self.clock(self.db))
            questions = (await self.db.scalars(select(InterviewQuestion).where(InterviewQuestion.interview_id == item.id).order_by(InterviewQuestion.main_number, InterviewQuestion.position))).all()
            answers = (await self.db.scalars(select(InterviewAnswer).where(InterviewAnswer.interview_id == item.id))).all()
            by_question = {a.question_id: {'id': a.id, 'kind': a.kind, 'content': a.content, 'submitted_at': a.submitted_at} for a in answers}
            return {'id': item.id, 'status': item.status, 'mode': item.mode, 'preset': public_preset(item.preset_snapshot), 'limit_type': item.limit_type, 'main_limit': item.main_limit, 'duration_seconds': item.duration_seconds, 'started_at': item.started_at, 'deadline_at': item.deadline_at, 'ended_at': item.ended_at, 'end_reason': item.end_reason, 'main_count': item.main_count, 'valid_main_count': item.valid_main_count, 'version': item.version, 'questions': [{'id': q.id, 'main_number': q.main_number, 'depth': q.depth, 'position': q.position, 'content': q.content, 'closed_at': q.closed_at, 'answer': by_question.get(q.id)} for q in questions]}

    async def start(self, interview_id: str, key: str) -> dict:
        async with self.db.begin():
            item = await self._lock(interview_id)
            digest, prior = await self._previous(item, key, 'start', {})
            if item.status == 'in_progress':
                expired = await self._expire(item, await self.clock(self.db))
                if prior is not None: return prior
                if expired: return self._record(item, key, 'start', digest, {'status': item.status, 'outcome': expired, 'end_reason': item.end_reason})
                return self._record(item, key, 'start', digest, {'status': item.status, 'started_at': utc(item.started_at).isoformat()})
            if prior is not None: return prior
            if item.status != 'pending': raise InterviewConflict('终态不可开始')
            now = await self.clock(self.db)
            item.status, item.started_at, item.last_activity_at = 'in_progress', now, now
            item.model_grace_until = None
            if item.limit_type == 'time': item.deadline_at = now + timedelta(seconds=item.duration_seconds)
            item.version += 1
            return self._record(item, key, 'start', digest, {'status': item.status, 'started_at': now.isoformat()})

    async def add_question(self, interview_id: str, key: str, content: str, parent_id: str | None = None) -> dict:
        payload = {'content': content, 'parent_id': parent_id}
        async with self.db.begin():
            item = await self._lock(interview_id)
            digest, prior = await self._previous(item, key, 'question', payload)
            now = await self.clock(self.db)
            expired = await self._expire(item, now) if item.status == 'in_progress' else None
            if prior is not None: return prior
            if expired: return self._record(item, key, 'question', digest, {'status': item.status, 'outcome': expired, 'end_reason': item.end_reason})
            self._running(item)
            if not content.strip(): raise InterviewConflict('题目不能为空')
            if parent_id:
                parent = await self.db.get(InterviewQuestion, parent_id)
                if not parent or parent.interview_id != item.id or parent.main_number != item.main_count:
                    raise InterviewConflict('追问父题不属于当前场次或主问题')
                main = await self.db.scalar(select(InterviewQuestion).where(InterviewQuestion.interview_id == item.id, InterviewQuestion.main_number == parent.main_number, InterviewQuestion.depth == 0))
                if main.closed_at or parent.depth >= MAX_FOLLOWUPS:
                    raise InterviewConflict('追问已关闭或超过深度限制')
                if not await self.db.scalar(select(InterviewAnswer.id).where(InterviewAnswer.question_id == parent.id, InterviewAnswer.kind == 'answer')):
                    raise InterviewConflict('父问题尚无有效回答')
                depth, number = parent.depth + 1, parent.main_number
                questions = (await self.db.scalars(select(InterviewQuestion).where(InterviewQuestion.interview_id == item.id, InterviewQuestion.main_number == number))).all()
                if sum(q.depth > 0 for q in questions) >= MAX_FOLLOWUPS:
                    raise InterviewConflict('已达到追问数量限制')
                latest = max(questions, key=lambda q: q.position)
                if not await self.db.scalar(select(InterviewAnswer.id).where(InterviewAnswer.question_id == latest.id)):
                    raise InterviewConflict('当前问题尚未回答')
                position = max(q.position for q in questions) + 1
            else:
                if item.main_count:
                    last = await self.db.scalar(select(InterviewQuestion).where(InterviewQuestion.interview_id == item.id, InterviewQuestion.main_number == item.main_count, InterviewQuestion.depth == 0))
                    if not last or not last.closed_at: raise InterviewConflict('当前主问题尚未结束')
                if item.main_limit is not None and item.main_count >= item.main_limit: raise InterviewConflict('已达到主问题数量限制')
                item.main_count += 1
                depth, number, position = 0, item.main_count, 0
            question = InterviewQuestion(interview_id=item.id, parent_id=parent_id, main_number=number, depth=depth, position=position, content=content.strip(), source_snapshot={})
            self.db.add(question); await self.db.flush()
            item.version += 1
            return self._record(item, key, 'question', digest, {'id': question.id, 'main_number': number, 'depth': depth})

    async def answer(self, interview_id: str, key: str, question_id: str, content: str = '', skip: bool = False) -> dict:
        if not isinstance(content, str) or not isinstance(skip, bool):
            raise InterviewValidation('回答格式无效')
        payload = {'question_id': question_id, 'content': content, 'skip': skip}
        async with self.db.begin():
            item = await self._lock(interview_id)
            digest, prior = await self._previous(item, key, 'answer', payload)
            now = await self.clock(self.db)
            expired = await self._expire(item, now) if item.status == 'in_progress' else None
            if prior is not None: return prior
            if expired: return self._record(item, key, 'answer', digest, {'status': item.status, 'outcome': expired, 'end_reason': item.end_reason})
            self._running(item)
            question = await self.db.get(InterviewQuestion, question_id)
            if not question or question.interview_id != item.id: raise InterviewNotFound('问题不存在')
            if question.main_number != item.main_count: raise InterviewConflict('问题不是当前主问题')
            main = await self.db.scalar(select(InterviewQuestion).where(InterviewQuestion.interview_id == item.id, InterviewQuestion.main_number == question.main_number, InterviewQuestion.depth == 0))
            latest = await self.db.scalar(select(func.max(InterviewQuestion.position)).where(InterviewQuestion.interview_id == item.id, InterviewQuestion.main_number == question.main_number))
            if main.closed_at or question.position != latest: raise InterviewConflict('问题不是当前可回答问题')
            if skip and (item.mode != 'practice' or content): raise InterviewConflict('仅练习模式可跳题')
            if not skip and (not isinstance(content, str) or len(content) > self.rules.max_answer_chars or not valid_submission(content) or not self.rules.valid_answer(content)): raise InterviewValidation('回答无效')
            if await self.db.scalar(select(InterviewAnswer.id).where(InterviewAnswer.question_id == question.id)): raise InterviewConflict('问题已提交')
            answer = InterviewAnswer(interview_id=item.id, question_id=question.id, kind='skip' if skip else 'answer', content='' if skip else content.strip(), request_id=key, submitted_at=now)
            self.db.add(answer); await self.db.flush()
            item.valid_main_count = await self._count_valid_main(item)
            item.last_activity_at = now; item.model_grace_until = None; item.version += 1
            return self._record(item, key, 'answer', digest, {'id': answer.id, 'valid_main_count': item.valid_main_count})

    async def close_main(self, interview_id: str, key: str, question_id: str | None = None) -> dict:
        async with self.db.begin():
            item = await self._lock(interview_id)
            digest, prior = await self._previous(item, key, 'close_main', {'question_id': question_id} if question_id is not None else {})
            now = await self.clock(self.db)
            expired = await self._expire(item, now) if item.status == 'in_progress' else None
            if prior is not None: return prior
            if expired: return self._record(item, key, 'close_main', digest, {'status': item.status, 'outcome': expired, 'end_reason': item.end_reason})
            self._running(item)
            qs = (await self.db.scalars(select(InterviewQuestion).where(InterviewQuestion.interview_id == item.id, InterviewQuestion.main_number == item.main_count).order_by(InterviewQuestion.depth))).all()
            if not qs or qs[0].closed_at: raise InterviewConflict('主问题不存在或已结束')
            if question_id is not None and qs[0].id != question_id: raise InterviewConflict('主问题已变更')
            count = await self.db.scalar(select(func.count(InterviewAnswer.id)).where(InterviewAnswer.question_id.in_([q.id for q in qs])))
            if count != len(qs): raise InterviewConflict('存在未处理问题')
            qs[0].closed_at = now; item.version += 1
            outcome = 'closed'
            if item.limit_type == 'count' and item.main_count == item.main_limit:
                item.valid_main_count = await self._count_valid_main(item)
                if item.valid_main_count >= self.rules.min_valid_main:
                    item.status, item.ended_at, item.end_reason = 'completed', now, 'count_limit'
                    outcome = 'completed'
                else:
                    item.status, item.ended_at, item.end_reason = 'terminated', now, 'count_limit_insufficient_evidence'
                    outcome = 'terminated'
            return self._record(item, key, 'close_main', digest, {'status': item.status, 'outcome': outcome})

    async def check_expiry(self, interview_id: str) -> dict:
        async with self.db.begin():
            item = await self._lock(interview_id)
            if item.status != 'in_progress': return {'status': item.status, 'outcome': 'unchanged'}
            outcome = await self._expire(item, await self.clock(self.db))
            return {'status': item.status, 'outcome': outcome or 'not_expired'}

    async def check_inactivity(self, interview_id: str) -> bool:
        # 惰性检查不刷新活动时间，已有终态不改变。
        async with self.db.begin():
            item = await self._lock(interview_id)
            if item.status != 'in_progress' or item.limit_type != 'count': return False
            return await self._expire(item, await self.clock(self.db)) == 'interrupted'

    async def end(self, interview_id: str, key: str, target: str, reason: str) -> dict:
        if target not in {'terminated', 'interrupted'} or not reason.strip() or len(reason) > 100: raise InterviewConflict('终止参数无效')
        payload = {'target': target, 'reason': reason}
        async with self.db.begin():
            item = await self._lock(interview_id)
            digest, prior = await self._previous(item, key, 'end', payload)
            expired = await self._expire(item, await self.clock(self.db)) if item.status == 'in_progress' else None
            if prior is not None: return prior
            if expired: return self._record(item, key, 'end', digest, {'status': item.status, 'outcome': expired, 'end_reason': item.end_reason})
            if item.status in TERMINAL:
                if item.status != target: raise InterviewConflict('终态不可变更')
                return self._record(item, key, 'end', digest, {'status': item.status})
            self._running(item); now = await self.clock(self.db)
            item.status, item.ended_at, item.end_reason = target, now, reason.strip(); item.version += 1
            return self._record(item, key, 'end', digest, {'status': item.status})

    async def add_report_placeholder(self, interview_id: str, report_type: str) -> str:
        # 到期转换需提交后再报告资格错误，避免异常回滚终态。
        error = None
        report_id = None
        async with self.db.begin():
            item = await self._lock(interview_id)
            if item.status == 'in_progress':
                await self._expire(item, await self.clock(self.db))
            if report_type == 'full' and item.status != 'completed':
                error = '未完成面试不能生成完整报告'
            elif report_type == 'partial' and (item.status not in {'terminated', 'interrupted'} or item.valid_main_count < 1):
                error = '部分复盘需要未完成场次和有效回答'
            elif report_type not in {'full', 'partial'}:
                error = '报告类型无效'
            else:
                report = InterviewReport(interview_id=item.id, type=report_type, status='not_requested')
                self.db.add(report)
                await self.db.flush()
                report_id = report.id
        if error: raise InterviewConflict(error)
        return report_id
