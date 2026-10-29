"""终端报告的单测：只验证打印出来的信息是否足够定位问题。"""
from __future__ import annotations

from autoistudy.core import Answer, Question, QuestionType, SubmitResult
from autoistudy.report import one_line, print_answers, print_report

QUESTIONS = [
    Question("1", "“小于或等于”的运算符", QuestionType.SINGLE_CHOICE,
             ["A. <=", "B. <"], 2.0, "单项选择题第1题"),
    Question("2", "编写程序求和", QuestionType.SHORT_ANSWER, [], 5.0, "编程题第1题"),
]


def test_one_line_flattens_and_truncates():
    assert one_line("print(1)\nprint(2)") == "print(1) / print(2)"
    assert one_line("x" * 100, width=10) == "xxxxxxxxxx…"


def test_answers_preview(capsys):
    print_answers(QUESTIONS, [Answer("1", "A"), Answer("2", "print(1)")])
    out = capsys.readouterr().out
    assert "1  single_choice" in out
    assert "print(1)" in out


def test_report_without_submit(capsys):
    """DO_SUBMIT=False 时没有保存行。"""
    print_report(QUESTIONS, [Answer("1", "A", 0.9), Answer("2", "print(1)", 0.8)])
    out = capsys.readouterr().out
    assert "抓题   2 道" in out
    assert "有答案 2 道 / 空答案 0 道" in out
    assert "保存" not in out


def test_report_lists_empty_answers(capsys):
    print_report(QUESTIONS, [Answer("1", "A", 0.9), Answer("2", "", 0.0)])
    out = capsys.readouterr().out
    assert "有答案 1 道 / 空答案 1 道" in out
    assert "空答案（1 道）" in out
    assert "编写程序求和" in out     # 空答案要能定位到题干


def test_report_lists_low_confidence(capsys):
    print_report(QUESTIONS, [Answer("1", "A", 0.5), Answer("2", "print(1)", 0.8)])
    out = capsys.readouterr().out
    assert "低置信度（1 道）" in out
    assert "conf=0.50" in out


def test_report_lists_failures_but_not_empty_answers(capsys):
    result = SubmitResult(total=2, saved=1, details=[
        {"question_id": "1", "answer": "", "qinfo": "q1", "ok": False},      # 空答案已单独报
        {"question_id": "2", "answer": "print(1)", "qinfo": "q2", "ok": False},
    ], message="答案已逐题保存；整体交卷接口未对接")
    print_report(QUESTIONS, [Answer("1", "", 0.0), Answer("2", "print(1)", 0.8)], result)
    out = capsys.readouterr().out
    assert "保存   1/2 成功" in out
    assert "[x] 保存失败（1 道）" in out
    assert "整体交卷接口未对接" in out


def test_report_success_banner(capsys):
    result = SubmitResult(total=2, saved=2, details=[
        {"question_id": "1", "answer": "A", "qinfo": "q1", "ok": True},
        {"question_id": "2", "answer": "print(1)", "qinfo": "q2", "ok": True},
    ])
    print_report(QUESTIONS, [Answer("1", "A", 0.9), Answer("2", "print(1)", 0.8)], result)
    assert "[OK] 全部题都解出并保存成功。" in capsys.readouterr().out
