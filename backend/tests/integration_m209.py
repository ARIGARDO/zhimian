import json, os, subprocess, sys, threading, time, signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx

captured=[]
class Upstream(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        captured.append(body['messages'])
        self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.end_headers()
        try:
            for i in range(25):
                self.wfile.write(b'data: {"choices":[{"delta":{"content":"x"}}]}\n\n'); self.wfile.flush()
                if 'upstream-drop' in body['messages'][-1]['content'] and i == 1:
                    self.close_connection=True; return
                time.sleep(.12)
            self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError): pass

server=ThreadingHTTPServer(('127.0.0.1',18777),Upstream)
threading.Thread(target=server.serve_forever,daemon=True).start()
env=os.environ.copy(); env.update(MODEL_BASE_URL='http://127.0.0.1:18777/v1', MODEL_NAME='test', MODEL_API_KEY='test-only', MODEL_TIMEOUT='10')
processes=[]; ids=[]
client=httpx.Client(timeout=15,trust_env=False)
a='http://127.0.0.1:18781/api/v1'; b='http://127.0.0.1:18782/api/v1'
def start(port):
    p=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    processes.append(p)
    for _ in range(100):
        try:
            if client.get(f'http://127.0.0.1:{port}/api/v1/health').status_code==200: return p
        except httpx.HTTPError: time.sleep(.1)
    raise RuntimeError('backend startup failed')
def new(topic=None):
    r=client.post(a+'/conversations',json={'title':'M2-09 临时测试','topic_id':topic}); r.raise_for_status(); cid=r.json()['id']; ids.append((cid,topic)); return cid
def scope(topic): return '?topic_id='+topic if topic else ''
def msgs(base,cid,topic=None):
    r=client.get(base+f'/conversations/{cid}/messages'+scope(topic)); r.raise_for_status(); return r.json()
def wait_status(base,cid,status):
    for _ in range(100):
        m=msgs(base,cid)
        if m and m[-1]['status']==status: return m
        time.sleep(.1)
    raise AssertionError('state did not reach '+status)
def stream_url(base,cid,topic=None): return base+f'/conversations/{cid}/messages/stream'+scope(topic)
def first_delta(response):
    iterator=response.iter_lines()
    for line in iterator:
        if line=='event: delta': return iterator
    raise AssertionError('missing delta')

try:
    p1=start(18781); p2=start(18782)
    cid=new()
    with client.stream('POST',stream_url(a,cid),json={'content':'concurrency'}) as first:
        assert first.status_code==200
        lines=first_delta(first)
        second=client.post(stream_url(b,cid),json={'content':'concurrent-other'})
        assert second.status_code==409
        assert msgs(b,cid)[-1]['status']=='streaming'
        assert 'event: done' in list(lines)
    m=wait_status(b,cid,'complete'); assert len(m)==2 and m[0]['content']=='concurrency'
    retry=client.post(stream_url(b,cid),json={'content':'after-release'}); assert retry.status_code==200 and 'event: done' in retry.text
    assert len(msgs(b,cid))==4
    print('双进程同会话并发 409、持锁至生成结束、释放后可再生成：通过')

    cid=new()
    with client.stream('POST',stream_url(a,cid),json={'content':'client-disconnect'}) as r:
        assert r.status_code==200; first_delta(r)
    m=wait_status(b,cid,'cancelled'); assert m[-1]['content']
    print('客户端硬断开：部分消息保存为 cancelled：通过')

    cid=new(); r=client.post(stream_url(a,cid),json={'content':'upstream-drop'})
    assert 'event: error' in r.text
    m=wait_status(b,cid,'error'); assert m[-1]['content']
    print('上游连接中断：错误事件及 error 持久化：通过')

    topics=client.get(a+'/topics').json(); t1=topics[0]['id']; t2=topics[1]['id']; assert t1!=t2
    c1=new(t1); c2=new(t2)
    for cid,topic in [(c1,t1),(c2,t2)]:
        r=client.post(stream_url(a,cid,topic),json={'content':'context-check'}); assert 'event: done' in r.text
        detail=client.get(a+f'/topics/{topic}').json()
        assert detail['content_md'][:100] in captured[-1][0]['content']
        assert len(msgs(a,cid,topic))==2
    assert c1 not in [x['id'] for x in client.get(a+'/conversations',params={'topic_id':t2}).json()]
    assert client.get(a+f'/conversations/{c1}/messages',params={'topic_id':t2}).status_code==404
    assert client.post(stream_url(a,c1,t2),json={'content':'wrong-scope'}).status_code==404
    assert client.delete(a+f'/conversations/{c1}',params={'topic_id':t2}).status_code==404
    print('两专题会话、上下文及后端跨范围读写限制：通过')

    cid=new()
    with client.stream('POST',stream_url(a,cid),json={'content':'process-crash'}) as r:
        assert r.status_code==200; first_delta(r)
        p1.kill(); p1.wait(timeout=5)
        try: list(r.iter_lines())
        except (httpx.HTTPError,RuntimeError): pass
    m=wait_status(b,cid,'cancelled'); assert len(m)==2
    p1=start(18781); assert msgs(a,cid)[-1]['status']=='cancelled'
    print('生成期间 SIGKILL、另一进程恢复状态及重启后历史读取：通过')
finally:
    for cid,topic in ids:
        try: client.delete(b+f'/conversations/{cid}'+scope(topic))
        except Exception: pass
    for p in processes:
        if p.poll() is None:
            p.terminate()
            try: p.wait(timeout=5)
            except subprocess.TimeoutExpired: p.kill()
    server.shutdown(); client.close()
