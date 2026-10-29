"""答案编码 + 提交载荷的单测（不碰网络）。"""
from __future__ import annotations

from autoistudy.core import Answer, Question, Settings
from autoistudy.submit import (
    build_payload,
    custom_obfuscate,
    encode_answer,
    rot13,
    save_one,
    submit_answers,
)


class FakeResponse:
    def __init__(self, data=None, error: Exception | None = None):
        self._data = data
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._data


class FakeSession:
    """记录请求，并返回预置响应。"""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data, "headers": headers})
        return self.response


def make_settings(**overrides) -> Settings:
    base = dict(
        testone_url="https://www.zjcai.com/GoTest/TestOne/101958",
        cookie="", timeout=5.0, api_key="k", api_base="http://x",
        model="m", temperature=0.1, max_tokens=100, submit_interval=0.0,
    )
    base.update(overrides)
    return Settings(**base)


class TestEncode:
    def test_matches_captured_samples(self):
        # 抓包样本：A -> "Tg=="，B -> "Tw=="
        assert encode_answer("A") == "Tg=="
        assert encode_answer("B") == "Tw=="

    def test_empty_stays_empty(self):
        assert encode_answer("") == ""

    def test_rot13_roundtrip(self):
        assert rot13(rot13("Hello, World!")) == "Hello, World!"

    def test_obfuscation_replaces_dangerous_tokens(self):
        assert custom_obfuscate("<select>") == "【LT】【SELECT】【GT】"
        # 先替换再编码：encode("<") 等于 encode("【LT】")
        assert encode_answer("<") == encode_answer("【LT】")


class TestPayload:
    def test_fields_match_browser_capture(self):
        payload = build_payload("61045436", "A", "单项选择题第2题")
        assert payload["id"] == "61045436"
        assert payload["answer"] == "Tg=="
        assert payload["qinfo"] == "单项选择题第2题"
        assert payload["answerext"] == ""
        assert isinstance(payload["tail"], int)


class TestSaveOne:
    def test_success(self):
        session = FakeSession(FakeResponse({"Success": True}))
        assert save_one(session, "https://www.zjcai.com", "1", "A", "单项选择题第1题") is True
        assert session.calls[0]["url"].endswith("/GoTest/SaveQuestionOne")
        assert session.calls[0]["data"]["answer"] == "Tg=="

    def test_server_rejects(self):
        session = FakeSession(FakeResponse({"Success": False, "ErrorMessage": "cookie 过期"}))
        assert save_one(session, "https://www.zjcai.com", "1", "A", "q") is False

    def test_network_error_is_swallowed(self):
        session = FakeSession(FakeResponse(error=RuntimeError("timeout")))
        assert save_one(session, "https://www.zjcai.com", "1", "A", "q") is False


class TestSubmitAnswers:
    def test_saves_each_answer_with_qinfo(self):
        session = FakeSession(FakeResponse({"Success": True}))
        questions = [Question("1", "题干", qinfo="单项选择题第1题"),
                     Question("2", "题干", qinfo="判断题第1题")]
        answers = [Answer("1", "A"), Answer("2", "B")]

        result = submit_answers(make_settings(), answers, questions, session=session)

        assert (result.total, result.saved) == (2, 2)
        assert [d["ok"] for d in result.details] == [True, True]
        assert session.calls[0]["data"]["qinfo"] == "单项选择题第1题"
        assert session.calls[1]["data"]["qinfo"] == "判断题第1题"

    def test_empty_answer_is_not_sent(self):
        session = FakeSession(FakeResponse({"Success": True}))
        questions = [Question("1", "题干", qinfo="单项选择题第1题")]
        answers = [Answer("1", "")]

        result = submit_answers(make_settings(), answers, questions, session=session)

        assert result.saved == 0
        assert session.calls == []      # 空答案不该白占一次请求
        assert result.details[0]["ok"] is False

    def test_no_answers(self):
        result = submit_answers(make_settings(), [], [])
        assert (result.total, result.saved) == (0, 0)
        assert result.message
