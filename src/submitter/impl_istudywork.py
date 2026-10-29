"""提交器实现：istudyWork（zjcai.com / GoTest / SaveQuestionOne）。

线索来源：
  - POST https://www.zjcai.com/GoTest/SaveQuestionOne
  - 负载：id=xxx&tail=时间戳&answer=编码串&answerext=&qinfo=单项选择题第2题
  - 答案编码链路（JS 源码）：customObfuscate → rot13 → Base64.encode

实测样本（id=61045436, qinfo=单项选择题第2题）：
    answer="A" → rot13("A")="N" → Base64("N")="Tg=="  ✅ 与抓包一致
"""
from __future__ import annotations
import base64
import logging
import time
from typing import List, Optional
from urllib.parse import urljoin

import requests

try:
    from .base import BaseSubmitter
    from ..config.settings import settings
    from ..models.schema import Answer, ExamResult
except ImportError:
    import sys
    from pathlib import Path as _P
    _root = _P(__file__).resolve().parent.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from src.submitter.base import BaseSubmitter           # type: ignore  # noqa: E402
    from src.config.settings import settings               # type: ignore  # noqa: E402
    from src.models.schema import Answer, ExamResult       # type: ignore  # noqa: E402

log = logging.getLogger(__name__)


# ---------------------------------------------------------
# 答案编码工具（等价 JS 端的 encodeAnswer）
# ---------------------------------------------------------

_CUSTOM_MAP = {
    "%": "【PERCENT】", ".2f": "【DOT2F】", "printf": "【PRINTF】",
    "eval": "【EVAL】", "script": "【SCRIPT】", "<": "【LT】", ">": "【GT】",
    "union": "【UNION】", "select": "【SELECT】", "alert": "【ALERT】",
}


def _custom_obfuscate(s: str) -> str:
    for key, val in _CUSTOM_MAP.items():
        s = s.replace(key, val)
    return s


def _rot13(s: str) -> str:
    out = []
    for c in s:
        code = ord(c)
        if 65 <= code <= 90:    # A-Z
            out.append(chr((code - 65 + 13) % 26 + 65))
        elif 97 <= code <= 122:  # a-z
            out.append(chr((code - 97 + 13) % 26 + 97))
        else:
            out.append(c)
    return "".join(out)


def encode_answer(plain: str) -> str:
    """Python 版 JS encodeAnswer：customObfuscate → rot13 → Base64。"""
    if not plain:
        return ""
    step1 = _custom_obfuscate(plain)
    step2 = _rot13(step1)
    step3 = base64.b64encode(step2.encode("utf-8")).decode("ascii")
    return step3


# 快速验证编码逻辑 —— import 时断言检查
# 用户给的样本 answer=Tg== → Base64 decode="N" → rot13 反解="A"
assert encode_answer("A") == "Tg==", f"期望 'Tg=='，实际 '{encode_answer('A')}'"
assert encode_answer("B") == "Tw==", f"期望 'Tw=='，实际 '{encode_answer('B')}'"
assert encode_answer("") == ""
assert _rot13(_rot13("Hello, World!")) == "Hello, World!"


# ---------------------------------------------------------
# 提交器实现
# ---------------------------------------------------------

class IstudyWorkSubmitter(BaseSubmitter):
    """zjcai.com / GoTest 页面的答案提交器。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        cookie: Optional[str] = None,
        interval: Optional[float] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.base_url = base_url or "https://www.zjcai.com"
        self.interval = interval if interval is not None else settings.submitter.interval

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": f"{self.base_url}/GoTest/TestOne",
            "X-Requested-With": "XMLHttpRequest",
        })
        ck = cookie or settings.submitter.cookie or settings.fetcher.cookie
        if ck:
            self.session.headers["Cookie"] = ck

    # -------------------------------------------------------------
    def build_payload(
        self,
        question_id: str,
        answer_text: str,
        qinfo: str,
        answerext: str = "",
    ) -> dict:
        """构造 SaveQuestionOne 表单负载，字段与浏览器抓包一一对应。"""
        return {
            "id": question_id,
            "tail": int(time.time() * 1000),
            "answer": encode_answer(answer_text),
            "answerext": answerext,
            "qinfo": qinfo,
        }

    # -------------------------------------------------------------
    def save_one(
        self,
        question_id: str,
        answer_text: str,
        qinfo: str,
        answerext: str = "",
    ) -> bool:
        """保存单题答案（POST SaveQuestionOne）。返回 True 表示服务器确认成功。"""
        url = urljoin(self.base_url, "/GoTest/SaveQuestionOne")
        try:
            resp = self.session.post(
                url,
                data=self.build_payload(question_id, answer_text, qinfo, answerext),
                timeout=15,
            )
            resp.raise_for_status()
            # JS 端判断 data.Success
            data = resp.json()
            if data.get("Success"):
                log.info("保存成功 id=%s  answer=%s  qinfo=%s", question_id, answer_text, qinfo)
                return True
            else:
                log.warning("保存失败 id=%s  err=%s", question_id, data.get("ErrorMessage"))
                return False
        except Exception as exc:
            log.error("SaveQuestionOne 异常 id=%s : %s", question_id, exc)
            return False

    # -------------------------------------------------------------
    def submit(
        self,
        answers: List[Answer],
        qinfo_map: Optional[dict] = None,
    ) -> ExamResult:
        """主入口：批量保存所有答案。

        qinfo_map: {question_id: "单项选择题第2题"}，由 fetcher 的
        Question.raw["qinfo"] 汇总而来；缺省时 qinfo 字段留空。

        注意：SaveQuestionOne 只负责单题保存，整体交卷接口尚未对接。
        """
        if not answers:
            return ExamResult(success=False, message="答案列表为空")

        qinfo_map = qinfo_map or {}
        success_count = 0
        details = []

        for i, ans in enumerate(answers, 1):
            qinfo = qinfo_map.get(ans.question_id, "")
            log.info("[%d/%d] 保存 id=%s", i, len(answers), ans.question_id)
            ok = self.save_one(ans.question_id, ans.answer_text, qinfo)
            details.append({
                "question_id": ans.question_id,
                "answer": ans.answer_text,
                "qinfo": qinfo,
                "ok": ok,
            })
            if ok:
                success_count += 1
            if i < len(answers):
                time.sleep(self.interval)   # 风控：每题间隔

        # TODO: 整体交卷接口待用户补充（JS submitTest 函数的具体 URL）
        log.info("单题保存完成 %d/%d，整体交卷接口暂未对接", success_count, len(answers))

        return ExamResult(
            submitted_count=success_count,
            success=success_count == len(answers),
            details=details,
            message=f"SaveQuestionOne {success_count}/{len(answers)} 成功；整体交卷未对接",
        )


# ============================================================
#   直接运行：python src/submitter/impl_istudywork.py
#   默认只打印负载、不发请求；确认真实提交时把 REAL_SUBMIT 改为 True
# ============================================================
REAL_SUBMIT = False

if __name__ == "__main__":
    from src.fetcher.impl_istudywork import IstudyWorkFetcher

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    submitter = IstudyWorkSubmitter()

    # 与抓包样本对齐的离线校验：id=61045436 / 答案 A / qinfo=单项选择题第2题
    payload = submitter.build_payload("61045436", "A", "单项选择题第2题")
    print("负载（对应抓包样本）：")
    for k, v in payload.items():
        print(f"  {k} = {v}")
    print(f"  answer 是否符合抓包 Tg== : {payload['answer'] == 'Tg=='}")

    if not REAL_SUBMIT:
        print("\n当前为干跑模式，未发送请求。如需真实提交，把 REAL_SUBMIT 改为 True。")
    else:
        fetcher = IstudyWorkFetcher()
        questions = fetcher.fetch()
        print(f"\n抓到 {len(questions)} 道题，test_instance_id={fetcher.test_instance_id}")
        first = questions[0]
        ok = submitter.save_one(first.id, "A", first.raw["qinfo"])
        print(f"保存 id={first.id} ({first.raw['qinfo']}) → {'成功' if ok else '失败'}")
