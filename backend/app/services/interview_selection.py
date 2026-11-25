"""根据用户选项和 JD 关键词调整题目计划，不改变已冻结场次。"""
import re

# 只提取可解释的技术关键词；不把 JD 当作模型指令。
SKILLS = {
    'python': ('python', 'fastapi', 'django', 'flask'),
    'asyncio': ('asyncio', '异步', '并发', '协程', '事件循环'),
    'database': ('sql', '数据库', 'mysql', 'postgresql', '事务', '索引'),
    'api': ('api', '接口', 'http', '幂等', 'fastapi'),
    'cache': ('redis', '缓存'),
    'rag': ('rag', '检索', '召回', '文档切分'),
    'llm': ('llm', '大模型', '模型', '提示词', 'token'),
    'agent': ('agent', '智能体', '工具调用'),
    'embedding': ('embedding', '向量', '相似度'),
}


def skills(text: str) -> set[str]:
    text = text.lower()
    return {name for name, aliases in SKILLS.items() if any(
        (re.search(r'(?<![a-z0-9_])' + re.escape(alias) + r'(?![a-z0-9_])', text) if alias.isascii() else alias in text)
        for alias in aliases)}


def select_questions(questions, difficulty: str | None, jd: str | None, minimum: int | None):
    if difficulty:
        questions = [question for question in questions if question.difficulty == difficulty]
        if not questions:
            raise ValueError('所选难度暂无可用题目，请选择其他难度')
    if minimum and len(questions) < minimum:
        raise ValueError(f'所选题目仅有 {len(questions)} 道，不足 {minimum} 道；请减少题量或调整难度')
    detected = skills(jd or '')
    # “Python 后端”等岗位背景词较宽泛；有更具体技能时不让它淹没缓存或数据库需求。
    if len(detected) > 1:
        detected.discard('python')
    notice = None
    if jd:
        if not detected:
            notice = 'JD 未识别到支持的技能，已按预设题库顺序出题。'
        else:
            scored = [(len(detected & skills(q.topic + ' ' + q.content)), q) for q in questions]
            if any(score for score, _ in scored):
                questions = [q for _, q in sorted(scored, key=lambda row: -row[0])]
                notice = '已优先选择与 JD 技能匹配的题目；不足时使用同一题库的其他题目补足。'
            else:
                notice = 'JD 技能与当前题库未匹配，已按预设题库顺序出题。'
    return questions, notice
