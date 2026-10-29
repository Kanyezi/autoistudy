"""IstudyWorkFetcher 单元 + 集成测试。

测试分层：
  - 单元测试（test_parse_*）：喂固定 HTML 样本，不联网，秒级通过
  - 集成测试（test_integration_fetch）：真实请求站点，需要 .env 里有 Cookie
    运行：  pytest -m integration              # 只跑集成
    或：    pytest -m "not integration"         # 只跑单元
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

# 让 tests/ 下可以直接 import src/
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from src.fetcher.impl_istudywork import IstudyWorkFetcher
from src.models.schema import QuestionType


# ============================================================
#   HTML 样本（2026-10-29 实测 zjcai.com 返回）
# ============================================================

# TestOne 首页 —— 只截关键结构（4 个题型分组 + 部分题目 ID）
TESTONE_HTML = """\
<!DOCTYPE html><html><body>
<a id="cmd_submit" class="button green r2" href="javascript:;" data-val-testid="3987256">提交作业</a>
<div id="content_left">
<dl class="bundle-item front">
<dt><b class="transform">&nbsp;</b> <a href="javascript:;">单项选择题</a></dt>
<dd data-val-id="61045435" class="undo"><a href="javascript:;">第1题</a></dd>
<dd data-val-id="61045436" class="undo"><a href="javascript:;">第2题</a></dd>
<dd data-val-id="61045437" class="undo"><a href="javascript:;">第3题</a></dd>
</dl>
<dl class="bundle-item front">
<dt><b class="transform">&nbsp;</b> <a href="javascript:;">填空题</a></dt>
<dd data-val-id="61045465" class="undo"><a href="javascript:;">第1题</a></dd>
<dd data-val-id="61045466" class="undo"><a href="javascript:;">第2题</a></dd>
</dl>
<dl class="bundle-item front">
<dt><b class="transform">&nbsp;</b> <a href="javascript:;">判断题</a></dt>
<dd data-val-id="61045470" class="undo"><a href="javascript:;">第1题</a></dd>
</dl>
<dl class="bundle-item front">
<dt><b class="transform">&nbsp;</b> <a href="javascript:;">编程题</a></dt>
<dd data-val-id="61045490" class="undo"><a href="javascript:;">第1题</a></dd>
</dl>
</div></body></html>
"""

# QuestionOne —— 单选题
QUESTION_ONE_SINGLE = """\
<div class="question-item" id="61045435" data-type="SINGLE_CHIOCE"
     data-type-judgeonsave="0" data-type-heavyjudger="0"
     data-judge-status="Idle" data-judge-history="False">
    <div class="question-info">
        <table class="d-tbl autow"><tr><td class="text-right">分数：</td><td>2</td></tr></table>
    </div>
    <div class="question-face"><p><span>"小于或等于"比较运算符是（&nbsp;&nbsp;&nbsp; ）。</span></p></div>
    <div class="question-answer">
        <input class="question-option-input" type="radio" value="A" id="Q_A" name="ANSWER_X" />
        <label for="Q_A">A. <span>&lt;=</span></label><br />
        <input class="question-option-input" type="radio" value="B" id="Q_B" name="ANSWER_X" />
        <label for="Q_B">B. <span>&lt;</span></label><br />
        <input class="question-option-input" type="radio" value="C" id="Q_C" name="ANSWER_X" />
        <label for="Q_C">C. <span>=&lt;</span></label>
    </div>
    <div class="question-spinner lf"></div>
</div>
"""

# QuestionOne —— 判断题
QUESTION_ONE_JUDGE = """\
<div class="question-item" id="61045470" data-type="JUDGE">
    <div class="question-info">
        <table class="d-tbl autow"><tr><td class="text-right">分数：</td><td>1</td></tr></table>
    </div>
    <div class="question-face"><p>执行语句print(bool(0))，其输出结果是False。</p></div>
    <div class="question-answer">
        <input class="question-option-input" type="radio" value="A" id="J_A" name="ANSWER_Y" />
        <label for="J_A">A. 对</label><br />
        <input class="question-option-input" type="radio" value="B" id="J_B" name="ANSWER_Y" />
        <label for="J_B">B. 错</label>
    </div>
</div>
"""

# QuestionOne —— 编程题（无选项）
QUESTION_ONE_PROGRAM = """\
<div class="question-item" id="61045490" data-type="PROGRAM_DESIGN">
    <div class="question-info">
        <table class="d-tbl autow"><tr><td class="text-right">分数：</td><td>5</td></tr></table>
    </div>
    <div class="question-face">
        <p>【描述】<br />编写程序，计算下面序列的和。</p>
        <p>【输出】在一行中输出结果，保留2位小数。</p>
    </div>
</div>
"""


# ============================================================
#   Fixture
# ============================================================

@pytest.fixture
def fetcher() -> IstudyWorkFetcher:
    """带一个占位 URL 的 fetcher（不触发真实请求）。"""
    return IstudyWorkFetcher(testone_url="https://www.zjcai.com/GoTest/TestOne/101958")


# ============================================================
#   单元测试：题型标题清理 / 映射
# ============================================================

class TestTypeMapping:
    def test_clean_type_title_strips_nbsp_and_whitespace(self, fetcher):
        assert fetcher._clean_type_title("单项选择题") == "单项选择题"
        assert fetcher._clean_type_title("单项选择  题") == "单项选择题"
        assert fetcher._clean_type_title("单项\u00a0选择\u00a0题") == "单项选择题"

    def test_known_types_map_correctly(self, fetcher):
        cases = [
            ("单项选择题", QuestionType.SINGLE_CHOICE),
            ("填空题", QuestionType.FILL_BLANK),
            ("判断题", QuestionType.JUDGE),
            ("编程题", QuestionType.SHORT_ANSWER),
            ("简答题", QuestionType.SHORT_ANSWER),
            ("综合题", QuestionType.SHORT_ANSWER),
        ]
        for title, expected in cases:
            assert fetcher._map_type(title) == expected

    def test_unknown_type_falls_back_to_single_choice(self, fetcher, caplog):
        with caplog.at_level("WARNING"):
            result = fetcher._map_type("冷门题型")
        assert result == QuestionType.SINGLE_CHOICE
        assert "未知题型分组" in caplog.text


# ============================================================
#   单元测试：base_url 提取
# ============================================================

class TestBaseUrl:
    def test_extract_base_url_normal(self):
        url = "https://www.zjcai.com/GoTest/TestOne/101958"
        assert IstudyWorkFetcher._extract_base_url(url) == "https://www.zjcai.com"

    def test_extract_base_url_no_trailing_slash(self):
        url = "http://example.com/path/to/page"
        assert IstudyWorkFetcher._extract_base_url(url) == "http://example.com"


# ============================================================
#   单元测试：TestOne 首页解析
# ============================================================

class TestParseQuestionList:
    def test_extracts_test_instance_id(self, fetcher):
        tid, _ = fetcher._parse_question_list(TESTONE_HTML)
        assert tid == "3987256"

    def test_groups_and_ids(self, fetcher):
        tid, groups = fetcher._parse_question_list(TESTONE_HTML)

        # 总数
        assert len(groups) == 7   # 单选3 + 填空2 + 判断1 + 编程1

        # 题型分布
        type_counts: dict[QuestionType, int] = {}
        for _, qt in groups:
            type_counts[qt] = type_counts.get(qt, 0) + 1
        assert type_counts[QuestionType.SINGLE_CHOICE] == 3
        assert type_counts[QuestionType.FILL_BLANK] == 2
        assert type_counts[QuestionType.JUDGE] == 1
        assert type_counts[QuestionType.SHORT_ANSWER] == 1

    def test_ids_in_order(self, fetcher):
        _, groups = fetcher._parse_question_list(TESTONE_HTML)
        ids = [qid for qid, _ in groups]
        assert ids[:3] == ["61045435", "61045436", "61045437"]

    def test_no_submit_btn_gives_empty_id(self, fetcher):
        html_no_submit = "<div id='content_left'></div>"
        tid, _ = fetcher._parse_question_list(html_no_submit)
        assert tid == ""

    def test_empty_html_gives_no_groups(self, fetcher):
        tid, groups = fetcher._parse_question_list("<html></html>")
        assert tid == ""
        assert groups == []


# ============================================================
#   单元测试：QuestionOne 详情解析
# ============================================================

class TestParseQuestionDetail:
    def test_single_choice_extracts_content_options_score(self, fetcher):
        content, options, score = fetcher._parse_question_detail(QUESTION_ONE_SINGLE)

        assert "小于或等于" in content
        assert len(options) == 3
        # 选项描述以 "A." / "B." 开头
        assert options[0].startswith("A.")
        assert options[1].startswith("B.")
        assert options[2].startswith("C.")
        assert score == 2.0

    def test_judge_extracts_content_and_two_options(self, fetcher):
        content, options, score = fetcher._parse_question_detail(QUESTION_ONE_JUDGE)

        assert "print(bool(0))" in content
        assert options == ["A. 对", "B. 错"]
        assert score == 1.0

    def test_programming_has_no_options(self, fetcher):
        content, options, score = fetcher._parse_question_detail(QUESTION_ONE_PROGRAM)

        assert "编写程序" in content
        assert options == []
        assert score == 5.0

    def test_empty_html_gives_zero_values(self, fetcher):
        content, options, score = fetcher._parse_question_detail("")
        assert content == ""
        assert options == []
        assert score == 0.0


# ============================================================
#   集成测试（需要 .env 中 FETCHER_COOKIE 可用）
# ============================================================

@pytest.mark.integration
class TestIntegration:
    def test_full_fetch_pipeline(self):
        """完整跑通 fetcher.fetch()，返回 57 道完整 Question 对象。"""
        cookie = os.getenv("FETCHER_COOKIE", "").strip()
        if not cookie:
            pytest.skip("未配置 FETCHER_COOKIE，跳过集成测试")

        fetcher = IstudyWorkFetcher()
        questions = fetcher.fetch()

        assert len(questions) == 57, f"期望 57 道，实际 {len(questions)} 道"

        # test_instance_id 被写入 raw
        assert fetcher.test_instance_id == "3987256"
        for q in questions:
            assert q.raw["test_instance_id"] == "3987256"

        # 题干和分数不应全为空
        filled_content = [q for q in questions if q.content]
        assert len(filled_content) >= 50, f"题干空太多：只有 {len(filled_content)}/57 道有题干"

        # 单选 / 判断 / 填空应有选项
        choice_like = [q for q in questions
                       if q.type in (QuestionType.SINGLE_CHOICE, QuestionType.JUDGE, QuestionType.MULTI_CHOICE)]
        with_options = [q for q in choice_like if q.options]
        assert len(with_options) >= len(choice_like) - 3, \
            f"选项缺失太多：{len(with_options)}/{len(choice_like)}"

        # 编程题应该没有选项
        programs = [q for q in questions if q.type == QuestionType.SHORT_ANSWER]
        for q in programs:
            assert q.options == [], f"编程题不该有选项：{q.id} -> {q.options}"
