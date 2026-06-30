"""命令行入口模块。

提供顶层 :func:`main` 入口，被 ``pyproject.toml`` 的
``[project.scripts]`` 声明为 ``ai_browser = "ai_browser.cli:main"``。

支持三种模式：
- 直接命令模式（``--exec``）：执行单条或多条命令后退出。
- 命令文件模式（``--file``）：从文件读取命令列表依次执行。
- 交互 REPL 模式（默认）：用户手动输入指令操作浏览器。
- 自动 Agent 模式（``--task``）：LLM 驱动操作浏览器完成任务。
"""
from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .agent import AgentSession
from .browser import BrowserController
from .llm import LLMClient, LLMConfigError
from .repl import run_repl
from .types import MaxStepsExceeded


# 顶层 Console 实例：CLI 各处复用，保证输出风格统一
_console = Console()


def _run_agent(page, task: str, max_steps: int) -> str:
    """运行自动 Agent 模式。

    创建 :class:`LLMClient` 与 :class:`AgentSession`，通过 ``on_step`` 回调
    用 rich 打印每步进度，返回 Agent 的最终结果摘要。

    Args:
        page: Playwright Page 对象。
        task: 用户任务描述。
        max_steps: 最大步数上限。
    Returns:
        Agent 完成时的结果摘要字符串。
    """
    console = _console

    def on_step(step: int, state, action_text: str, result: str) -> None:
        # 步骤分隔标题
        console.print(f"── 步骤 {step} ──────────────────────", style="cyan")
        # 动作：cyan
        console.print(Text.assemble(("动作: ", "bold"), (action_text, "cyan")))
        # 结果：含“错误”字样用 red，否则 green
        result_style = "red" if "错误" in result else "green"
        console.print(Text.assemble(("结果: ", "bold"), (result, result_style)))

    llm_client = LLMClient()
    session = AgentSession(page, llm_client, on_step=on_step)
    return session.run(task, max_steps=max_steps)


def _run_commands(page, commands: list[str], console: Console) -> int:
    """执行命令列表，返回退出码。

    Args:
        page: Playwright Page 对象。
        commands: 命令列表，每条命令格式同 REPL。
        console: Rich Console 实例用于输出。
    Returns:
        0 表示全部成功，1 表示有错误。
    """
    from .actions import execute_action, parse_action
    from .state import extract_page_state

    # 延迟导入避免循环依赖
    has_error = False
    for i, cmd in enumerate(commands, 1):
        cmd = cmd.strip()
        if not cmd:
            continue
        if cmd.lower() in ("exit", "quit", "q", "finish"):
            console.print("[yellow]命令finish，退出执行[/yellow]")
            break

        console.print(f"[cyan]▶ {cmd}[/cyan]")
        try:
            action = parse_action(cmd)
            state = extract_page_state(page)
            result = execute_action(page, action, state.mapping)
            console.print(f"[green]✓ {result}[/green]")
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            has_error = True

    return 1 if has_error else 0


def main(argv=None) -> int:
    """命令行入口，返回退出码。

    Args:
        argv: 参数列表，便于测试；为 None 时取 ``sys.argv[1:]`` 。
    Returns:
        进程退出码（0 正常 / 1 错误 / 2 配置错误 / 130 中断）。
    """
    parser = argparse.ArgumentParser(
        prog="ai_browser",
        description="AI 友好的终端浏览器：通过指令或 LLM Agent 操作浏览器。",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="启动时打开的初始页面 URL",
    )
    parser.add_argument(
        "--task",
        default=None,
        help="进入自动 Agent 模式，执行描述的任务",
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="显示浏览器窗口（默认无头模式运行）",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=50,
        help="自动模式最大步数（默认 50）",
    )
    parser.add_argument(
        "-e", "--exec",
        action="append",
        default=None,
        dest="commands",
        help="执行一条命令（可多次使用）",
    )
    parser.add_argument(
        "-f", "--file",
        default=None,
        help="从文件读取命令列表执行（每行一条命令）",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="启用 TUI 仪表盘模式（可视化监控/交互）",
    )

    args = parser.parse_args(argv)

    # 收集所有命令
    commands = []
    if args.commands:
        commands.extend(args.commands)
    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                commands.extend(f.read().splitlines())
        except Exception as e:
            _console.print(f"[red]无法读取命令文件: {e}[/red]")
            return 1

    # 自动模式依赖 LLM；未配置 OPENAI_API_KEY 时直接报错退出，避免启动浏览器
    if args.task and not LLMClient().is_configured:
        _console.print(
            "未配置 OPENAI_API_KEY，无法使用自动模式。请设置环境变量"
            "或在交互模式（不带 --task）下使用。",
            style="red",
        )
        return 2

    # 检查是否有管道输入的命令
    if not commands and not sys.stdin.isatty():
        commands = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]

    try:
        with BrowserController(headless=not args.visible) as bc:
            if args.url:
                bc.navigate(args.url)

            # TUI 模式
            if args.tui:
                from .tui import run_tui_agent, run_tui_interactive
                if args.task:
                    result = run_tui_agent(bc.page, args.task, args.max_steps)
                    _console.print(
                        Panel(Text(result), title="任务结果", border_style="green")
                    )
                    return 0
                else:
                    return run_tui_interactive(bc.page, initial_url=args.url)

            # 优先处理 Agent 模式
            if args.task:
                result = _run_agent(bc.page, args.task, args.max_steps)
                _console.print(
                    Panel(Text(result), title="任务结果", border_style="green")
                )
                return 0

            # 命令执行模式
            if commands:
                return _run_commands(bc.page, commands, _console)

            # 交互 REPL 模式：返回其退出码
            return run_repl(bc.page, initial_url=args.url)
    except MaxStepsExceeded as e:
        _console.print(f"[警告] {e}", style="yellow")
        return 1
    except LLMConfigError as e:
        _console.print(f"[配置错误] {e}", style="red")
        return 2
    except KeyboardInterrupt:
        print("\n已中断")
        return 130
    except Exception as e:
        _console.print(f"[错误] {e}", style="red")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
