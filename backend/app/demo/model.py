"""本地确定性模拟接口；输出仅用于体验流程，不代表 AI 评价。"""
import json
import hashlib
from app.services.retrieval import terms
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()


@app.post('/v1/chat/completions')
async def chat(request: Request):
    data = await request.json()
    messages = data.get('messages', [])
    system = messages[0].get('content', '') if messages else ''
    if '返回结构：' not in system:
        content = '【模拟回复】这是本地演示内容，并非真实模型生成。请结合专题资料继续学习。'
    elif '原回答ID' in system:
        records = json.loads(messages[-1]['content'])
        result = {'summary': '【模拟复盘】以下内容仅用于演示流程，不构成真实评价。', 'items': [{'answer_id': record['answer_id'], 'review': '【模拟建议】请结合题目复习相关专题，并自行核对实际回答。'} for record in records]}
        if 'overall_score' in system:
            result['overall_score'] = 0.0
        content = json.dumps(result, ensure_ascii=False)
    elif '"feedback"' in system:
        content = json.dumps({'feedback': '【模拟反馈】请结合专题资料检查回答，不代表真实评价。'}, ensure_ascii=False)
    else:
        content = json.dumps({'question': '【模拟追问】你会如何验证这个方案？'}, ensure_ascii=False)
    async def events():
        yield 'data: ' + json.dumps({'choices': [{'delta': {'content': content}, 'finish_reason': None}]}, ensure_ascii=False) + '\n\n'
        yield 'data: [DONE]\n\n'
    return StreamingResponse(events(), media_type='text/event-stream')


@app.post('/v1/embeddings')
async def embeddings(request: Request):
    data = await request.json()
    inputs = data.get('input', [])
    if isinstance(inputs, str): inputs = [inputs]
    result = []
    for index, text in enumerate(inputs):
        vector = [0.0] * 384
        for word in terms(text):
            vector[int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], 'big') % 384] += 1.0
        if not any(vector): vector[0] = 1.0
        result.append({'index': index, 'embedding': vector})
    return {'model': 'demo-hash-384', 'data': result}
