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
    assert all(q['content_status']=='待审核' for q in questions)
    assert next(q for q in questions if q['code']=='P04')['content'].startswith('热点缓存 Key 过期')

def test_reviewed_edits_keep_other_questions_and_anchors():
    _,questions,report=load_manifest(MANIFEST)
    digests=dict((code,digest) for code,_,digest in report)
    original={'P01':'99f38b1ac7867cbd257f43605abbc4d876b5a65b7644ff7893c76b8ad88645a7','P02':'7c747308c624e478aec3a17b8e958144cbac08bbca5b69af476ec74db2397292','P03':'7ff1acabe03cc2d6fce8a90e68309dfbac29f8f8f6b85260fbe67f9f5f7ea018','P04':'12132ba91103f20fe8d3bdd1b86dddf771379c4d2c4804beeef92348713ae64a','P07':'5875c0d0779ee525d11bceb60ab5a29db8fdc12fad1361257fc1ddff43618304','P08':'ee0b7a1c4842e1aeb1fdffaa90b44c409e660862bae47219212273347080b35f','P09':'65cadc25aec800da2c60f017d27a25348a7d190f28371176d498445436d256f6','P10':'f2b4fb2f91cbf783af5bec7a26469bbeb4e0e987c2ce4687f40a8aeb84fb07b0','A01':'7bfc2a19df3c989fe1e032359e9e6a875ae9bd0f98b3b15b522678f120c55846','A02':'632544254dd0e8c47150792608c4116961434905d359930d999775c379fdb292','A03':'9bbb66c12f4fbb09bbff426662f3da7d37f7448a90db485271beb9d2f770ff6a','A04':'8c8078f39b7d0fd5317c0707c5e2a6175f6545e2606c3d4ada5c00df5b0e6fa4','A05':'f4f4dd27e24eb65ebe99ccf0e1eadbceb958fe48c979cddb1bc0064029993ecb','A07':'02eadc49745fe6c8b908138ea9364b9049bc9e92dbb0cf1681235c8e9935dfbe','A08':'1e95ff452c734228466cd3602c77e00c2f65f5913013f93e985f551cfde1fa02','A09':'eed1e1376ac93f2229f93511fb564800066363b25fd75cbc9e314b3a4e21b7ae'}
    assert all(digests[code]==digest for code,digest in original.items())
    by={q['code']:q for q in questions}
    assert by['P05']['material']['anchors']=={'complete':'说明主要环节与异常清理','adequate':'说明校验、处理和会话释放','partial':'只描述处理函数','insufficient':'忽视校验与资源生命周期'}
    assert by['P06']['material']['anchors']=={'complete':'区分五类并举贴切例子','adequate':'主要类别和例子正确','partial':'区分客户端与服务端错误但部分混淆','insufficient':'将所有失败统一视为 500'}
    assert by['A06']['material']['anchors']=={'complete':'解释取舍并提出验证','adequate':'说明过大过小的问题','partial':'只知道有长度限制','insufficient':'认为切分粒度不会影响效果'}
    assert by['A10']['material']['anchors']=={'complete':'覆盖证据、版本、人工复核和偏差','adequate':'要求基于作答并进行人工检查','partial':'只强调使用更强模型','insufficient':'将模型评分视为客观能力结论'}
    assert all(code in by['P06']['material']['alternatives'][0] for code in ('400','409','422'))
    for preset in ('bank-python-v1','bank-ai-v1'):
        ordered=sorted((q for q in questions if q['preset_id']==preset),key=lambda q:({'basic':0,'intermediate':1,'challenge':2}[q['difficulty']],q['sort_order'],q['code']))
        assert [q['difficulty'] for q in ordered]==['basic']*4+['intermediate']*5+['challenge']

@pytest.mark.parametrize('url',[
    'postgresql+asyncpg://a:b@localhost/zhimian_m306b_test',
    'postgresql+asyncpg://a:b@127.0.0.1/zhimian',
    'postgresql+asyncpg://a:b@192.0.2.1/zhimian_m306b_test',
    'sqlite+aiosqlite:///zhimian_m306b_test',
    'postgresql+asyncpg://a:b@127.0.0.1/zhimian_m306b_test?host=remote.example:5432',
    'postgresql+asyncpg://a:b@127.0.0.1/zhimian_m306b_test?database=production',
    'postgresql+asyncpg://a:b@127.0.0.1/zhimian_m306b_test#fragment',
])
def test_reject_nonisolated_urls(url):
    with pytest.raises(ValueError): validate_url(url)

def test_manifest_rejects_duplicate_code(tmp_path):
    data=json.loads(MANIFEST.read_text()); data['questions'][1]['code']=data['questions'][0]['code']
    target=tmp_path/'manifest.json'; target.write_text(json.dumps(data))
    with pytest.raises(ValueError): load_manifest(target)
