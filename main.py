"""autoistudy 入口：把抓题、解题、提交三块拼成一条完整流水线。

这里故意不写函数、不做命令行解析 —— 这份文件就是装配图，想改行为直接改：

    LIMIT        只处理前 N 道题（0 = 全部），调试时很省时间
    DO_SUBMIT    False = 只抓题 + 解题并打印答案，不往平台提交

运行：python main.py

注意：SaveQuestionOne 只保存单题答案，整体交卷要在网页点【提交作业】。
"""
from __future__ import annotations

import logging
import sys

from autoistudy.core import load_settings, make_session
from autoistudy.fetch import fetch_questions
from autoistudy.report import print_answers, print_report
from autoistudy.solve import solve_questions
from autoistudy.submit import submit_answers

LIMIT = 0
DO_SUBMIT = True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("autoistudy")
# 中文 Windows 控制台是 GBK，答案里混进表情符号时别崩在 print 上
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

settings = load_settings()
if not settings.testone_url:
    sys.exit("未配置 FETCHER_URL，请在 .env 中填写试卷地址")
if not settings.api_key:
    sys.exit("未配置 SOLVER_API_KEY，请在 .env 中填写模型 API Key")

session = make_session(settings.cookie)   # 抓题和保存共用同一个会话（同一份 Cookie）

# ---------- 1/3 抓题 ----------
log.info("=== 1/3 抓题 ===")
fetched = fetch_questions(settings, session=session, limit=LIMIT)
questions = fetched.questions
if not questions:
    sys.exit("没抓到题：检查 FETCHER_URL 和 FETCHER_COOKIE 是否过期")
log.info("[OK] 抓到 %d 道题  test_instance_id=%s", len(questions), fetched.test_instance_id or "?")

# ---------- 2/3 解题 ----------
log.info("=== 2/3 AI 解题 ===")
answers = solve_questions(settings, questions)
log.info("[OK] 有答案 %d/%d 道", sum(1 for a in answers if a.answer_text.strip()), len(answers))

if not DO_SUBMIT:
    print_answers(questions, answers)
    print_report(questions, answers)
    sys.exit(0)

# ---------- 3/3 提交 ----------
log.info("=== 3/3 保存答案 ===")
result = submit_answers(settings, answers, questions, session=session)
print_report(questions, answers, result)

# 有题没保存成功就以非 0 退出，方便脚本里判断
sys.exit(0 if result.saved == result.total else 1)
