"""AI 解题模块 —— 抽象基类。

子类需实现 solve()，输入单个 Question，输出 Answer。
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List
from ..models.schema import Question, Answer


class BaseSolver(ABC):
    """所有 AI 解题器的基类。"""

    def __init__(self, **kwargs):
        pass

    @abstractmethod
    def solve(self, question: Question) -> Answer:
        """解一道题，返回 Answer。"""
        raise NotImplementedError

    def solve_batch(self, questions: List[Question]) -> List[Answer]:
        """批量解题，默认逐条调用 solve()，子类可覆盖以支持并发。"""
        return [self.solve(q) for q in questions]

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"
