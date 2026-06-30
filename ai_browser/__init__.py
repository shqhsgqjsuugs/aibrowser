"""AI 友好的终端浏览器。

基于 Playwright 把网页可访问性树转换为带编号的文本，
让 LLM/用户通过 ``click 3``、``type 2 "hello"`` 这样的指令操作浏览器。
"""
from __future__ import annotations

__version__ = "0.1.0"

__all__ = [
    "AgentSession",
    "BrowserController",
    "extract_page_state",
    "execute_action",
    "LLMClient",
    "run_repl",
    "__version__",
]


# 占位模块尚未实现公开 API，使用 try/except 保证包在骨架阶段可被导入。
# 后续任务实现各模块后会自动覆盖这些占位符号。
try:  # pragma: no cover - 骨架阶段占位
    from .agent import AgentSession
except ImportError:  # pragma: no cover
    AgentSession = None  # type: ignore[assignment]

try:  # pragma: no cover - 骨架阶段占位
    from .browser import BrowserController
except ImportError:  # pragma: no cover
    BrowserController = None  # type: ignore[assignment]

try:  # pragma: no cover - 骨架阶段占位
    from .state import extract_page_state
except ImportError:  # pragma: no cover
    extract_page_state = None  # type: ignore[assignment]

try:  # pragma: no cover - 骨架阶段占位
    from .actions import execute_action
except ImportError:  # pragma: no cover
    execute_action = None  # type: ignore[assignment]

try:  # pragma: no cover - 骨架阶段占位
    from .llm import LLMClient
except ImportError:  # pragma: no cover
    LLMClient = None  # type: ignore[assignment]

try:  # pragma: no cover - 骨架阶段占位
    from .repl import run_repl
except ImportError:  # pragma: no cover
    run_repl = None  # type: ignore[assignment]
