"""仅用于显式指定的隔离 PostgreSQL 数据库；不会连接默认数据库。"""
import asyncio
import os
import subprocess
import sys
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

url = os.environ['M306_TEST_DATABASE_URL']
name = urlsplit(url).path.lstrip('/')
if not name.startswith('zhimian_m306_') or not name.replace('_', '').isalnum():
    raise ValueError('仅允许 zhimian_m306_ 前缀的隔离数据库')
env = dict(os.environ, DATABASE_URL=url)
subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', '0007_interview_model_grace'], env=env, check=True)
engine = create_async_engine(url, poolclass=NullPool)

async def setup():
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO topics (id,category,category_label,title,summary,content_md,sort_order) VALUES ('t','python','Python','existing','summary','content',1)"))
        await conn.execute(text("INSERT INTO learning_progress (topic_id,reading_position,completed) VALUES ('t',0.5,true)"))
        await conn.execute(text("INSERT INTO conversations (id,title,topic_id) VALUES ('c','existing chat','t')"))
        await conn.execute(text("INSERT INTO messages (id,conversation_id,role,content,status) VALUES ('m','c','user','existing message','complete')"))
        await conn.execute(text("INSERT INTO interview_presets (id,kind,name,version,active,config) VALUES ('p','bank','test',1,true,'{}')"))
        await conn.execute(text("INSERT INTO interview_question_bank (id,preset_id,content,topic,version,active) VALUES ('legacy','p','existing','test',1,true)"))
asyncio.run(setup())
subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env=env, check=True)

async def main():
    async with engine.begin() as conn:
        assert (await conn.execute(text("SELECT content FROM interview_question_bank WHERE id='legacy'"))).scalar_one() == 'existing'
        assert (await conn.execute(text("SELECT title FROM topics WHERE id='t'"))).scalar_one() == 'existing'
        assert (await conn.execute(text("SELECT reading_position FROM learning_progress WHERE topic_id='t'"))).scalar_one() == 0.5
        assert (await conn.execute(text("SELECT content FROM messages WHERE id='m'"))).scalar_one() == 'existing message'
        await conn.execute(text("INSERT INTO interview_question_bank (id,preset_id,content,topic,version,active,content_code,difficulty,sort_order,review_status,review_material,reviewed_by,reviewed_at) VALUES ('v1','p','reviewed','test',1,true,'P01','basic',1,'approved','{}','tester',now())"))
    async with engine.connect() as conn:
        try:
            async with conn.begin(): await conn.execute(text("UPDATE interview_question_bank SET content='changed' WHERE id='v1'"))
            raise AssertionError('已审核版本被修改')
        except Exception as exc:
            if isinstance(exc, AssertionError): raise
    async with engine.connect() as conn:
        try:
            async with conn.begin(): await conn.execute(text("INSERT INTO interview_question_bank (id,preset_id,content,topic,version,active,content_code,difficulty,sort_order,review_status,review_material) VALUES ('v2','p','draft','test',2,true,'P01','basic',1,'draft','{}')"))
            raise AssertionError('未审核题目被启用')
        except Exception as exc:
            if isinstance(exc, AssertionError): raise
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO interview_question_bank (id,preset_id,content,topic,version,active,content_code,difficulty,sort_order,review_status,review_material,reviewed_by,reviewed_at) VALUES ('v2','p','reviewed2','test',2,false,'P01','basic',1,'approved','{}','tester',now())"))
    async def activate(version_id):
        try:
            async with engine.begin() as conn: await conn.execute(text("UPDATE interview_question_bank SET active=true WHERE id=:id"), {'id':version_id})
            return True
        except Exception: return False
    results = await asyncio.gather(activate('v2'), activate('v2'))
    assert not any(results)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE interview_question_bank SET active=false WHERE id='v1'"))
    results = await asyncio.gather(activate('v1'), activate('v2'))
    assert sorted(results) == [False, True]
    print('隔离 PostgreSQL 迁移、旧数据保留、版本不可变、审核启用和并发唯一约束：通过')
    await engine.dispose()

asyncio.run(main())
