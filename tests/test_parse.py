"""抓题解析的离线单测：喂固定 HTML，不联网。

网站改版时先坏的就是这里，所以解析逻辑是唯一必须留测试的部分。
"""
from __future__ import annotations

import pytest

from autoistudy.core import QuestionType, base_url_of
from autoistudy.fetch import (
    clean_type_title,
    map_type,
    parse_question_detail,
    parse_testone_page,
)

# TestOne 首页：4 个题型分组
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

QUESTION_ONE_SINGLE = """\
<div class="question-item" id="61045435" data-type="SINGLE_CHIOCE">
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
</div>
"""

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


class TestCleanTypeTitle:
    def test_strips_nbsp_and_whitespace(self):
        assert clean_type_title("单项选择题") == "单项选择题"
        assert clean_type_title("单项选择  题") == "单项选择题"
        assert clean_type_title("单项\u00a0选择\u00a0题") == "单项选择题"


class TestMapType:
    @pytest.mark.parametrize("title,expected", [
        ("单项选择题", QuestionType.SINGLE_CHOICE),
        ("多选题", QuestionType.MULTI_CHOICE),
        ("填空题", QuestionType.FILL_BLANK),
        ("判断题", QuestionType.JUDGE),
        ("编程题", QuestionType.SHORT_ANSWER),
        ("简答题", QuestionType.SHORT_ANSWER),
        ("综合题", QuestionType.SHORT_ANSWER),
    ])
    def test_known_types(self, title, expected):
        assert map_type(title) == expected

    def test_unknown_falls_back_to_single_choice(self, caplog):
        with caplog.at_level("WARNING"):
            assert map_type("冷门题型") == QuestionType.SINGLE_CHOICE
        assert "未知题型" in caplog.text


class TestBaseUrl:
    def test_normal(self):
        assert base_url_of("https://www.zjcai.com/GoTest/TestOne/101958") == "https://www.zjcai.com"

    def test_http_without_trailing_slash(self):
        assert base_url_of("http://example.com/path/to/page") == "http://example.com"

    def test_empty_falls_back_to_default(self):
        assert base_url_of("") == "https://www.zjcai.com"


class TestParseTestonePage:
    def test_extracts_test_instance_id(self):
        tid, _ = parse_testone_page(TESTONE_HTML)
        assert tid == "3987256"

    def test_groups_and_type_counts(self):
        _, groups = parse_testone_page(TESTONE_HTML)
        assert len(groups) == 7   # 单选3 + 填空2 + 判断1 + 编程1
        counts = {}
        for _, qtype in groups:
            counts[qtype] = counts.get(qtype, 0) + 1
        assert counts == {
            QuestionType.SINGLE_CHOICE: 3,
            QuestionType.FILL_BLANK: 2,
            QuestionType.JUDGE: 1,
            QuestionType.SHORT_ANSWER: 1,
        }

    def test_ids_keep_page_order(self):
        _, groups = parse_testone_page(TESTONE_HTML)
        assert [qid for qid, _ in groups][:3] == ["61045435", "61045436", "61045437"]

    def test_missing_submit_button(self):
        tid, groups = parse_testone_page("<div id='content_left'></div>")
        assert tid == ""
        assert groups == []

    def test_empty_html(self):
        assert parse_testone_page("<html></html>") == ("", [])


class TestParseQuestionDetail:
    def test_single_choice(self):
        content, options, score = parse_question_detail(QUESTION_ONE_SINGLE)
        assert "小于或等于" in content
        assert len(options) == 3
        assert options[0].startswith("A.")
        assert options[2].startswith("C.")
        assert score == 2.0

    def test_judge(self):
        content, options, score = parse_question_detail(QUESTION_ONE_JUDGE)
        assert "print(bool(0))" in content
        assert options == ["A. 对", "B. 错"]
        assert score == 1.0

    def test_program_has_no_options(self):
        content, options, score = parse_question_detail(QUESTION_ONE_PROGRAM)
        assert "编写程序" in content
        assert options == []
        assert score == 5.0

    def test_empty_html(self):
        assert parse_question_detail("") == ("", [], 0.0)
