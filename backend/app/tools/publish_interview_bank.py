"""发布人工签核题库。默认只校验；审核入库和启用必须分别显式执行。"""
import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select, text
from app.db.session import get_engine, get_session_factory
from app.models.interview import InterviewPreset, InterviewQuestionBank
from app.services.question_version import question_digest, question_payload
from app.tools.import_interview_draft import load_manifest


def verify_approval(manifest, approval):
    """校验签核信息及每道题的完整摘要；这是人工声明，不是身份签名。"""
    presets, questions, reports = load_manifest(manifest)
    data = json.loads(Path(approval).read_text(encoding='utf-8'))
    if set(data) != {'reviewer', 'approved_at', 'questions'}:
        raise ValueError('签核文件必须包含 reviewer、approved_at 和 questions')
    reviewer = data['reviewer']
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer.strip()) > 100:
        raise ValueError('请填写实际审核人')
    try:
        approved_at = datetime.fromisoformat(data['approved_at'].replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('审核时间格式无效') from exc
    if approved_at.tzinfo is None:
        raise ValueError('审核时间必须包含时区')
    approvals = data['questions']
    if not isinstance(approvals, dict) or not approvals:
        raise ValueError('签核题目列表为空')
    expected = {code: digest for code, _, digest in reports}
    for code, digest in approvals.items():
        if code not in expected or digest != expected[code]:
            raise ValueError(f'题目 {code} 的签核摘要不匹配')
    return presets, [q for q in questions if q['code'] in approvals], reviewer.strip(), approved_at


def payload(q):
    return SimpleNamespace(id=q['id'], preset_id=q['preset_id'], content_code=q['code'], version=q['version'], content=q['content'], topic=q['topic'], difficulty=q['difficulty'], sort_order=q['sort_order'], review_material=q['material'])


async def publish(presets, questions, reviewer, approved_at, enable=False):
    async with get_session_factory()() as db:
        async with db.begin():
            if db.bind.dialect.name != 'postgresql':
                raise ValueError('正式题库工具仅支持 PostgreSQL')
            await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('zhimian-question-publication'))"))
            for preset in presets:
                if not any(q['preset_id'] == preset['id'] for q in questions):
                    continue
                existing = await db.get(InterviewPreset, preset['id'], with_for_update=True)
                if not existing:
                    if enable: raise ValueError('请先完成签核入库')
                    db.add(InterviewPreset(**preset, active=False, config={}))
                    await db.flush()
                elif (existing.kind, existing.name, existing.version) != (preset['kind'], preset['name'], preset['version']):
                    raise ValueError('预设版本冲突，不能覆盖')
            for q in questions:
                row = await db.scalar(select(InterviewQuestionBank).where(InterviewQuestionBank.preset_id == q['preset_id'], InterviewQuestionBank.content_code == q['code'], InterviewQuestionBank.version == q['version']).with_for_update())
                if row and question_digest(question_payload(row)) != question_digest(question_payload(payload(q))):
                    raise ValueError(f"题目 {q['code']} 已存在不同内容，必须新建版本")
                if enable:
                    if not row or row.review_status != 'approved' or not row.reviewed_by or not row.reviewed_at:
                        raise ValueError(f"题目 {q['code']} 尚未签核入库")
                    row.active = True
                elif not row:
                    db.add(InterviewQuestionBank(**vars(payload(q)), active=False, review_status='approved', reviewed_by=reviewer, reviewed_at=approved_at))
                elif row.review_status == 'draft':
                    row.review_status, row.reviewed_by, row.reviewed_at = 'approved', reviewer, approved_at
            await db.flush()
            if enable:
                for preset_id in {q['preset_id'] for q in questions}:
                    active_rows = (await db.scalars(select(InterviewQuestionBank).where(
                        InterviewQuestionBank.preset_id == preset_id,
                        InterviewQuestionBank.active.is_(True)).with_for_update())).all()
                    if any(not row.content_code or row.review_status != 'approved' or not row.reviewed_by or not row.reviewed_at for row in active_rows):
                        raise ValueError('题库包含已启用的未审核题目，不能混用')
                    preset = await db.get(InterviewPreset, preset_id, with_for_update=True)
                    preset.active = True
    await get_engine().dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--approval', help='负责人逐题填写的签核文件；不要提交含私人信息的文件')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--apply', action='store_true', help='将已签核版本入库，保持禁用')
    actions.add_argument('--enable', action='store_true', help='启用已入库且签核摘要匹配的题目')
    args = parser.parse_args()
    if not args.approval:
        if args.apply or args.enable: parser.error('写入必须提供人工签核文件')
        _, _, reports = load_manifest(args.manifest)
        for code, size, digest in reports: print(f'{code}\t{size}\t{digest}')
        return
    presets, questions, reviewer, approved_at = verify_approval(args.manifest, args.approval)
    print(f'签核校验通过：{len(questions)} 道题；未执行写入' if not (args.apply or args.enable) else f'已确认 {len(questions)} 道题，开始执行。')
    if args.apply or args.enable:
        asyncio.run(publish(presets, questions, reviewer, approved_at, enable=args.enable))
        print('完成；审核与启用状态已分别处理。')


if __name__ == '__main__':
    main()
