"""交互式 REPL 模块。

提供终端交互入口 :func:`run_repl`，用户可输入与 ActionExecutor 相同语法的指令
操作浏览器，并实时查看页面状态（基于 rich 美化输出）。
"""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .actions import execute_action, parse_action
from .state import extract_page_state
from .types import ActionError, PageState


# 指令帮助文本：控制指令 + 10 条动作指令
HELP_TEXT = """\
[控制指令]
  exit | quit | q       退出 REPL
  help | ?              显示本帮助
  state | refresh       重新提取并显示当前页面状态

[动作指令]（与 ActionExecutor 语法一致）
  click <id>               点击编号元素，例如 click 3
  type <id> "<text>"       在输入框输入文本，例如 type 2 "hello"
  select <id> "<option>"   在下拉框选择选项，例如 select 5 "A"
  check <id>               勾选复选框/单选框
  uncheck <id>             取消勾选复选框
  scroll <up|down>         上下滚动页面
  press <key>              按下按键，例如 press Enter
  navigate <url>           导航到指定 URL
  wait <seconds>           等待指定秒数，例如 wait 1.5
  finish                   结束当前会话
"""


def _print_state(console: Console, state: PageState) -> None:
    """用 rich Panel 打印页面状态。

    正文为 ``state.text``（用 :class:`~rich.text.Text` 包裹，避免页面内容中
    的 ``[...]`` 被 rich 误判为标记），标题为 ``state.title``，边框颜色 cyan。
    """
    console.print(
        Panel(
            Text(state.text),
            title=state.title,
            border_style="cyan",
        )
    )


def run_repl(page, initial_url: str | None = None) -> int:
    """启动交互式 REPL，返回退出码（0 表示正常退出）。

    Parameters
    ----------
    page:
        Playwright 页面对象（鸭子类型：需提供 ``url``、``title()``、
        ``accessibility.snapshot()`` 以及 ActionExecutor 所用到的方法）。
    initial_url:
        若不为 None，启动时先调用 ``page.goto(initial_url, wait_until="load")``。
    """
    console = Console()

    if initial_url is not None:
        page.goto(initial_url, wait_until="load")

    state: PageState | None = None
    refresh = True  # 是否在循环顶部重新提取并打印状态

    while True:
        # a / b. 提取并打印当前状态（仅在 refresh=True 时执行）
        if refresh:
            state = extract_page_state(page)
            _print_state(console, state)
            refresh = False

        # c. 读取用户输入（直接用内置 input 以兼容性；EOFError 视为退出）
        try:
            user_input = input("ai_browser> ")
        except EOFError:
            console.print("再见")
            return 0
        except KeyboardInterrupt:
            # Ctrl+C → 换行后继续（循环顶部重新提取状态）
            console.print()
            refresh = True
            continue

        user_input = user_input.strip()

        # d. 空输入 → 重新显示状态
        if not user_input:
            refresh = True
            continue

        # e. 退出指令
        if user_input in ("exit", "quit", "q"):
            console.print("再见")
            return 0

        # f. 帮助指令（不重新提取状态）
        if user_input in ("help", "?"):
            console.print(Panel(Text(HELP_TEXT), title="帮助", border_style="blue"))
            continue

        # g. 刷新状态指令（循环顶部会重新提取并打印状态）
        if user_input in ("state", "refresh"):
            refresh = True
            continue

        # h. 动作指令
        try:
            action = parse_action(user_input)
            if action.command == "finish":
                console.print("会话结束", style="yellow")
                return 0
            result = execute_action(page, action, state.mapping if state else {})
            console.print(Text.assemble((">> ", "green"), result))
            page.wait_for_load_state("load")
            page.wait_for_timeout(300)
            refresh = True
        except ActionError as e:
            # 解析/执行错误：不重新提取状态，等用户重新输入
            console.print(Text(f"[错误] {e}", style="red"))
            continue
        except KeyboardInterrupt:
            console.print()
            refresh = True
            continue
        except Exception as e:
            # 意外错误：循环回到顶部重新提取状态
            console.print(Text(f"[意外错误] {e}", style="red"))
            continue
