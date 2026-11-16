"""真实模型低量联调；仅允许专用隔离数据库，不输出模型内容或密钥。"""
import asyncio
import os
import subprocess
import sys
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from app.services.interview import InterviewService, recommended_rules
from app.services.interview_ai import InterviewAIService

name=os.environ['M304_TEST_DB']
if not name.startswith('zhimian_m304_') or not name.replace('_','').isalnum(): raise ValueError('仅允许隔离测试数据库')
url=os.environ['DATABASE_URL'].rsplit('/',1)[0]+'/'+name
env=os.environ.copy(); env['DATABASE_URL']=url
subprocess.run(['alembic','upgrade','head'],env=env,check=True)
engine=create_async_engine(url,poolclass=NullPool); factory=async_sessionmaker(engine,expire_on_commit=False)

async def main():
    async def call(method,*args,**kwargs):
        async with factory() as db: return await getattr(InterviewService(db,recommended_rules()),method)(*args,**kwargs)
    cid=await call('create',mode='practice',limit_type='count',main_limit=3,duration_seconds=None,preset_snapshot={'kind':'bank'},config_snapshot={})
    await call('start',cid,'start')
    q=await call('add_question',cid,'q','解释 Python 异步编程中的事件循环。')
    a=await call('answer',cid,'a',q['id'],'事件循环负责在等待异步操作时调度其他任务。')
    ai=InterviewAIService(factory)
    follow=await ai.run(cid,'follow','followup',a['id'])
    feedback=await ai.run(cid,'feedback','feedback',a['id'])
    await call('end',cid,'end','terminated','测试结束')
    report=await ai.run(cid,'report','report','partial')
    full_id=await call('create',mode='formal',limit_type='count',main_limit=3,duration_seconds=None,preset_snapshot={'kind':'bank'},config_snapshot={})
    await call('start',full_id,'start')
    for number in range(3):
        question=await call('add_question',full_id,f'q{number}',f'测试问题{number}：解释 Python 异步任务。')
        await call('answer',full_id,f'a{number}',question['id'],'异步任务适合等待网络或数据库等操作。')
        await call('close_main',full_id,f'c{number}')
    full=await ai.run(full_id,'full-report','report','full')
    for label,result in [('追问',follow),('练习反馈',feedback),('部分报告',report),('完整报告',full)]:
        print('真实模型'+label+'：'+result['status']+(('（'+result.get('error','')+'）') if result['status']!='complete' else ''))
    await engine.dispose()
    if any(x['status']!='complete' for x in (follow,feedback,report,full)): sys.exit(1)

asyncio.run(main())
