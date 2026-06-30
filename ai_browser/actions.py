"""动作解析与执行模块。

将 LLM/用户输出的文本指令解析为结构化 :class:`Action`，
并基于 ``{编号 -> NodeInfo}`` 映射在 Playwright 页面上精准执行。
"""
from __future__ import annotations

import re
from typing import Any

from ai_browser.types import Action, NodeInfo, ActionError


# 常见特殊键名（小写形式），用于规范化按键指令。
# 单字符按键（如 "a"）保持原样；这些多字符键名会做 title() 规范化。
_COMMON_KEYS = {
    "enter", "escape", "tab", "backspace",
    "arrowdown", "arrowup", "arrowleft", "arrowright",
    "home", "end", "delete", "insert",
    "pagedown", "pageup",
    "control", "alt", "shift", "meta",
    "space", "capslock",
}


def _extract_command_line(text: str) -> str:
    """从 LLM 输出中提取指令行。

    规则：取第一个非空行；若该行包含 ``---`` 或 ``//`` 分隔符
    （需前面带空格，避免误伤 URL 中的 ``//`` 或带 ``---`` 的文本），
    取分隔符之前部分。最后去除首尾空白。
    """
    if not text:
        return ""
    line = ""
    for raw_line in text.splitlines():
        if raw_line.strip():
            line = raw_line
            break
    # 分隔符需前面带空格，避免误伤 URL 中的 `//` 或带 `---` 的文本
    line = re.split(r"\s+(?://|---)", line, maxsplit=1)[0]
    return line.strip()


def _parse_quoted_or_rest(rest: str) -> str:
    """从 id 之后的字符串中提取文本参数。

    若用双引号包裹，取引号内内容；否则取整段（去除首尾空格）。
    """
    s = rest.strip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s


def parse_action(text: str) -> Action:
    """将 LLM/用户文本解析为 :class:`Action`。

    支持指令：``click/type/select/check/uncheck/scroll/press/navigate/wait/finish``。
    命令名大小写不敏感，参数区分大小写。解析失败抛 :class:`ActionError`。
    """
    raw_text = text or ""
    line = _extract_command_line(raw_text)
    if not line:
        raise ActionError(f"无法解析指令: {text!r}")

    m = re.match(r"^(\S+)\s*(.*)$", line)
    if not m:
        raise ActionError(f"无法解析指令: {text!r}")
    cmd = m.group(1).lower()
    rest = m.group(2).strip()

    try:
        if cmd == "click":
            return Action(command="click", args=[int(rest)], raw=raw_text)
        if cmd == "type":
            m2 = re.match(r"^(\d+)\s+(.*)$", rest, re.DOTALL)
            if not m2:
                raise ValueError("type 需要 id 和文本")
            return Action(
                command="type",
                args=[int(m2.group(1)), _parse_quoted_or_rest(m2.group(2))],
                raw=raw_text,
            )
        if cmd == "select":
            m2 = re.match(r"^(\d+)\s+(.*)$", rest, re.DOTALL)
            if not m2:
                raise ValueError("select 需要 id 和选项")
            return Action(
                command="select",
                args=[int(m2.group(1)), _parse_quoted_or_rest(m2.group(2))],
                raw=raw_text,
            )
        if cmd == "check":
            return Action(command="check", args=[int(rest)], raw=raw_text)
        if cmd == "uncheck":
            return Action(command="uncheck", args=[int(rest)], raw=raw_text)
        if cmd == "scroll":
            return Action(command="scroll", args=[rest], raw=raw_text)
        if cmd == "press":
            return Action(command="press", args=[rest], raw=raw_text)
        if cmd == "navigate":
            return Action(command="navigate", args=[rest], raw=raw_text)
        if cmd == "wait":
            return Action(command="wait", args=[float(rest)], raw=raw_text)
        if cmd == "finish":
            return Action(command="finish", args=[], raw=raw_text)
        raise ActionError(f"无法解析指令: {text!r}")
    except ActionError:
        raise
    except Exception as e:
        raise ActionError(f"无法解析指令: {text!r}") from e


def _locate(page: Any, node: NodeInfo):
    """根据 :class:`NodeInfo` 在页面上定位元素，按优先级回退。

    优先级：
    1. ``get_by_role(role, name=name, exact=True)`` —— name 非空时
    2. 若匹配多个，取 ``.nth(index)``
    3. name 为空或上面无匹配：``get_by_role(role).nth(index)``
    4. 回退：``get_by_label(name)``
    5. 最终回退：``locator('text="name"')``
    """
    name = node.name
    if name:
        loc = page.get_by_role(node.role, name=name, exact=True)
        try:
            count = loc.count()
        except Exception:
            count = 1
        if count > node.index:
            return loc.nth(node.index)
        if count > 0:
            return loc.first
    # name 为空或上面失败
    try:
        loc2 = page.get_by_role(node.role)
        if loc2.count() > node.index:
            return loc2.nth(node.index)
    except Exception:
        pass
    if name:
        try:
            return page.get_by_label(name)
        except Exception:
            return page.locator(f'text="{name}"')
    raise ActionError(f"无法定位元素: role={node.role!r} name={name!r}")


def _normalize_key(key: str) -> str:
    """规范化按键名称：单字符保持；常见键名做 title() 处理。"""
    key = key.strip()
    if not key:
        return key
    if len(key) == 1:
        return key
    if key.lower() in _COMMON_KEYS:
        return key.title()
    return key


def execute_action(page: Any, action: Action, mapping: dict) -> str:
    """执行 :class:`Action`，返回结果描述字符串（用于历史记录）。

    元素操作失败（Playwright 抛错）会被捕获并包装为 :class:`ActionError`，
    不让原始异常冒泡。
    """
    cmd = action.command
    try:
        if cmd == "click":
            node_id = action.args[0]
            node = mapping.get(node_id)
            if node is None:
                raise ActionError(f"编号 {node_id} 不存在")
            locator = _locate(page, node)
            href = locator.get_attribute("href") or ""
            target = locator.get_attribute("target") or ""
            if target == "_blank":
                # 新标签页打开：直接在当前页导航
                page.goto(href, wait_until="load")
                return f"已点击 [{node_id}] {node.role} {node.name!r} (新标签页 → 当前页导航)"
            locator.click()
            return f"已点击 [{node_id}] {node.role} {node.name!r}"

        if cmd == "type":
            node_id, txt = action.args[0], action.args[1]
            node = mapping.get(node_id)
            if node is None:
                raise ActionError(f"编号 {node_id} 不存在")
            locator = _locate(page, node)
            locator.fill("")
            locator.type(txt, delay=30)
            return f"已在 [{node_id}] 输入 {txt!r}"

        if cmd == "select":
            node_id, opt = action.args[0], action.args[1]
            node = mapping.get(node_id)
            if node is None:
                raise ActionError(f"编号 {node_id} 不存在")
            locator = _locate(page, node)
            try:
                locator.select_option(label=opt)
            except Exception:
                locator.select_option(value=opt)
            return f"已在 [{node_id}] 选择 {opt!r}"

        if cmd == "check":
            node_id = action.args[0]
            node = mapping.get(node_id)
            if node is None:
                raise ActionError(f"编号 {node_id} 不存在")
            locator = _locate(page, node)
            locator.set_checked(True)
            return f"已选中 [{node_id}]"

        if cmd == "uncheck":
            node_id = action.args[0]
            node = mapping.get(node_id)
            if node is None:
                raise ActionError(f"编号 {node_id} 不存在")
            locator = _locate(page, node)
            locator.set_checked(False)
            return f"已取消选中 [{node_id}]"

        if cmd == "scroll":
            direction = action.args[0]
            if direction.lower() == "down":
                page.mouse.wheel(0, 600)
                return "已向下滚动"
            if direction.lower() == "up":
                page.mouse.wheel(0, -600)
                return "已向上滚动"
            raise ActionError(f"未知滚动方向: {direction!r}")

        if cmd == "press":
            key = _normalize_key(action.args[0])
            page.keyboard.press(key)
            return f"已按键 {key}"

        if cmd == "navigate":
            url = action.args[0]
            page.goto(url, wait_until="load")
            return f"已导航至 {url}"

        if cmd == "wait":
            seconds = action.args[0]
            page.wait_for_timeout(int(seconds * 1000))
            return f"已等待 {seconds} 秒"

        if cmd == "finish":
            return "finish"

        raise ActionError(f"未知指令: {cmd!r}")
    except ActionError:
        raise
    except Exception as e:
        node_id = action.args[0] if action.args else "?"
        raise ActionError(f"操作失败 [{node_id}]: {e}") from e
