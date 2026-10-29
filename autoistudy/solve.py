"""解题：整卷打包成一个 prompt → 调 LLM → 解析 JSON → Answer 列表。"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import List, Tuple

from .core import Answer, Question, QuestionType, Settings

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是 Python 编程课的助教，请为下面这份试卷给出正确答案。

【答案格式】（机器要解析，必须严格遵守）
  单项选择题 single_choice   → "B"
  判断题 judge              → "A"（对）或 "B"（错），平台内部用 A/B 作为 value
  多选题 multi_choice       → JSON 数组字符串 "[\"A\",\"C\"]"，只选一个也要是数组
  填空题 fill_blank         → JSON 数组字符串 "[\"第1空\",\"第2空\"]"，只有一个空也一样
  编程题 / 简答题 short_answer → 完整代码或答案文本，换行写成 \\n

【规则】
  - 只给最终答案，不写解题过程
  - 没把握就写低 confidence（<0.7）；完全看不懂则 confidence=0 且 answer_text 留空
  - 编程题代码必须能直接运行；填空内容不要额外加引号或括号
  - 不要漏题、不要新增题目、不要改题目 id

【输出】
只输出一个 JSON 对象，不要 Markdown 代码块。key 是题号，value 形如：
{"61045435": {"answer_text": "B", "confidence": 0.95}, "61045490": {"answer_text": "print(1)", "confidence": 0.8}}
"""

USER_HEADER = """
======================== 试卷开始 ========================

试卷标题：{title}
共 {total} 道题，题型分布：{dist}

----------------------------------------------------------
"""

USER_FOOTER = """
======================== 试卷结束 ========================

请只输出纯 JSON 对象（不要 ```json 包裹、不要任何解释）。
每题都要有 key；漏题会按空答案处理。
"""

TYPE_ORDER = [
    QuestionType.SINGLE_CHOICE,
    QuestionType.JUDGE,
    QuestionType.MULTI_CHOICE,
    QuestionType.FILL_BLANK,
    QuestionType.SHORT_ANSWER,
]


def format_question(question: Question, index: int) -> str:
    lines = [f"[{question.id}] {question.type.value}（第{index}题，{question.score or '?'}分）"]
    lines.append("_" * 50)
    lines.extend(question.content.strip().splitlines() or ["(无题干)"])
    if question.options:
        lines.append("")
        lines.extend(f"  • {opt}" for opt in question.options)
    return "\n".join(lines) + "\n"


def build_prompt(questions: List[Question], title: str = "Python 编程作业") -> Tuple[str, str]:
    """返回 (system_prompt, user_prompt)。"""
    counts = Counter(q.type.value for q in questions)
    dist = "、".join(f"{v}×{k}" for k, v in counts.items())
    ordered = sorted(enumerate(questions, 1), key=lambda it: (TYPE_ORDER.index(it[1].type), it[0]))
    header = USER_HEADER.format(title=title, total=len(questions), dist=dist)
    body = "\n".join(format_question(q, idx) for idx, q in ordered)
    return SYSTEM_PROMPT, header + body + USER_FOOTER


def _json_text(raw: str) -> str:
    """去掉 ```json 围栏；再坏就截取首尾花括号之间的部分。"""
    text = re.sub(r"^```[A-Za-z]*\s*", "", raw.strip())
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_answers(raw: str, questions: List[Question]) -> List[Answer]:
    """把 LLM 的 JSON 回复映射成与 questions 同序的 Answer 列表。

    缺题、空答案都补成 answer_text="" / confidence=0，交给 main 报告。
    """
    text = _json_text(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"LLM 回复里没有 JSON 对象：{text[:200]}") from exc
        data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError(f"LLM 回复不是 JSON 对象：{text[:200]}")

    answers: List[Answer] = []
    for question in questions:
        entry = data.get(question.id, "")
        if isinstance(entry, dict):
            answer_text = str(entry.get("answer_text", ""))
            try:
                confidence = float(entry.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
        else:
            # 直接给字符串也认，置信度按中等处理
            answer_text = str(entry)
            confidence = 0.9 if answer_text else 0.0
        answers.append(Answer(question.id, answer_text, confidence))

    missing = [a.question_id for a in answers if not a.answer_text.strip()]
    if missing:
        log.warning("空答案 / 漏答 %d 道：%s", len(missing), missing)
    return answers


def call_llm(settings: Settings, system_prompt: str, user_prompt: str) -> str:
    """调 OpenAI 兼容 API；服务端不支持 json_object 时回退普通调用。"""
    from openai import OpenAI

    client = OpenAI(api_key=settings.api_key, base_url=settings.api_base)
    log.info("调用 %s，prompt 约 %d 字符", settings.model, len(user_prompt))
    kwargs = dict(
        model=settings.model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
    )
    try:
        resp = client.chat.completions.create(
            **kwargs, response_format={"type": "json_object"}
        )
    except Exception as exc:
        log.warning("服务端不支持 response_format=json_object（%s），改用普通调用", exc)
        resp = client.chat.completions.create(**kwargs)

    content = resp.choices[0].message.content or ""
    log.info("模型返回 %d 字符", len(content))
    return content


def solve_questions(
    settings: Settings,
    questions: List[Question],
    title: str = "Python 编程作业",
) -> List[Answer]:
    if not questions:
        return []
    system_prompt, user_prompt = build_prompt(questions, title=title)
    return parse_answers(call_llm(settings, system_prompt, user_prompt), questions)
