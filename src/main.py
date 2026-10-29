"""程序入口：完整流水线 fetcher → solver → submitter。

一键跑通（默认根据 .env 里的 SOLVER_API_KEY 自动选模式）：
    python -m src.main                 # 自动
    python -m src.main --api           # 强制 API 模式
    python -m src.main --interactive   # 强制交互（手动粘 prompt/JSON）

也可以分步调试：
    python src/fetcher/impl_istudywork.py      # 只抓题
    python src/solver/impl_istudywork.py       # 抓题 + 生成 prompt + 交互解题
    python src/submitter/impl_istudywork.py    # 干跑：只打印 SaveQuestionOne 负载格式
"""
from __future__ import annotations
import argparse
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("autoistudy")


def main() -> int:
    # --- 命令行解析 ---
    parser = argparse.ArgumentParser(description="autoistudy 流水线")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--api", action="store_true", help="强制使用 API 模式")
    mode.add_argument("--interactive", action="store_true", help="强制使用交互模式（手动粘 prompt/JSON）")
    args = parser.parse_args()

    # interactive 参数传给 solver：None=自动, True=交互, False=API
    interactive_arg: bool | None = None
    if args.api:
        interactive_arg = False
    elif args.interactive:
        interactive_arg = True

    # 相对 import 可能因启动方式不同而失败，这里做一层兜底
    try:
        from .fetcher.impl_istudywork import IstudyWorkFetcher
        from .solver.impl_istudywork import IstudyWorkSolver
        from .submitter.impl_istudywork import IstudyWorkSubmitter
    except ImportError:
        import sys as _sys
        from pathlib import Path as _P
        _root = _P(__file__).resolve().parent.parent
        if str(_root) not in _sys.path:
            _sys.path.insert(0, str(_root))
        from src.fetcher.impl_istudywork import IstudyWorkFetcher         # type: ignore
        from src.solver.impl_istudywork import IstudyWorkSolver           # type: ignore
        from src.submitter.impl_istudywork import IstudyWorkSubmitter     # type: ignore

    t0 = time.time()

    # ========== 阶段 1：抓题 ==========
    log.info("=== 阶段 1 / 3  抓题 ===")
    fetcher = IstudyWorkFetcher()
    questions = fetcher.fetch()
    if not questions:
        log.error("没抓到题就走了，检查一下 FETCHER_URL 和 FETCHER_COOKIE")
        return 1
    log.info("✓ 抓到 %d 道题  test_instance_id=%s", len(questions), fetcher.test_instance_id)

    # ========== 阶段 2：AI 解题 ==========
    log.info("=== 阶段 2 / 3  AI 解题 ===")
    solver = IstudyWorkSolver(interactive=interactive_arg)
    mode_label = "交互（手动粘 JSON）" if solver.interactive else "API（自动调 LLM）"
    log.info("solver 模式: %s", mode_label)
    answers = solver.solve_batch(questions)
    log.info("✓ 收到 %d 道题答案", len(answers))

    # ========== 阶段 3：提交 ==========
    log.info("=== 阶段 3 / 3  提交 ===")
    qinfo_map = {q.id: q.raw["qinfo"] for q in questions}
    submitter = IstudyWorkSubmitter()
    result = submitter.submit(answers, qinfo_map=qinfo_map)

    # ========== 报告 ==========
    elapsed = time.time() - t0

    # 三类问题分别统计
    empty_answers = [a for a in answers if not a.answer_text.strip()]
    low_conf_answers = [a for a in answers if 0 < a.confidence < 0.7]
    fail_submit = [d for d in result.details if not d["ok"]]

    total = len(questions)
    good = total - len(empty_answers) - len(fail_submit)

    print()
    print("=" * 60)
    print(f"  流水线完成   耗时 {elapsed:.1f}s")
    print(f"  抓题  {total} 道")
    print(f"  AI解题  漏答/空答案 {len(empty_answers)} 道  低置信度 {len(low_conf_answers)} 道")
    print(f"  提交  成功 {result.submitted_count}/{total}  失败 {len(fail_submit)} 道")
    print(f"  有效 {good}/{total}")
    print("=" * 60)

    if result.message:
        log.info("说明：%s", result.message)

    if empty_answers:
        print(f"\n⚠ AI 漏答 / 空答案（{len(empty_answers)} 道）:")
        for a in empty_answers:
            # 找到对应 qinfo 和题干方便定位
            qinfo = next((q.raw["qinfo"] for q in questions if q.id == a.question_id), "")
            content = next((q.content[:40] for q in questions if q.id == a.question_id), "")
            print(f"  {a.question_id}  {qinfo}  题干: {content}")

    if low_conf_answers:
        print(f"\n⚠ AI 低置信度 confidence<0.7（{len(low_conf_answers)} 道）:")
        for a in low_conf_answers:
            print(f"  {a.question_id}  conf={a.confidence}  answer={a.answer_text[:40]}")

    if fail_submit:
        print(f"\n❌ 保存失败（{len(fail_submit)} 道）:")
        for d in fail_submit:
            print(f"  {d['question_id']}  answer={d['answer'][:40]}")

    if not empty_answers and not low_conf_answers and not fail_submit:
        print("\n✅ 所有题解题 + 保存都成功！")

    return 0 if not fail_submit else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
