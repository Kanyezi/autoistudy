# autoistudy

把 zjcai.com（istudyWork）上的 Python 作业自动答掉：抓题 → AI 解题 → 逐题保存答案。

## 结构

```
main.py              # 装配脚本：抓题 → 解题 → 提交，直接读，直接改
autoistudy/
  core.py            # Question / Answer / Settings + HTTP 会话
  fetch.py           # 解析试卷首页与单题（纯函数，可离线测试）
  solve.py           # 拼 prompt、调 LLM、解析 JSON
  submit.py          # 答案编码 + POST SaveQuestionOne
  report.py          # 终端报告
tests/
  test_parse.py      # 固定 HTML 解析测试
  test_submit.py     # 编码与提交载荷测试
  test_solve.py      # prompt 与回复解析测试
  test_report.py     # 报告输出测试
```

`main.py` 没有 `main()` 函数和命令行参数，也不在 `__main__` 守卫里包一层——它就是一份从上到下的装配图，想调节哪一步就直接改哪几行。

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env        # 填 FETCHER_URL / FETCHER_COOKIE / SOLVER_API_KEY
python main.py
```

两个开关在 `main.py` 开头：

```python
LIMIT = 0          # 只处理前 N 道题，调试时设 3、5 很快
DO_SUBMIT = True   # 改成 False 就只抓题+解题并打印答案，不提交
```

第一次跑建议 `DO_SUBMIT = False`，确认答案像样再打开提交。

## 配置（.env）

| 键 | 含义 |
|---|---|
| `FETCHER_URL` | 试卷页地址，如 `https://www.zjcai.com/GoTest/TestOne/101958` |
| `FETCHER_COOKIE` | 浏览器里登录后的 Cookie（会过期，过期后重新复制） |
| `SOLVER_API_KEY` / `SOLVER_BASE_URL` / `SOLVER_MODEL` | OpenAI 兼容的模型配置 |
| `SUBMIT_COOKIE` | 可选，提交用不同 Cookie 时才填 |
| `SUBMIT_INTERVAL` | 每题保存间隔秒数，默认 1.0 |

## 测试

```bash
python -m pytest -q                 # 全部离线测试，秒级
```

## 已知限制

- **只保存、不交卷**：`SaveQuestionOne` 是逐题保存，整体交卷（`submitTest`）还没对接，答完要在网页点【提交作业】。
- Cookie 过期后首页解析不到题目，程序直接报错退出，不会瞎提交。
- 只支持 zjcai.com / istudyWork 一个平台，没有多平台抽象。
- `main.py` 是脚本，`import main` 会直接把整条流水线跑起来。
