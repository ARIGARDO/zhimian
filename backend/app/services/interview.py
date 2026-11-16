"""面试状态及答案事务；不调用模型，也不提供 HTTP 接口。"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview import Interview, InterviewAnswer, InterviewOperation, InterviewQuestion, InterviewReport


@dataclass(frozen=True)
class InterviewRules:
    # 产品尚未确认的推荐值，由调用方显式选择或替换。
    min_valid_main: int
    min_count_questions: int
    inactivity_seconds: int
    jd_max_chars: int
    valid_answer: Callable[[str], bool]


def recommended_rules() -> InterviewRules:
    return InterviewRules(2, 3, 30 * 60, 5000, lambda text: bool(text.strip()))


MAX_FOLLOWUPS = 2  # 已确认的每道主问题追问上限。
TERMINAL = {'completed', 'terminated', 'interrupted'}


class InterviewConflict(ValueError):
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
        if min(rules.min_valid_main, rules.min_count_questions, rules.inactivity_seconds, rules.jd_max_chars) <= 0:
            raise ValueError('规则值必须为正数')

    async def _lock(self, interview_id: str) -> Interview:
        item = await self.db.scalar(select(Interview).where(Interview.id == interview_id).with_for_update())
        if item is None:
            raise InterviewConflict('面试不存在')
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

    async def _expire(self, item: Interview, now: datetime) -> str | None:
        if item.limit_type != 'time' or not item.deadline_at or now < utc(item.deadline_at):
            return None
        # 不足门槛的终态尚未确定；保持原状态，但任何逾期写入都被拒绝。
        if item.valid_main_count < self.rules.min_valid_main:
            return 'expired_insufficient_evidence'
        item.status, item.ended_at, item.end_reason = 'completed', now, 'time_limit'
        item.version += 1
        return 'completed'

    async def create(self, *, mode: str, limit_type: str, main_limit: int | None, duration_seconds: int | None, preset_snapshot: dict, config_snapshot: dict, jd: str | None = None) -> str:
        if mode not in {'practice', 'formal'} or len(jd or '') > self.rules.jd_max_chars:
            raise InterviewConflict('面试模式或 JD 无效')
        if limit_type == 'count':
            if main_limit is None or main_limit < self.rules.min_count_questions or duration_seconds is not None:
                raise InterviewConflict('主问题数量无效')
        elif limit_type == 'time':
            if duration_seconds is None or duration_seconds <= 0 or main_limit is not None:
                raise InterviewConflict('面试时长无效')
        else:
            raise InterviewConflict('限制类型无效')
        async with self.db.begin():
            item = Interview(status='pending', mode=mode, limit_type=limit_type, main_limit=main_limit, duration_seconds=duration_seconds, preset_snapshot=preset_snapshot, config_snapshot=config_snapshot, jd=jd, main_count=0, valid_main_count=0, version=0)
            self.db.add(item); await self.db.flush()
            return item.id

    async def start(self, interview_id: str, key: str) -> dict:
        async with self.db.begin():
            item = await self._lock(interview_id)
            digest, prior = await self._previous(item, key, 'start', {})
            if prior is not None: return prior
            if item.status == 'in_progress':
                expired = await self._expire(item, await self.clock(self.db))
                if expired: return self._record(item, key, 'start', digest, {'status': item.status, 'outcome': expired})
                return self._record(item, key, 'start', digest, {'status': item.status, 'started_at': utc(item.started_at).isoformat()})
            if item.status != 'pending': raise InterviewConflict('终态不可开始')
            now = await self.clock(self.db)
            item.status, item.started_at, item.last_activity_at = 'in_progress', now, now
            if item.limit_type == 'time': item.deadline_at = now + timedelta(seconds=item.duration_seconds)
            item.version += 1
            return self._record(item, key, 'start', digest, {'status': item.status, 'started_at': now.isoformat()})

    async def add_question(self, interview_id: str, key: str, content: str, parent_id: str | None = None) -> dict:
        payload = {'content': content, 'parent_id': parent_id}
        async with self.db.begin():
            item = await self._lock(interview_id)
            digest, prior = await self._previous(item, key, 'question', payload)
            if prior is not None: return prior
            self._running(item); now = await self.clock(self.db)
            expired = await self._expire(item, now)
            if expired: return self._record(item, key, 'question', digest, {'status': item.status, 'outcome': expired})
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
                existing = await self.db.scalar(select(InterviewQuestion.id).where(InterviewQuestion.interview_id == item.id, InterviewQuestion.main_number == number, InterviewQuestion.depth == depth))
                if existing: raise InterviewConflict('该追问已存在')
            else:
                if item.main_count:
                    last = await self.db.scalar(select(InterviewQuestion).where(InterviewQuestion.interview_id == item.id, InterviewQuestion.main_number == item.main_count, InterviewQuestion.depth == 0))
                    if not last or not last.closed_at: raise InterviewConflict('当前主问题尚未结束')
                if item.main_limit is not None and item.main_count >= item.main_limit: raise InterviewConflict('已达到主问题数量限制')
                item.main_count += 1
                depth, number = 0, item.main_count
            question = InterviewQuestion(interview_id=item.id, parent_id=parent_id, main_number=number, depth=depth, content=content.strip(), source_snapshot={})
            self.db.add(question); await self.db.flush()
            item.last_activity_at = now; item.version += 1
            return self._record(item, key, 'question', digest, {'id': question.id, 'main_number': number, 'depth': depth})

    async def answer(self, interview_id: str, key: str, question_id: str, content: str = '', skip: bool = False) -> dict:
        payload = {'question_id': question_id, 'content': content, 'skip': skip}
        async with self.db.begin():
            item = await self._lock(interview_id)
            digest, prior = await self._previous(item, key, 'answer', payload)
            if prior is not None: return prior
            self._running(item); now = await self.clock(self.db)
            expired = await self._expire(item, now)
            if expired: return self._record(item, key, 'answer', digest, {'status': item.status, 'outcome': expired})
            question = await self.db.get(InterviewQuestion, question_id)
            if not question or question.interview_id != item.id or question.main_number != item.main_count: raise InterviewConflict('问题不属于当前面试')
            main = await self.db.scalar(select(InterviewQuestion).where(InterviewQuestion.interview_id == item.id, InterviewQuestion.main_number == question.main_number, InterviewQuestion.depth == 0))
            latest = await self.db.scalar(select(func.max(InterviewQuestion.depth)).where(InterviewQuestion.interview_id == item.id, InterviewQuestion.main_number == question.main_number))
            if main.closed_at or question.depth != latest: raise InterviewConflict('问题不是当前可回答问题')
            if skip and (item.mode != 'practice' or content): raise InterviewConflict('仅练习模式可跳题')
            if not skip and not self.rules.valid_answer(content): raise InterviewConflict('回答无效')
            if await self.db.scalar(select(InterviewAnswer.id).where(InterviewAnswer.question_id == question.id)): raise InterviewConflict('问题已提交')
            answer = InterviewAnswer(interview_id=item.id, question_id=question.id, kind='skip' if skip else 'answer', content='' if skip else content.strip(), request_id=key, submitted_at=now)
            self.db.add(answer); await self.db.flush()
            item.valid_main_count = await self.db.scalar(select(func.count(distinct(InterviewQuestion.main_number))).join(InterviewAnswer, InterviewAnswer.question_id == InterviewQuestion.id).where(InterviewAnswer.interview_id == item.id, InterviewAnswer.kind == 'answer'))
            item.last_activity_at = now; item.version += 1
            return self._record(item, key, 'answer', digest, {'id': answer.id, 'valid_main_count': item.valid_main_count})

    async def close_main(self, interview_id: str, key: str) -> dict:
        async with self.db.begin():
            item = await self._lock(interview_id)
            digest, prior = await self._previous(item, key, 'close_main', {})
            if prior is not None: return prior
            self._running(item); now = await self.clock(self.db)
            expired = await self._expire(item, now)
            if expired: return self._record(item, key, 'close_main', digest, {'status': item.status, 'outcome': expired})
            qs = (await self.db.scalars(select(InterviewQuestion).where(InterviewQuestion.interview_id == item.id, InterviewQuestion.main_number == item.main_count).order_by(InterviewQuestion.depth))).all()
            if not qs or qs[0].closed_at: raise InterviewConflict('主问题不存在或已结束')
            count = await self.db.scalar(select(func.count(InterviewAnswer.id)).where(InterviewAnswer.question_id.in_([q.id for q in qs])))
            if count != len(qs): raise InterviewConflict('存在未处理问题')
            qs[0].closed_at = now; item.last_activity_at = now; item.version += 1
            outcome = 'closed'
            if item.limit_type == 'count' and item.main_count == item.main_limit:
                if item.valid_main_count >= self.rules.min_valid_main:
                    item.status, item.ended_at, item.end_reason = 'completed', now, 'count_limit'
                    outcome = 'completed'
                else: outcome = 'insufficient_evidence'
            return self._record(item, key, 'close_main', digest, {'status': item.status, 'outcome': outcome})

    async def check_expiry(self, interview_id: str) -> dict:
        async with self.db.begin():
            item = await self._lock(interview_id)
            if item.status != 'in_progress': return {'status': item.status, 'outcome': 'unchanged'}
            outcome = await self._expire(item, await self.clock(self.db))
            return {'status': item.status, 'outcome': outcome or 'not_expired'}

    async def check_inactivity(self, interview_id: str) -> bool:
        # 推荐无活动期限仅提示，不改变状态；产品确认后再决定终止策略。
        async with self.db.begin():
            item = await self._lock(interview_id)
            return bool(item.status == 'in_progress' and item.limit_type == 'count' and item.last_activity_at and (await self.clock(self.db)) >= utc(item.last_activity_at) + timedelta(seconds=self.rules.inactivity_seconds))

    async def end(self, interview_id: str, key: str, target: str, reason: str) -> dict:
        if target not in {'terminated', 'interrupted'} or not reason.strip() or len(reason) > 100: raise InterviewConflict('终止参数无效')
        payload = {'target': target, 'reason': reason}
        async with self.db.begin():
            item = await self._lock(interview_id)
            digest, prior = await self._previous(item, key, 'end', payload)
            if prior is not None: return prior
            if item.status in TERMINAL:
                if item.status != target: raise InterviewConflict('终态不可变更')
                return self._record(item, key, 'end', digest, {'status': item.status})
            self._running(item); now = await self.clock(self.db)
            expired = await self._expire(item, now)
            if expired == 'completed': return self._record(item, key, 'end', digest, {'status': item.status, 'outcome': expired})
            item.status, item.ended_at, item.end_reason = target, now, reason.strip(); item.version += 1
            return self._record(item, key, 'end', digest, {'status': item.status})

    async def add_report_placeholder(self, interview_id: str, report_type: str) -> str:
        # 仅创建数据占位，不执行模型评估或报告生成。
        async with self.db.begin():
            item = await self._lock(interview_id)
            if report_type == 'full' and item.status != 'completed': raise InterviewConflict('未完成面试不能生成完整报告')
            if report_type == 'partial' and (item.status not in {'terminated', 'interrupted'}): raise InterviewConflict('部分复盘不得评分')
            if report_type not in {'full', 'partial'}: raise InterviewConflict('报告类型无效')
            # 部分报告仅存纯文字字段，不定义任何逐题数值评分字段。
            report = InterviewReport(interview_id=item.id, type=report_type, status='not_requested')
            self.db.add(report); await self.db.flush()
            return report.id
