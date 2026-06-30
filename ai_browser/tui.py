"""TUI 监控面板模块。

提供基于 rich 的终端仪表盘，实时展示 AI Agent 执行状态、
动作日志和页面元素，支持交互操作。

用法：
  ai_browser --tui                         # 交互式 TUI 仪表盘
  ai_browser --tui --task "搜索世界杯"      # Agent 监控仪表盘
  ai_browser --tui --url https://baidu.com  # 打开页面后进入 TUI
"""
from __future__ import annotations

import msvcrt
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .actions import execute_action, parse_action
from .state import extract_page_state
from .types import ActionError

# Windows 终端 UTF-8 兼容
if os.name == "nt":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        import sys
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ── 数据结构 ──────────────────────────────────────────────────

@dataclass
class StepLog:
    """单步执行日志。"""
    step: int
    action: str
    result: str = ""
    status: str = "running"  # running / success / error


@dataclass
class MonitorState:
    """TUI 共享状态（线程安全）。"""
    status: str = "空闲"
    url: str = ""
    title: str = ""
    current_step: int = 0
    max_steps: int = 50
    logs: list = field(default_factory=list)
    page_mapping: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add_log(self, step: int, action: str, **kw):
        with self._lock:
            self.logs.append(StepLog(step=step, action=action, **kw))
            self.current_step = step

    def update_log_result(self, step: int, result: str, status: str):
        with self._lock:
            for log in reversed(self.logs):
                if log.step == step and log.status == "running":
                    log.result = result
                    log.status = status
                    break

    def refresh_page(self, page):
        with self._lock:
            try:
                ps = extract_page_state(page)
                self.url = page.url
                self.title = page.title() or ""
                self.page_mapping = dict(ps.mapping)
            except Exception:
                pass


# ── 渲染组件 ──────────────────────────────────────────────────

def _header_panel(state: MonitorState) -> Panel:
    """顶部状态栏。"""
    colors = {
        "空闲": "dim", "运行中": "bold green",
        "已完成": "bold cyan", "已暂停": "bold yellow",
    }
    parts = [
        ("状态: ", "bold"), (state.status, colors.get(state.status, "white")),
        ("  |  ", "dim"),
        ("步骤: ", "bold"), (f"{state.current_step}/{state.max_steps}", "cyan"),
        ("  |  ", "dim"),
        ("URL: ", "bold"), (state.url[:55], "blue"),
        ("  |  ", "dim"),
        ("标题: ", "bold"), (state.title[:25], "white"),
    ]
    return Panel(Text.assemble(*parts), title="AI Browser", border_style="cyan", height=3)


def _log_panel(state: MonitorState) -> Panel:
    """执行日志面板。"""
    with state._lock:
        logs = list(state.logs)

    if not logs:
        return Panel(Text("等待执行...", style="dim"),
                     title="执行日志", border_style="green")

    lines = []
    for log in logs[-18:]:
        t = Text()
        t.append(f"[{log.step}] ", style="bold cyan")
        t.append(log.action, style="white")
        if log.status == "running":
            t.append(" ...", style="yellow")
        elif log.status == "success":
            t.append(f"\n    >> {log.result}", style="green")
        else:
            t.append(f"\n    !! {log.result}", style="bold red")
        lines.append(t)

    return Panel(Group(*lines), title="执行日志", border_style="green")


def _elements_panel(state: MonitorState) -> Panel:
    """页面元素面板。"""
    with state._lock:
        mapping = dict(state.page_mapping)

    if not mapping:
        return Panel(Text("无页面元素", style="dim"),
                     title="页面元素", border_style="blue")

    table = Table(show_header=True, expand=True, padding=0, show_lines=False)
    table.add_column("#", style="bold cyan", width=4, justify="right")
    table.add_column("角色", style="yellow", width=10)
    table.add_column("名称/值", style="white")

    for idx in sorted(mapping.keys()):
        node = mapping[idx]
        name = node.name or ""
        if node.value:
            name += f" ({node.value})"
        if len(name) > 45:
            name = name[:42] + "..."
        table.add_row(str(idx), node.role, name)

    return Panel(table, title=f"页面元素 ({len(mapping)})",
                 border_style="blue")


def _build_layout(state: MonitorState, footer: Panel) -> Layout:
    """组装完整 TUI 布局。"""
    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="body", ratio=1),
        Layout(name="footer", size=3),
    )
    layout["body"].split_row(
        Layout(name="log", ratio=3),
        Layout(name="elements", ratio=2),
    )
    layout["header"].update(_header_panel(state))
    layout["log"].update(_log_panel(state))
    layout["elements"].update(_elements_panel(state))
    layout["footer"].update(footer)
    return layout


# ── Agent 监控模式 ─────────────────────────────────────────────

def run_tui_agent(page, task: str, max_steps: int) -> str:
    """TUI 监控模式运行 Agent。

    主线程渲染 Live 仪表盘，Agent 在后台线程执行。
    支持快捷键：Q 退出、P 暂停/继续、R 刷新页面状态。
    """
    from .agent import AgentSession
    from .llm import LLMClient

    state = MonitorState(max_steps=max_steps)
    state.refresh_page(page)
    result_box: dict = {"value": ""}
    pause_event = threading.Event()
    pause_event.set()  # 默认不暂停

    def on_step(step, ps, action_text, result):
        state.add_log(step, action_text)
        pause_event.wait()  # 暂停时阻塞
        status = "error" if "错误" in result else "success"
        state.update_log_result(step, result, status)
        state.refresh_page(page)

    def agent_worker():
        try:
            state.status = "运行中"
            llm = LLMClient()
            session = AgentSession(page, llm, on_step=on_step)
            result_box["value"] = session.run(task, max_steps=max_steps)
            state.status = "已完成"
        except Exception as e:
            result_box["value"] = f"错误: {e}"
            state.status = "已完成"

    t = threading.Thread(target=agent_worker, daemon=True)
    t.start()

    help_bar = Panel(
        Text.assemble(
            ("快捷键: ", "bold"),
            ("[Q]退出 ", "cyan"),
            ("[P]暂停/继续 ", "cyan"),
            ("[R]刷新 ", "cyan"),
        ),
        border_style="dim", height=3,
    )

    console = Console()
    with Live(console=console, refresh_per_second=4, screen=True) as live:
        while t.is_alive():
            live.update(_build_layout(state, help_bar))
            if msvcrt.kbhit():
                ch = msvcrt.getch().lower()
                if ch == b"q":
                    state.status = "已暂停"
                    break
                elif ch == b"p":
                    if pause_event.is_set():
                        pause_event.clear()
                        state.status = "已暂停"
                    else:
                        pause_event.set()
                        state.status = "运行中"
                elif ch == b"r":
                    state.refresh_page(page)
            time.sleep(0.05)

        # 最终渲染
        live.update(_build_layout(state, help_bar))

    t.join(timeout=5)
    return result_box["value"]


# ── 交互式 TUI 模式 ─────────────────────────────────────────────

def run_tui_interactive(page, initial_url: str | None = None) -> int:
    """交互式 TUI 仪表盘。

    每次输入命令前刷新仪表盘，提供直观的页面状态和操作历史。
    支持所有 REPL 指令，以及额外控制：
      state  - 刷新页面状态
      clear  - 清除日志
      help   - 显示帮助
      q      - 退出
    """
    console = Console()

    if initial_url:
        page.goto(initial_url, wait_until="load")

    state = MonitorState()
    state.refresh_page(page)
    step_counter = 0

    while True:
        state.refresh_page(page)

        # 渲染仪表盘
        console.clear()
        footer = Panel(
            Text.assemble(
                ("输入命令操作浏览器 | ", "bold"),
                ("help=帮助  q=退出  clear=清除日志", "cyan"),
            ),
            border_style="dim", height=3,
        )
        console.print(_build_layout(state, footer))

        # 读取命令
        try:
            cmd = console.input("[bold cyan]命令>[/bold cyan] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n再见")
            return 0

        cmd = cmd.strip()
        if not cmd:
            continue

        # 控制指令
        if cmd.lower() in ("q", "quit", "exit"):
            console.print("再见")
            return 0
        if cmd.lower() in ("help", "?"):
            from .repl import HELP_TEXT
            console.print(Panel(HELP_TEXT, title="帮助", border_style="yellow"))
            console.input("[dim]按回车继续...[/dim]")
            continue
        if cmd.lower() == "clear":
            with state._lock:
                state.logs.clear()
            continue
        if cmd.lower() == "state":
            state.refresh_page(page)
            continue

        # 执行动作指令
        step_counter += 1
        state.status = "运行中"
        try:
            action = parse_action(cmd)
            if action.command == "finish":
                console.print("会话结束", style="yellow")
                return 0
            ps = extract_page_state(page)
            result = execute_action(page, action, ps.mapping)
            state.add_log(step_counter, cmd, result=result, status="success")
        except ActionError as e:
            state.add_log(step_counter, cmd, result=str(e), status="error")
        except Exception as e:
            state.add_log(step_counter, cmd, result=str(e), status="error")
        state.status = "空闲"
