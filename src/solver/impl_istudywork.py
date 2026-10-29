"""AI 解题器实现：整包 prompt，支持交互输入或 API 自动。

两种模式（构造时传 interactive=... 或看 API Key 自动选）：
  交互模式 interactive=True  ：把 prompt 写到 prompt.txt，等用户复制给豆包/通义/Claude，
                                 再把 AI 返回的 JSON 粘回来解析。**不需要 API Key**。
  自动模式 interactive=False  ：用 OpenAI SDK 直接调 LLM API（需要 .env 配好）。

默认 interactive=None 表示：有 API Key 走自动，没有就交互。
"""
from __future__ import annotations
import json
import logging
import re
import sys
from pathlib import Path
from typing import List, Optional

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from .base import BaseSolver
    from ..config.settings import settings
    from ..models.schema import Question, QuestionType, Answer
except ImportError:
    import sys as _sys
    from pathlib import Path as _P
    _root = _P(__file__).resolve().parent.parent.parent
    if str(_root) not in _sys.path:
        _sys.path.insert(0, str(_root))
    from src.solver.base import BaseSolver                     # type: ignore  # noqa: E402
    from src.config.settings import settings                   # type: ignore  # noqa: E402
    from src.models.schema import Question, QuestionType, Answer  # type: ignore  # noqa: E402

log = logging.getLogger(__name__)


# ============================================================
#   提示词模板（与对话 AI 友好的写法）
# ============================================================

SYSTEM_PROMPT = """你是一名 Python 编程辅导老师，正在为一份课堂作业给出正确答案。

【你的任务】
仔细阅读下面这份试卷，对每一道题给出**精准**答案。

【题型 → 答案格式】（严格遵守，这是机器能识别的结构）
  1. 单项选择题 single_choice
     → answer_text 写一个字母：A / B / C / D / E
  2. 判断题 judge
     → answer_text 写一个字母：A（代表"对"）或 B（代表"错"）
     （虽然选项文本是"对/错"，但平台内部用 A/B 作为 value）
  3. 多选题 multi_choice
     → answer_text 写 JSON 数组字符串：["A","C"]；只选一个也必须是数组
  4. 填空题 fill_blank
     → answer_text 写 JSON 数组字符串：["第1空","第2空"]；只有一个空也用 ["..."]
  5. 编程题 / 简答题 short_answer
     → answer_text 写完整的 Python 代码块或答案文本（多行原样保留）

【执行契约】
  - 只输出最终答案，不要写出推理过程（reasoning 字段可为空字符串）
  - 不确定时 confidence 写低于 0.7；有十足把握写 0.9~1.0
  - 禁止编造题目；如果题干本身看不懂，confidence 填 0.0，answer_text 填 ""
  - 编程题代码必须能直接运行；填空题内容不要加多余的引号或括号

【输出格式】
必须输出一个 JSON 对象，key 是每题的 question_id（即题目编号字符串），value 是一个包含以下字段的对象：
  - answer_text: 如上所述格式的答案字符串（必填）
  - confidence: 0~1 的浮点数（必填）
  - reasoning: 简短说明或 ""（可选）

示例（仅演示格式）：
{
  "61045435": {"answer_text": "B", "confidence": 0.95, "reasoning": "小于等于运算符"},
  "61045470": {"answer_text": "A", "confidence": 0.9,  "reasoning": "bool(0) 结果是 False"},
  "61045490": {"answer_text": "s = 0.0\\nfor i in range(1, 101):\\n    if i % 2 == 0:\\n        s += i\\nprint(f'{s:.2f}')", "confidence": 0.85}
}
"""

USER_PROMPT_HEADER = """
======================== 试卷开始 ========================

试卷标题：{title}
共 {total} 道题，题型分布：{dist}

----------------------------------------------------------
"""

USER_PROMPT_FOOTER = """
======================== 试卷结束 ========================

请立即输出 JSON。不要先写任何分析、解题过程或 Markdown 代码块标记，
只输出纯 JSON 对象，并用换行缩进保证可读性。再次强调：
  - 每题都要有 key，哪怕 confidence=0 也要给出空 answer_text
  - 不要漏题、不要新增题目、不要修改题目 id
  - 不要解释、不要道歉、不要使用 ```json 包裹
"""


# ============================================================
#   Solver 实现
# ============================================================

class IstudyWorkSolver(BaseSolver):
    """整包解题器：交互优先，API 自动兜底。"""

    def __init__(self, interactive: Optional[bool] = None, **kwargs):
        super().__init__(**kwargs)
        cfg = settings.solver
        self.api_key   = cfg.api_key
        self.base_url  = cfg.base_url
        self.model     = cfg.model
        self.max_tokens = cfg.max_tokens
        self.temperature = cfg.temperature
        self.batch_size = 999   # 不分批，一次全给 LLM

        # 模式：显式传 interactive 优先；否则有 API Key → API 模式，无 → 交互
        if interactive is None:
            self.interactive = not self.api_key
        else:
            self.interactive = interactive

    # -------------------------------------------------------------
    def _format_question(self, q: Question, index: int) -> str:
        """把单道题格式化成人类可读的文本块。"""
        lines = [f"[{q.id}] {q.type.value}（第{index}题，{q.score or '?'}分）"]
        lines.append("_" * 50)
        for ln in q.content.strip().splitlines() or ["(无题干)"]:
            lines.append(ln)
        if q.options:
            lines.append("")
            for op in q.options:
                lines.append(f"  • {op}")
        lines.append("")
        return "\n".join(lines)

    # -------------------------------------------------------------
    def _build_prompt(self, questions: List[Question], title: str = "Python 编程作业") -> tuple[str, str]:
        from collections import Counter

        type_counts = Counter(q.type.value for q in questions)
        dist = "、".join(f"{v}×{k}" for k, v in type_counts.items())

        _type_order = [
            QuestionType.SINGLE_CHOICE,
            QuestionType.JUDGE,
            QuestionType.MULTI_CHOICE,
            QuestionType.FILL_BLANK,
            QuestionType.SHORT_ANSWER,
        ]
        sorted_qs = sorted(
            enumerate(questions, 1),
            key=lambda item: (_type_order.index(item[1].type), item[0]),
        )

        header = USER_PROMPT_HEADER.format(title=title, total=len(questions), dist=dist)
        blocks = [self._format_question(q, idx) for idx, q in sorted_qs]
        user_prompt = header + "\n".join(blocks) + USER_PROMPT_FOOTER
        return SYSTEM_PROMPT, user_prompt

    # -------------------------------------------------------------
    #  输出 / 输入（交互模式）
    # -------------------------------------------------------------

    PROMPT_FILE = "solver_prompt.txt"
    RESPONSE_FILE = "solver_response.json"

    def dump_prompt(
        self,
        questions: List[Question],
        out_path: Optional[str] = None,
        title: str = "Python 编程作业",
    ) -> str:
        """把 prompt 写到文件，返回文件路径（方便用户打开复制）。"""
        system_prompt, user_prompt = self._build_prompt(questions, title=title)
        out_path = out_path or self.PROMPT_FILE

        content = (
            "【把下面这两段一起发给对话 AI】\n\n"
            "────────────── SYSTEM ──────────────\n"
            f"{system_prompt}\n"
            "────────────── USER  ──────────────\n"
            f"{user_prompt}\n"
        )
        Path(out_path).write_text(content, encoding="utf-8")
        log.info("prompt 已写入 %s（%d 字符）", out_path, len(content))
        return out_path

    def collect_response(
        self,
        response_path: Optional[str] = None,
        interactive: bool = True,
    ) -> str:
        """从终端 stdin 读 AI 返回，或从已有文件读取。

        interactive=True  ：提示用户粘贴、以单独一行 END 结束
        interactive=False  ：直接读 response_path（测试用）
        """
        if not interactive:
            text = Path(response_path or self.RESPONSE_FILE).read_text(encoding="utf-8")
            log.info("从文件读取 AI 回复 %s（%d 字符）", response_path, len(text))
            return text

        print()
        print("=" * 60)
        print("  请把对话 AI 返回的 JSON 粘贴到这里")
        print("  粘完后单独输入一行 END 再回车")
        print("=" * 60)
        buf: List[str] = []
        for line in sys.stdin:
            stripped = line.strip()
            if stripped == "END":
                break
            buf.append(line)
        text = "".join(buf).strip()
        log.info("收到 AI 回复 %d 字符", len(text))
        return text

    # -------------------------------------------------------------
    #  API 自动模式
    # -------------------------------------------------------------

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """最简 API 调用：一段 OpenAI SDK 搞定。"""
        import os
        from openai import OpenAI

        # 构造函数里已经配好 api_key / base_url / model，这里直接用
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        log.info("调用 LLM model=%s  prompt 约 %d 字符", self.model, len(user_prompt))

        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=False,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        content = resp.choices[0].message.content or ""
        log.info("LLM 返回 %d 字符", len(content))
        return content

    # -------------------------------------------------------------
    #  解析 + 映射
    # -------------------------------------------------------------

    @staticmethod
    def _extract_json(text: str) -> dict:
        """从 AI 回复里抠 JSON 块（可能带 ```json 包裹或前后夹杂）。

        容错：
          1. 先用 find("{")/rfind("}") 切出疑似 JSON 段
          2. 如果直接 loads 失败，尝试修复字符串值里的裸换行（编程题代码常见）
          3. 再失败则用 Python 原生 ast.literal_eval 兜底（如果是单引号 JSON）
        """
        cleaned = re.sub(r"```(?:json)?\s*", "", text).strip()
        first = cleaned.find("{")
        last = cleaned.rfind("}")
        if first >= 0 and last > first:
            cleaned = cleaned[first:last + 1]

        # 1) 直接 parse
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 2) 修复字符串值里的裸换行 / 回车（LLM 常把编程题代码里的真实 \n 塞进 JSON 字符串）
        fixed = IstudyWorkSolver._fix_json_string_newlines(cleaned)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError as e2:
            log.warning("JSON 修复后仍失败：%s\n前 300 字符:\n%s", e2, fixed[:300])
            raise

    @staticmethod
    def _fix_json_string_newlines(s: str) -> str:
        """把 JSON 字符串值内部的裸换行 / 制表符转义掉。

        扫描器：遇到 '"' 进入字符串模式，模式内把 '\n' → '\\n', '\r' → '\\r', '\t' → '\\t'。
        注意：跳过已转义的 \"（即 \" 不计入字符串结束）。
        """
        out: list[str] = []
        i = 0
        in_string = False
        n = len(s)
        while i < n:
            ch = s[i]
            if not in_string:
                if ch == '"':
                    in_string = True
                    out.append(ch)
                else:
                    out.append(ch)
                i += 1
            else:
                # 在字符串里：先处理转义符
                if ch == "\\" and i + 1 < n:
                    # 已转义的字符原样保留（包括 \\ 和 \" 和已转义的 \n）
                    out.append(ch)
                    out.append(s[i + 1])
                    i += 2
                    continue
                if ch == '"':
                    in_string = False
                    out.append(ch)
                elif ch == "\n":
                    out.append("\\n")
                elif ch == "\r":
                    out.append("\\r")
                elif ch == "\t":
                    out.append("\\t")
                else:
                    out.append(ch)
                i += 1
        return "".join(out)

    def _parse_response(self, raw: str, questions: List[Question]) -> List[Answer]:
        data = self._extract_json(raw)
        answer_map: dict[str, Answer] = {}
        empty_ans: List[str] = []   # 漏答 / 空答案的题目 id
        low_conf: List[str] = []    # 低置信度的题目 id
        for q in questions:
            if q.id in data:
                entry = data[q.id]
                if isinstance(entry, dict):
                    ans_text = str(entry.get("answer_text", ""))
                    conf = float(entry.get("confidence", 0.0) or 0.0)
                    reasoning = str(entry.get("reasoning", "") or "")
                else:
                    ans_text = str(entry)
                    conf = 0.9
                    reasoning = ""
            else:
                # AI 完全漏掉这道题
                ans_text = ""
                conf = 0.0
                reasoning = ""
                empty_ans.append(q.id)

            if not ans_text.strip() and q.id not in empty_ans:
                empty_ans.append(q.id)
            elif 0 < conf < 0.7:
                low_conf.append(q.id)

            answer_map[q.id] = Answer(
                question_id=q.id,
                answer_text=ans_text,
                confidence=conf,
                reasoning=reasoning,
            )

        if empty_ans:
            log.warning("AI 漏答 / 空答案 %d 道：%s", len(empty_ans), empty_ans)
        if low_conf:
            log.warning("AI 低置信度 %d 道（confidence<0.7）：%s", len(low_conf), low_conf)

        return [answer_map[q.id] for q in questions]

    # -------------------------------------------------------------
    #  对外主入口
    # -------------------------------------------------------------

    def solve_batch(
        self,
        questions: List[Question],
        title: str = "Python 编程作业",
    ) -> List[Answer]:
        """整包解题：自动判定交互 / API 模式。"""
        if not questions:
            return []

        if len(questions) <= self.batch_size:
            return self._solve_once(questions, title=title)

        # 分批处理
        all_answers: List[Answer] = []
        seen_ids: set[str] = set()
        for offset in range(0, len(questions), self.batch_size):
            batch = questions[offset:offset + self.batch_size]
            log.info("分批解题 [%d~%d]/%d", offset, offset + len(batch) - 1, len(questions))
            answers = self._solve_once(batch, title=f"{title}(批次 {offset // self.batch_size + 1})")
            for ans in answers:
                if ans.question_id not in seen_ids:
                    seen_ids.add(ans.question_id)
                    all_answers.append(ans)
        return all_answers

    def _solve_once(self, questions: List[Question], title: str) -> List[Answer]:
        system_prompt, user_prompt = self._build_prompt(questions, title=title)

        if self.interactive:
            path = self.dump_prompt(questions, title=title)
            print(f"\n📝 已生成 prompt 文件：{Path(path).resolve()}")
            print("   打开它，把两段内容一起发给对话 AI（豆包/通义/Claude/...）")
            print("   拿到 AI 返回的 JSON 后，回到本脚本粘贴")
            raw = self.collect_response(interactive=True)
        else:
            raw = self._call_llm(system_prompt, user_prompt)

        return self._parse_response(raw, questions)

    def solve(self, question: Question) -> Answer:
        return self.solve_batch([question])[0]


# ============================================================
#   直接运行：完整交互流程
#   python src/solver/impl_istudywork.py
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from src.fetcher.impl_istudywork import IstudyWorkFetcher

    fetcher = IstudyWorkFetcher()
    questions = fetcher.fetch()
    solver = IstudyWorkSolver()

    print(f"\n抓到 {len(questions)} 道题，开始解题流程...")
    print(f"solver 模式 = {'交互（无 API Key）' if solver.interactive else '自动（调用 LLM API）'}")

    answers = solver.solve_batch(questions)

    print(f"\n✓ 收到 {len(answers)} 道题答案")
    print("=" * 60)
    for a in answers[:5]:
        print(f"  {a.question_id}: {a.answer_text[:40]:40s}  conf={a.confidence}")
    print("  ...")
    print("=" * 60)
    print("接下来可以把 answers 交给 submitter，或手动检查。")
