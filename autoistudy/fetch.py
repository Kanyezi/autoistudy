"""抓题：TestOne 首页 → 题目 ID 列表 → 逐题详情。

解析函数（parse_testone_page / parse_question_detail）都是纯函数，
方便用固定 HTML 做离线单测；网络逻辑集中在 fetch_questions。
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .core import Question, QuestionType, Settings, base_url_of, make_session

log = logging.getLogger(__name__)

# 页面上的题型标题 → 枚举
TYPE_BY_TITLE = {
    "单项选择题": QuestionType.SINGLE_CHOICE,
    "单选题": QuestionType.SINGLE_CHOICE,
    "多选题": QuestionType.MULTI_CHOICE,
    "填空题": QuestionType.FILL_BLANK,
    "判断题": QuestionType.JUDGE,
    "编程题": QuestionType.SHORT_ANSWER,
    "简答题": QuestionType.SHORT_ANSWER,
    "综合题": QuestionType.SHORT_ANSWER,
}

# 枚举 → 拼 qinfo 用的中文标题
TITLE_BY_TYPE = {
    QuestionType.SINGLE_CHOICE: "单项选择题",
    QuestionType.MULTI_CHOICE: "多选题",
    QuestionType.FILL_BLANK: "填空题",
    QuestionType.JUDGE: "判断题",
    QuestionType.SHORT_ANSWER: "编程题",
}


@dataclass
class FetchResult:
    questions: List[Question]
    test_instance_id: str = ""


def clean_type_title(raw: str) -> str:
    """<dt> 文本清理：<b class="transform">&nbsp;</b> 之类残留全部去掉。"""
    return re.sub(r"\s+", "", raw).replace("\xa0", "")


def map_type(title: str) -> QuestionType:
    qtype = TYPE_BY_TITLE.get(title)
    if qtype is None:
        log.warning("未知题型 %r，按单选处理", title)
        return QuestionType.SINGLE_CHOICE
    return qtype


def parse_testone_page(html: str) -> Tuple[str, List[Tuple[str, QuestionType]]]:
    """解析试卷首页，返回 (test_instance_id, [(题目 id, 题型), ...])。"""
    soup = BeautifulSoup(html, "html.parser")

    submit_btn = soup.select_one("a#cmd_submit")
    test_instance_id = ""
    if submit_btn and submit_btn.has_attr("data-val-testid"):
        test_instance_id = submit_btn["data-val-testid"]

    groups: List[Tuple[str, QuestionType]] = []
    for dl in soup.select("dl.bundle-item.front"):
        dt = dl.select_one("dt")
        if not dt:
            continue
        qtype = map_type(clean_type_title(dt.get_text(separator="")))
        for dd in dl.select("dd[data-val-id]"):
            qid = dd.get("data-val-id", "").strip()
            if qid:
                groups.append((qid, qtype))

    log.debug("解析到 %d 道题", len(groups))
    return test_instance_id, groups


def parse_question_detail(html: str) -> Tuple[str, List[str], float]:
    """解析单题片段，返回 (题干, 选项, 分值)。

    真实 DOM：
      <div class="question-face">题干</div>
      <input class="question-option-input" type="radio" value="A" id="..."/>
      <label for="...">A. 选项文本</label>
    编程题只有 .question-face，没有选项。
    """
    soup = BeautifulSoup(html, "html.parser")

    node = soup.select_one(".question-face") or soup.select_one(
        ".question-content, .question-stem, .question-title"
    )
    content = node.get_text(separator="\n").strip() if node else ""

    options: List[str] = []
    seen = set()
    inputs = soup.select(
        "input.question-option-input[type='radio'], "
        "input.question-option-input[type='checkbox']"
    ) or soup.select("input[type='radio'], input[type='checkbox']")
    for inp in inputs:
        value = inp.get("value", "").strip()
        if not value or value in seen:
            continue
        label = soup.select_one(f'label[for="{inp.get("id", "")}"]') or inp.find_next_sibling("label")
        text = label.get_text(separator=" ").strip() if label else value
        seen.add(value)
        options.append(re.sub(r"\s+", " ", text))

    score = 0.0
    info = soup.select_one(".question-info table.d-tbl")
    if info:
        tds = info.select("td")
        if len(tds) >= 2:
            try:
                score = float(re.sub(r"[^\d.]", "", tds[1].get_text()))
            except ValueError:
                pass

    return content, options, score


def fetch_detail(
    session: requests.Session,
    base_url: str,
    question_id: str,
    timeout: float,
) -> Tuple[str, List[str], float]:
    """拉单题详情，失败返回空值（不阻断整份试卷）。"""
    try:
        resp = session.get(
            urljoin(base_url, "/GoTest/QuestionOne"),
            params={"id": question_id, "mode": 3, "tail": int(time.time() * 1000)},
            headers={"Referer": base_url},
            timeout=timeout,
        )
        resp.raise_for_status()
        return parse_question_detail(resp.text)
    except Exception as exc:  # 单题失败只跳过这一题
        log.error("抓题失败 id=%s: %s", question_id, exc)
        return "", [], 0.0


def fetch_questions(
    settings: Settings,
    session: Optional[requests.Session] = None,
    limit: int = 0,
) -> FetchResult:
    """主入口：抓整份试卷。limit > 0 时只取前 limit 道（调试用）。"""
    if not settings.testone_url:
        raise RuntimeError("未配置 FETCHER_URL，请在 .env 中填写试卷地址")

    session = session or make_session(settings.cookie)
    log.info("请求试卷首页 %s", settings.testone_url)
    resp = session.get(settings.testone_url, timeout=settings.timeout)
    resp.raise_for_status()

    test_instance_id, id_list = parse_testone_page(resp.text)
    if not id_list:
        log.warning("首页没有解析到题目，Cookie 可能已过期")
        return FetchResult([], test_instance_id)

    if limit > 0:
        id_list = id_list[:limit]
    log.info("共 %d 道题（test_instance_id=%s）", len(id_list), test_instance_id or "?")

    base_url = base_url_of(settings.testone_url)
    counters: dict[QuestionType, int] = {}
    questions: List[Question] = []
    for idx, (qid, qtype) in enumerate(id_list, 1):
        counters[qtype] = counters.get(qtype, 0) + 1
        qinfo = f"{TITLE_BY_TYPE.get(qtype, qtype.value)}第{counters[qtype]}题"
        log.info("[%d/%d] %s (%s)", idx, len(id_list), qid, qtype.value)
        content, options, score = fetch_detail(session, base_url, qid, settings.timeout)
        questions.append(Question(
            id=qid,
            content=content,
            type=qtype,
            options=options,
            score=score,
            qinfo=qinfo,
        ))

    return FetchResult(questions, test_instance_id)
