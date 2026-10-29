"""抓题器实现：istudyWork（zjcai.com 课外作业 / TestOne 页面）。

流程：
  1. GET TestOne 页面 → 从 HTML 解析出所有题目 ID + 题型分组
  2. 对每个题目 ID，GET /GoTest/QuestionOne?id={id}&mode=3 → 拿题干和选项

Cookie / Headers 等鉴权参数交给使用者在 .env 里补全，这里只写数据处理逻辑。

作者还发现的线索（供 submitter 使用，先记下来）：
  - 提交前保存单题答案 POST /GoTest/SaveQuestionOne （答案需 customObfuscate → rot13 → Base64）
  - 整体交卷接口：submitTest(userTestId) → 对应 JS 函数，submitter 阶段再深挖
"""
from __future__ import annotations
import logging
import re
import time
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    from .base import BaseFetcher
    from ..config.settings import settings
    from ..models.schema import Question, QuestionType
except ImportError:
    # 直接 python src/fetcher/impl_istudywork.py 运行时的兜底：补上项目根目录
    import sys
    from pathlib import Path as _P
    _root = _P(__file__).resolve().parent.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from src.fetcher.base import BaseFetcher           # type: ignore  # noqa: E402
    from src.config.settings import settings           # type: ignore  # noqa: E402
    from src.models.schema import Question, QuestionType  # type: ignore  # noqa: E402

log = logging.getLogger(__name__)


# dt 题型标题 → QuestionType 枚举
# 页面上 <dt> 的文本要 trim 掉 <b class="transform">&nbsp;</b> 等残留
_TYPE_MAP = {
    "单项选择题": QuestionType.SINGLE_CHOICE,
    "单选题":     QuestionType.SINGLE_CHOICE,
    "多选题":     QuestionType.MULTI_CHOICE,
    "填空题":     QuestionType.FILL_BLANK,
    "判断题":     QuestionType.JUDGE,
    "编程题":     QuestionType.SHORT_ANSWER,
    "简答题":     QuestionType.SHORT_ANSWER,
    "综合题":     QuestionType.SHORT_ANSWER,
}

# 题型枚举 → JS 页面里 dt 的中文标题（用于拼 qinfo）
_TYPE_TITLE: dict[QuestionType, str] = {
    QuestionType.SINGLE_CHOICE: "单项选择题",
    QuestionType.MULTI_CHOICE:  "多选题",
    QuestionType.FILL_BLANK:    "填空题",
    QuestionType.JUDGE:         "判断题",
    QuestionType.SHORT_ANSWER:  "编程题",
}


class IstudyWorkFetcher(BaseFetcher):
    """zjcai.com / GoTest / TestOne 页面的抓题器。"""

    def __init__(
        self,
        test_id: Optional[str] = None,
        testone_url: Optional[str] = None,
        cookie: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        # TestOne 页面 URL（形如 https://www.zjcai.com/GoTest/TestOne/101958）
        self.testone_url = testone_url or settings.fetcher.target_url
        # 用户测试实例 id（HTML 里 data-val-testid="3987256"），提交时要用
        self.test_instance_id = test_id

        # 请求会话
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": self.testone_url,
        })
        if cookie or settings.fetcher.cookie:
            self.session.headers["Cookie"] = cookie or settings.fetcher.cookie

        self.base_url = self._extract_base_url(self.testone_url)

    # -------------------------------------------------------------
    @staticmethod
    def _extract_base_url(testone_url: str) -> str:
        """从 TestOne URL 提取 scheme + host，例如 https://www.zjcai.com。"""
        return "/".join(testone_url.split("/")[:3])

    # -------------------------------------------------------------
    @staticmethod
    def _clean_type_title(raw_title: str) -> str:
        """<dt> 文本清理：去掉残留的 &nbsp;、空白字符。"""
        return re.sub(r"\s+", "", raw_title).replace("\xa0", "")

    # -------------------------------------------------------------
    @staticmethod
    def _map_type(title: str) -> QuestionType:
        """题型标题 → 枚举，未知的 fallback 为 SINGLE_CHOICE 并告警。"""
        qtype = _TYPE_MAP.get(title)
        if qtype is None:
            log.warning("未知题型分组：%s，fallback 为 SINGLE_CHOICE", title)
            qtype = QuestionType.SINGLE_CHOICE
        return qtype

    # -------------------------------------------------------------
    def _parse_question_list(self, html: str) -> tuple[str, List[tuple[str, QuestionType]]]:
        """从 TestOne 首页 HTML 解析出：
          - test_instance_id（用于后续提交）
          - 列表 [(question_id, QuestionType), ...]
        """
        soup = BeautifulSoup(html, "html.parser")

        # 1. 提取 test_instance_id：<a id="cmd_submit" ... data-val-testid="3987256">
        submit_btn = soup.select_one("a#cmd_submit")
        test_instance_id = ""
        if submit_btn and submit_btn.has_attr("data-val-testid"):
            test_instance_id = submit_btn["data-val-testid"]
            log.info("提取到 test_instance_id = %s", test_instance_id)

        # 2. 按 <dl class="bundle-item front"> 分组
        groups: List[tuple[str, QuestionType]] = []
        dl_nodes = soup.select("dl.bundle-item.front")
        log.info("共找到 %d 个题型分组", len(dl_nodes))

        for dl in dl_nodes:
            dt = dl.select_one("dt")
            if not dt:
                continue
            raw_title = dt.get_text(separator="")
            clean_title = self._clean_type_title(raw_title)
            qtype = self._map_type(clean_title)

            dd_nodes = dl.select("dd[data-val-id]")
            for dd in dd_nodes:
                qid = dd.get("data-val-id", "").strip()
                if qid:
                    groups.append((qid, qtype))

        log.info("解析到 %d 道题 ID", len(groups))
        return test_instance_id, groups

    # -------------------------------------------------------------
    def _parse_question_detail(self, html: str) -> tuple[str, List[str], float]:
        """从 /GoTest/QuestionOne 返回的片段 HTML 中提取题干、选项、分数。

        真实 DOM（2026-10-29 观察到）：

          <div class="question-item" id="61045435" data-type="SINGLE_CHIOCE">
            <div class="question-info">
              <table class="d-tbl autow"><tr><td>分数：</td><td>2</td></tr></table>
            </div>
            <div class="question-face"><p><span>“小于或等于”比较运算符是（ ）。</span></p></div>
            <div class="question-answer">
              <input class="question-option-input" type="radio" value="A" id="Question_61045435_OptionA" name="ANSWER_61045435" />
              <label for="Question_61045435_OptionA">A. <span><</span></label><br />
              ...
            </div>
          </div>

        编程题（SHORT_ANSWER）没有选项区域，只有 .question-face。
        """
        soup = BeautifulSoup(html, "html.parser")

        # --- 题干 ---
        content_node = soup.select_one(".question-face")
        if content_node is None:
            # 兜底：找 .question-content / .question-stem
            content_node = (
                soup.select_one(".question-content")
                or soup.select_one(".question-stem")
                or soup.select_one(".question-title")
            )
        content = content_node.get_text(separator="\n").strip() if content_node else ""

        # --- 选项 ---
        # 每个 input[type=radio/checkbox] 后面紧跟一个 <label>，label 才是选项描述
        options: List[str] = []
        seen_values = set()
        inputs = soup.select("input.question-option-input[type='radio'], "
                             "input.question-option-input[type='checkbox']")
        if not inputs:
            # 兜底：不用 class 过滤
            inputs = soup.select("input[type='radio'], input[type='checkbox']")
        for inp in inputs:
            val = inp.get("value", "").strip()
            if not val or val in seen_values:
                continue
            # 取紧邻的 <label for="...">
            label = soup.select_one(f'label[for="{inp.get("id", "")}"]')
            if label is None:
                label = inp.find_next_sibling("label")
            desc = label.get_text(separator=" ").strip() if label else val
            desc = re.sub(r"\s+", " ", desc)
            seen_values.add(val)
            options.append(desc)

        # --- 分数 ---
        score = 0.0
        info_table = soup.select_one(".question-info table.d-tbl")
        if info_table:
            tds = info_table.select("td")
            if len(tds) >= 2:
                try:
                    score = float(re.sub(r"[^\d.]", "", tds[1].get_text()))
                except ValueError:
                    pass

        return content, options, score

    # -------------------------------------------------------------
    def _fetch_question_detail(self, question_id: str) -> tuple[str, List[str], float]:
        """请求单题详情。失败时返回空。"""
        url = urljoin(self.base_url, "/GoTest/QuestionOne")
        try:
            resp = self.session.get(
                url,
                params={
                    "id": question_id,
                    "mode": 3,
                    "tail": int(time.time() * 1000),   # 原页面 JS 用时间戳做缓存破坏
                },
                timeout=settings.fetcher.timeout,
            )
            resp.raise_for_status()
            return self._parse_question_detail(resp.text)
        except Exception as exc:
            log.error("抓题详情失败 id=%s : %s", question_id, exc)
            return "", [], 0.0

    # -------------------------------------------------------------
    def fetch(self) -> List[Question]:
        """主入口：先抓 TestOne 首页 → 解析 ID 列表 → 逐题拉详情。"""
        if not self.testone_url:
            raise RuntimeError("IstudyWorkFetcher 需要 testone_url，请在 .env 中设置 FETCHER_URL")

        log.info("请求 TestOne 页面：%s", self.testone_url)
        resp = self.session.get(self.testone_url, timeout=settings.fetcher.timeout)
        resp.raise_for_status()

        test_instance_id, id_list = self._parse_question_list(resp.text)
        if test_instance_id and not self.test_instance_id:
            self.test_instance_id = test_instance_id

        questions: List[Question] = []
        # 每个题型出现了第几题，用来拼 qinfo（如"单项选择题第2题"）
        type_counters: dict[QuestionType, int] = {}
        for idx, (qid, qtype) in enumerate(id_list, 1):
            type_counters[qtype] = type_counters.get(qtype, 0) + 1
            type_index = type_counters[qtype]

            log.info("[%d/%d] 抓题 id=%s (%s)", idx, len(id_list), qid, qtype.value)
            content, options, score = self._fetch_question_detail(qid)

            # JS 里 qinfo = dt文本 + dd文本 = "单项选择题" + "第2题"
            type_title = _TYPE_TITLE.get(qtype, qtype.value)
            qinfo = f"{type_title}第{type_index}题"

            questions.append(Question(
                id=qid,
                content=content,
                type=qtype,
                options=options,
                score=score,
                raw={
                    "test_instance_id": self.test_instance_id,
                    "base_url": self.base_url,
                    "qinfo": qinfo,
                },
            ))

        log.info("抓题完成：%d 道", len(questions))
        return questions


# ============================================================
#   直接运行测试：python src/fetcher/impl_istudywork.py
# ============================================================
if __name__ == "__main__":
    from collections import Counter
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    fetcher = IstudyWorkFetcher()
    print(f"base_url    = {fetcher.base_url}")
    print(f"testone_url = {fetcher.testone_url}")
    print(f"has_cookie  = {bool(settings.fetcher.cookie)}")
    print()

    if not fetcher.testone_url:
        print("⚠ 请先在 .env 中设置 FETCHER_URL，或在构造函数中传入 testone_url=...")
    else:
        questions = fetcher.fetch()
        print(f"\n✓ 抓题完成，共 {len(questions)} 道")

        counter = Counter(q.type.value for q in questions)
        print(f"  题型分布：{dict(counter)}")
        print(f"  test_instance_id = {fetcher.test_instance_id}")

        for q in questions[:2]:
            print(f"\n--- id={q.id}  type={q.type.value}  score={q.score} ---")
            print(f"题干: {q.content[:80]}")
            for op in q.options[:4]:
                print(f"  {op}")

