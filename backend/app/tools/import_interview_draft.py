"""仅向显式标记的本机隔离 PostgreSQL 导入禁用题库草稿。"""
import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.models.interview import InterviewPreset, InterviewQuestionBank
from app.services.question_version import question_digest, question_payload, validate_review_capacity

GUARD = 'zhimian-m306b-isolated-only'


def validate_url(url):
    parsed = urlsplit(url)
    name = parsed.path.lstrip('/')
    # SQLAlchemy 的查询参数可以覆盖 host/database；禁止所有查询参数及片段。
    if parsed.scheme != 'postgresql+asyncpg' or parsed.query or parsed.fragment or parsed.hostname not in {'127.0.0.1', '::1'} or not name.startswith('zhimian_m306b_') or not name.replace('_', '').isalnum():
        raise ValueError('仅允许本机显式命名的隔离 PostgreSQL 测试库')


def load_manifest(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    presets=data['presets']; questions=data['questions']
    if data['manifest_version']!='v1.0-draft' or len(presets)!=2 or len(questions)!=20:
        raise ValueError('清单版本或数量不符合要求')
    expected={'bank-python-v1':{f'P{i:02}' for i in range(1,11)},'bank-ai-v1':{f'A{i:02}' for i in range(1,11)}}
    if {p['id'] for p in presets} != set(expected): raise ValueError('预设不符合要求')
    reports=[]
    for preset in presets:
        if preset['kind']!='bank' or preset['version']!=1: raise ValueError('预设版本无效')
        group=[q for q in questions if q['preset_id']==preset['id']]
        if {q['code'] for q in group}!=expected[preset['id']] or len(group)!=10: raise ValueError('题目编号重复或缺失')
        if sorted(q['difficulty'] for q in group)!=sorted(['basic']*4+['intermediate']*5+['challenge']): raise ValueError('难度分布无效')
        for q in group:
            if q['id']!=f"qb-{q['code'].lower()}-v1" or q['version']!=1 or q['sort_order']!=int(q['code'][1:]): raise ValueError('题目版本或顺序无效')
            row=SimpleNamespace(id=q['id'],preset_id=q['preset_id'],content_code=q['code'],version=q['version'],content=q['content'],topic=q['topic'],difficulty=q['difficulty'],sort_order=q['sort_order'],review_material=q['material'])
            payload=question_payload(row); validate_review_capacity(payload)
            size=len(json.dumps(q['material'],ensure_ascii=False,sort_keys=True,separators=(',',':')))
            reports.append((q['code'],size,question_digest(payload)))
    return presets,questions,reports


async def import_draft(url, path):
    validate_url(url)
    presets,questions,reports=load_manifest(path)
    engine=create_async_engine(url)
    try:
        async with engine.begin() as conn:
            guard=await conn.scalar(text("SELECT to_regclass('public.m306b_isolation_guard')"))
            if not guard: raise ValueError('缺少隔离测试数据库标记')
            marker=await conn.scalar(text('SELECT marker FROM public.m306b_isolation_guard LIMIT 1'))
            if marker != GUARD: raise ValueError('隔离测试数据库标记不匹配')
            await conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('m306b-draft-import'))"))
            session=async_sessionmaker(bind=conn,expire_on_commit=False)()
            async with session:
                for p in presets:
                    existing=await session.get(InterviewPreset,p['id'])
                    if existing:
                        if (existing.kind,existing.name,existing.version)!=(p['kind'],p['name'],p['version']): raise ValueError('预设版本冲突')
                    else:
                        session.add(InterviewPreset(**p,active=False,config={}))
                await session.flush()
                for q in questions:
                    existing=await session.scalar(select(InterviewQuestionBank).where(InterviewQuestionBank.preset_id==q['preset_id'],InterviewQuestionBank.content_code==q['code'],InterviewQuestionBank.version==q['version']))
                    if existing:
                        desired=SimpleNamespace(id=q['id'],preset_id=q['preset_id'],content_code=q['code'],version=q['version'],content=q['content'],topic=q['topic'],difficulty=q['difficulty'],sort_order=q['sort_order'],review_material=q['material'])
                        if question_digest(question_payload(existing))!=question_digest(question_payload(desired)): raise ValueError('题目版本内容冲突')
                    else:
                        session.add(InterviewQuestionBank(id=q['id'],preset_id=q['preset_id'],content_code=q['code'],version=q['version'],content=q['content'],topic=q['topic'],difficulty=q['difficulty'],sort_order=q['sort_order'],review_status='draft',review_material=q['material'],active=False))
                await session.flush()
    finally: await engine.dispose()
    return reports


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url',required=True)
    parser.add_argument('--manifest',default='../docs/interview/M3-06A-question-manifest.json')
    args=parser.parse_args()
    for code,size,digest in asyncio.run(import_draft(args.database_url,args.manifest)):
        print(f'{code}\t{size}\t{digest}')

if __name__=='__main__': main()
