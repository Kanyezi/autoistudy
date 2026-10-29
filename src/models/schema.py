"""共享数据模型：Question / Answer / ExamResult。

三个模块（fetcher / solver / submitter）只通过这些模型交互，
不直接依赖彼此的内部实现，从而实现解耦。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class QuestionType(str, Enum):
    """题目类型枚举，按需扩展。"""
    SINGLE_CHOICE = "single_choice"   # 单选
    MULTI_CHOICE  = "multi_choice"   # 多选
    FILL_BLANK    = "fill_blank"     # 填空
    JUDGE         = "judge"          # 判断
    SHORT_ANSWER  = "short_answer"   # 简答 / 编程


@dataclass
class Question:
    """题目：由 fetcher 产出，喂给 solver。"""
    id: str                                  # 题目唯一标识（题号 / hash）
    content: str                             # 题干
    type: QuestionType = QuestionType.SINGLE_CHOICE
    options: List[str] = field(default_factory=list)  # 选项（选择题用）
    score: float = 0.0                       # 分值
    raw: dict = field(default_factory=dict)  # 原始抓取的额外字段，保留扩展


@dataclass
class Answer:
    """答案：由 solver 产出，交给 submitter。"""
    question_id: str                         # 对应 Question.id
    answer_text: str                         # 答案字符串
    confidence: float = 0.0                  # AI 置信度（0~1）
    reasoning: str = ""                      # 推理过程（可选，便于调试）


@dataclass
class ExamResult:
    """提交结果：由 submitter 返回。"""
    submitted_count: int = 0                 # 提交了几题
    correct_count: Optional[int] = None      # 正确数（若平台返回）
    score: Optional[float] = None           # 总得分（若平台返回）
    details: List[dict] = field(default_factory=list)  # 每题提交详情
    success: bool = False                    # 整体是否提交成功
    message: str = ""                        # 附加信息 / 错误说明
