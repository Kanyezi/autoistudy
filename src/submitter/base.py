"""提交答案模块 —— 抽象基类。

子类需实现 submit()，输入 Answer 列表，输出 ExamResult。
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List
from ..models.schema import Answer, ExamResult


class BaseSubmitter(ABC):
    """所有提交器的基类。"""

    def __init__(self, **kwargs):
        pass

    @abstractmethod
    def submit(self, answers: List[Answer]) -> ExamResult:
        """提交所有答案，返回结果摘要。"""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"
