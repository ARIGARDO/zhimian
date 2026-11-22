"""审核题目的规范化内容及摘要；不向公开接口返回材料。"""
import hashlib
import json

from app.services.interview import InterviewConflict


def question_payload(question):
    material = question.review_material
    required = {'objectives', 'key_points', 'anchors', 'alternatives', 'misconceptions'}
    if not isinstance(material, dict) or set(material) != required:
        raise InterviewConflict('题目审核材料不完整')
    if not isinstance(material['objectives'], str) or not material['objectives'].strip():
        raise InterviewConflict('题目审核材料不完整')
    for key in ('key_points', 'alternatives', 'misconceptions'):
        if not isinstance(material[key], list) or not material[key] or any(not isinstance(v, str) or not v.strip() for v in material[key]):
            raise InterviewConflict('题目审核材料不完整')
    anchors = material['anchors']
    if not isinstance(anchors, dict) or set(anchors) != {'complete', 'adequate', 'partial', 'insufficient'} or any(not isinstance(v, str) or not v.strip() for v in anchors.values()):
        raise InterviewConflict('题目审核材料不完整')
    return {'id':question.id, 'preset_id':question.preset_id, 'code':question.content_code,
            'version':question.version, 'content':question.content, 'topic':question.topic,
            'difficulty':question.difficulty, 'sort_order':question.sort_order, 'material':material}


def question_digest(payload):
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()
