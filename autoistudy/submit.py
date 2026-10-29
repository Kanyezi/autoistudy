"""提交：把答案编码后逐题 POST 到 /GoTest/SaveQuestionOne。

编码链路与网页 JS 的 encodeAnswer 一致：
    customObfuscate → rot13 → Base64
样本：answer="A" → rot13="N" → Base64="Tg=="（与抓包一致）
"""
from __future__ import annotations

import base64
import logging
import time
from typing import List, Optional
from urllib.parse import urljoin

import requests

from .core import Answer, Question, Settings, SubmitResult, base_url_of, make_session

log = logging.getLogger(__name__)

# 与网页 JS 保持一致的替换表（防注入式混淆，照抄，不要“优化”）
CUSTOM_MAP = {
    "%": "【PERCENT】", ".2f": "【DOT2F】", "printf": "【PRINTF】",
    "eval": "【EVAL】", "script": "【SCRIPT】", "<": "【LT】", ">": "【GT】",
    "union": "【UNION】", "select": "【SELECT】", "alert": "【ALERT】",
}


def custom_obfuscate(text: str) -> str:
    for key, value in CUSTOM_MAP.items():
        text = text.replace(key, value)
    return text


def rot13(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch)
        if 65 <= code <= 90:
            out.append(chr((code - 65 + 13) % 26 + 65))
        elif 97 <= code <= 122:
            out.append(chr((code - 97 + 13) % 26 + 97))
        else:
            out.append(ch)
    return "".join(out)


def encode_answer(plain: str) -> str:
    if not plain:
        return ""
    return base64.b64encode(rot13(custom_obfuscate(plain)).encode("utf-8")).decode("ascii")


def build_payload(question_id: str, answer_text: str, qinfo: str, answerext: str = "") -> dict:
    """构造 SaveQuestionOne 表单，字段与浏览器抓包一一对应。"""
    return {
        "id": question_id,
        "tail": int(time.time() * 1000),
        "answer": encode_answer(answer_text),
        "answerext": answerext,
        "qinfo": qinfo,
    }


def save_one(
    session: requests.Session,
    base_url: str,
    question_id: str,
    answer_text: str,
    qinfo: str,
    timeout: float = 15.0,
) -> bool:
    """保存单题答案，返回服务器是否确认成功。"""
    try:
        resp = session.post(
            urljoin(base_url, "/GoTest/SaveQuestionOne"),
            data=build_payload(question_id, answer_text, qinfo),
            headers={
                "Referer": f"{base_url}/GoTest/TestOne",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.error("保存失败 id=%s: %s", question_id, exc)
        return False

    if data.get("Success"):
        log.info("保存成功 id=%s answer=%r qinfo=%s", question_id, answer_text[:40], qinfo)
        return True
    log.warning("保存被拒绝 id=%s err=%s", question_id, data.get("ErrorMessage"))
    return False


def submit_answers(
    settings: Settings,
    answers: List[Answer],
    questions: List[Question],
    session: Optional[requests.Session] = None,
) -> SubmitResult:
    """逐题保存。空答案不发请求（在平台上留空更糟），按失败计数。"""
    if not answers:
        return SubmitResult(total=0, saved=0, message="没有答案可保存")

    session = session or make_session(settings.cookie)
    base_url = base_url_of(settings.testone_url)
    qinfo_map = {q.id: q.qinfo for q in questions}

    details: List[dict] = []
    saved = 0
    for index, answer in enumerate(answers, 1):
        qinfo = qinfo_map.get(answer.question_id, "")
        if not answer.answer_text.strip():
            log.warning("[%d/%d] 跳过空答案 id=%s", index, len(answers), answer.question_id)
            ok = False
        else:
            log.info("[%d/%d] 保存 id=%s", index, len(answers), answer.question_id)
            ok = save_one(
                session, base_url, answer.question_id,
                answer.answer_text, qinfo, settings.timeout,
            )
        details.append({
            "question_id": answer.question_id,
            "answer": answer.answer_text,
            "qinfo": qinfo,
            "ok": ok,
        })
        if ok:
            saved += 1
        if index < len(answers):
            time.sleep(settings.submit_interval)   # 每题间隔，避免触发风控

    return SubmitResult(
        total=len(answers),
        saved=saved,
        details=details,
        message="答案已逐题保存",
    )
