"""抓题模块 —— 抽象基类。

子类需实现 fetch()，返回 List[Question]。
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List
from ..models.schema import Question


class BaseFetcher(ABC):
    """所有抓题器的基类。"""

    def __init__(self, **kwargs):
        self.session = None  # 子类可在此初始化 requests.Session

    @abstractmethod
    def fetch(self) -> List[Question]:
        """执行抓题，返回题目列表。"""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"
