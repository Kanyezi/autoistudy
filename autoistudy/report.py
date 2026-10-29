"""终端报告：把题目、答案、保存结果打印成人能看的几段。"""
from __future__ import annotations

from typing import List, Optional

from .core import Answer, Question, SubmitResult


def one_line(text: str, width: int = 48) -> str:
    """把多行答案压成一行，便于在终端里看。"""
    flat = " / ".join(line for line in text.strip().splitlines() if line.strip())
    return flat if len(flat) <= width else flat[:width] + "…"


def print_answers(questions: List[Question], answers: List[Answer]) -> None:
    print("\n答案预览：")
    for question, answer in zip(questions, answers):
        print(f"  {question.id}  {question.type.value:13s}  {one_line(answer.answer_text)}")


def print_report(
    questions: List[Question],
    answers: List[Answer],
    result: Optional[SubmitResult] = None,
) -> None:
    empty = [a for a in answers if not a.answer_text.strip()]
    low_conf = [a for a in answers if 0 < a.confidence < 0.7]
    # 空答案已经单独列出，这里只报真正提交失败的
    failed = [d for d in (result.details if result else [])
              if not d["ok"] and d["answer"].strip()]

    print()
    print("=" * 60)
    print(f"  抓题   {len(questions)} 道")
    print(f"  解题   有答案 {len(answers) - len(empty)} 道 / 空答案 {len(empty)} 道"
          f"   低置信度 {len(low_conf)} 道")
    if result is not None:
        print(f"  保存   {result.saved}/{result.total} 成功")
    print("=" * 60)

    if empty:
        print(f"\n[!] 空答案（{len(empty)} 道），需要人工补：")
        for answer in empty:
            question = next((q for q in questions if q.id == answer.question_id), None)
            print(f"  {answer.question_id}  {question.content[:40] if question else ''}")

    if low_conf:
        print(f"\n[!] 低置信度（{len(low_conf)} 道），建议复核：")
        for answer in low_conf:
            print(f"  {answer.question_id}  conf={answer.confidence:.2f}  "
                  f"{one_line(answer.answer_text, 30)}")

    if failed:
        print(f"\n[x] 保存失败（{len(failed)} 道）：")
        for detail in failed:
            print(f"  {detail['question_id']}  {one_line(detail['answer'], 30)}")

    if result is not None and result.message:
        print(f"\n提示：{result.message}")
    if result is not None and not failed and not empty:
        print("\n[OK] 全部题都解出并保存成功。")
