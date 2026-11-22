import json
from pathlib import Path
import pytest
from app.tools.import_interview_draft import load_manifest, validate_url

MANIFEST=Path(__file__).resolve().parents[2]/'docs/interview/M3-06A-question-manifest.json'

def test_manifest_complete_and_bounded():
    presets,questions,report=load_manifest(MANIFEST)
    assert len(presets)==2 and len(questions)==len(report)==20
    assert max(size for _,size,_ in report)<=1200
    assert {q['code'] for q in questions}=={f'{prefix}{i:02}' for prefix in 'PA' for i in range(1,11)}
    assert all(q['content_status']=='待最终启用确认' for q in questions)
    assert next(q for q in questions if q['code']=='P04')['content'].startswith('热点缓存 Key 过期')

@pytest.mark.parametrize('url',[
    'postgresql+asyncpg://a:b@localhost/zhimian_m306b_test',
    'postgresql+asyncpg://a:b@127.0.0.1/zhimian',
    'postgresql+asyncpg://a:b@192.0.2.1/zhimian_m306b_test',
    'sqlite+aiosqlite:///zhimian_m306b_test',
])
def test_reject_nonisolated_urls(url):
    with pytest.raises(ValueError): validate_url(url)

def test_manifest_rejects_duplicate_code(tmp_path):
    data=json.loads(MANIFEST.read_text()); data['questions'][1]['code']=data['questions'][0]['code']
    target=tmp_path/'manifest.json'; target.write_text(json.dumps(data))
    with pytest.raises(ValueError): load_manifest(target)
