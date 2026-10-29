"""共享数据模型、配置与 HTTP 会话。

整个项目只有这一处定义 Question / Answer / Settings，
其余模块之间只通过它们交互。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import List

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "https://www.zjcai.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class QuestionType(str, Enum):
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    FILL_BLANK = "fill_blank"
    JUDGE = "judge"
    SHORT_ANSWER = "short_answer"


@dataclass
class Question:
    id: str
    content: str
    type: QuestionType = QuestionType.SINGLE_CHOICE
    options: List[str] = field(default_factory=list)
    score: float = 0.0
    qinfo: str = ""          # "单项选择题第2题"，提交时原样回传


@dataclass
class Answer:
    question_id: str
    answer_text: str
    confidence: float = 0.0


@dataclass
class SubmitResult:
    total: int = 0
    saved: int = 0
    details: List[dict] = field(default_factory=list)
    message: str = ""


@dataclass(frozen=True)
class Settings:
    """从环境变量 / .env 读取的全部配置。"""

    testone_url: str
    cookie: str
    timeout: float
    api_key: str
    api_base: str
    model: str
    temperature: float
    max_tokens: int
    submit_interval: float


def load_settings() -> Settings:
    return Settings(
        testone_url=os.getenv("FETCHER_URL", "").strip(),
        # 提交与抓题通常用同一个会话 Cookie，SUBMIT_COOKIE 可单独覆盖
        cookie=(os.getenv("SUBMIT_COOKIE") or os.getenv("FETCHER_COOKIE") or "").strip(),
        timeout=float(os.getenv("FETCHER_TIMEOUT", "15")),
        api_key=os.getenv("SOLVER_API_KEY", "").strip(),
        api_base=os.getenv("SOLVER_BASE_URL", "https://api.openai.com/v1").strip(),
        model=os.getenv("SOLVER_MODEL", "deepseek-chat").strip(),
        temperature=float(os.getenv("SOLVER_TEMPERATURE", "0.1")),
        max_tokens=int(os.getenv("SOLVER_MAX_TOKENS", "4096")),
        submit_interval=float(os.getenv("SUBMIT_INTERVAL", "1.0")),
    )


def make_session(cookie: str = "") -> requests.Session:
    """抓题和提交共用一个 Session（同一份 Cookie / UA）。"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    if cookie:
        session.headers["Cookie"] = cookie
    return session


def base_url_of(testone_url: str) -> str:
    """https://www.zjcai.com/GoTest/TestOne/101958 -> https://www.zjcai.com"""
    parts = testone_url.split("/")
    return "/".join(parts[:3]) if len(parts) >= 3 and parts[0] else DEFAULT_BASE_URL
