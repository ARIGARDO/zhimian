import json
from pathlib import Path
import pytest
from app.tools.import_interview_draft import load_manifest
from app.tools.publish_interview_bank import verify_approval

MANIFEST = Path(__file__).resolve().parents[2] / 'docs/interview/M3-06A-question-manifest.json'


def test_explicit_individual_approval_matches_complete_digest(tmp_path):
    _, _, reports = load_manifest(MANIFEST)
    approval = {'reviewer': '隔离测试审核人', 'approved_at': '2026-01-01T12:00:00+00:00', 'questions': {reports[0][0]: reports[0][2]}}
    path = tmp_path / 'approval.json'
    path.write_text(json.dumps(approval), encoding='utf-8')
    _, questions, reviewer, at = verify_approval(MANIFEST, path)
    assert len(questions) == 1 and questions[0]['code'] == reports[0][0] and reviewer == approval['reviewer'] and at.tzinfo
    approval['questions'][reports[0][0]] = '0' * 64
    path.write_text(json.dumps(approval), encoding='utf-8')
    with pytest.raises(ValueError, match='摘要不匹配'):
        verify_approval(MANIFEST, path)
    approval['reviewer'] = ''
    path.write_text(json.dumps(approval), encoding='utf-8')
    with pytest.raises(ValueError, match='审核人'):
        verify_approval(MANIFEST, path)
