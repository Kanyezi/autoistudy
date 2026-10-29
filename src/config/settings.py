"""全局配置：从环境变量 / .env 文件加载。

使用示例：
    from src.config.settings import settings
    print(settings.target_url)
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()  # 自动读取项目根目录下的 .env


@dataclass
class FetcherConfig:
    """抓题相关配置。"""
    target_url: str = os.getenv("FETCHER_URL", "")
    cookie: str = os.getenv("FETCHER_COOKIE", "")
    timeout: int = int(os.getenv("FETCHER_TIMEOUT", "15"))
    retry: int = int(os.getenv("FETCHER_RETRY", "3"))


@dataclass
class SolverConfig:
    """AI 解题相关配置。"""
    api_key: str = os.getenv("SOLVER_API_KEY", "")
    base_url: str = os.getenv("SOLVER_BASE_URL", "https://api.openai.com/v1")
    model: str = os.getenv("SOLVER_MODEL", "gpt-4o-mini")
    temperature: float = float(os.getenv("SOLVER_TEMPERATURE", "0.1"))
    max_tokens: int = int(os.getenv("SOLVER_MAX_TOKENS", "1024"))


@dataclass
class SubmitterConfig:
    """提交答案相关配置。"""
    submit_url: str = os.getenv("SUBMIT_URL", "")
    cookie: str = os.getenv("SUBMIT_COOKIE", "")
    interval: float = float(os.getenv("SUBMIT_INTERVAL", "1.0"))  # 每题间隔秒数，防风控


@dataclass
class Settings:
    fetcher: FetcherConfig = field(default_factory=FetcherConfig)
    solver: SolverConfig = field(default_factory=SolverConfig)
    submitter: SubmitterConfig = field(default_factory=SubmitterConfig)


# 单例
settings = Settings()
