"""解题层的单测：prompt 拼装 + LLM 回复解析（不调 API）。"""
from __future__ import annotations

import pytest

from autoistudy.core import Question, QuestionType
from autoistudy.solve import build_prompt, format_question, parse_answers


def make_questions():
    return [
        Question("1", "“小于或等于”的运算符是（ ）", QuestionType.SINGLE_CHOICE,
                 ["A. <=", "B. <", "C. =<"], 2.0, "单项选择题第1题"),
        Question("2", "执行 print(bool(0)) 输出？", QuestionType.JUDGE,
                 ["A. 对", "B. 错"], 1.0, "判断题第1题"),
        Question("3", "编写程序求和", QuestionType.SHORT_ANSWER, [], 5.0, "编程题第1题"),
    ]


class TestFormat:
    def test_question_block_contains_id_type_and_options(self):
        block = format_question(make_questions()[0], 1)
        assert "[1]" in block
        assert "single_choice" in block
        assert "A. <=" in block
        assert "2.0分" in block

    def test_program_question_has_no_option_lines(self):
        block = format_question(make_questions()[2], 3)
        assert "编写程序求和" in block
        assert "•" not in block


class TestBuildPrompt:
    def test_contains_every_question_once(self):
        system_prompt, user_prompt = build_prompt(make_questions())
        assert "JSON" in system_prompt
        for qid in ("1", "2", "3"):
            assert f"[{qid}]" in user_prompt
        assert user_prompt.count("[1]") == 1

    def test_orders_by_type(self):
        _, user_prompt = build_prompt(make_questions())
        assert user_prompt.index("[1]") < user_prompt.index("[2]") < user_prompt.index("[3]")


class TestParseAnswers:
    def test_plain_json(self):
        raw = '{"1": {"answer_text": "A", "confidence": 0.95}, "2": {"answer_text": "B", "confidence": 0.6}}'
        answers = parse_answers(raw, make_questions())
        assert [a.answer_text for a in answers] == ["A", "B", ""]
        assert answers[0].confidence == 0.95

    def test_fenced_json(self):
        raw = '```json\n{"1": {"answer_text": "A", "confidence": 0.9}}\n```'
        answers = parse_answers(raw, make_questions())
        assert answers[0].answer_text == "A"

    def test_fenced_json_with_prose(self):
        raw = '好的，答案如下：\n{"3": {"answer_text": "print(1)", "confidence": 0.8}}\n以上。'
        answers = parse_answers(raw, make_questions())
        assert answers[2].answer_text == "print(1)"

    def test_missing_question_becomes_empty_answer(self):
        answers = parse_answers('{"1": {"answer_text": "A"}}', make_questions())
        assert answers[1].answer_text == ""
        assert answers[1].confidence == 0.0

    def test_bare_string_value_is_accepted(self):
        answers = parse_answers('{"1": "A"}', make_questions())
        assert answers[0].answer_text == "A"
        assert answers[0].confidence > 0

    def test_order_matches_questions(self):
        raw = '{"3": {"answer_text": "code"}, "1": {"answer_text": "A"}}'
        answers = parse_answers(raw, make_questions())
        assert [a.question_id for a in answers] == ["1", "2", "3"]

    def test_non_object_json_raises(self):
        with pytest.raises(ValueError):
            parse_answers('["A", "B"]', make_questions())

    def test_garbage_raises(self):
        with pytest.raises(ValueError):
            parse_answers("模型今天不想说话", make_questions())
