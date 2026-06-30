"""页面状态提取模块。

把 Playwright 可访问性树（``page.accessibility.snapshot()``）转换为带编号的文本表示，
供 LLM / 用户通过 ``click 3``、``type 2 "hello"`` 这样的指令操作浏览器。

核心函数 :func:`extract_page_state` 返回 :class:`~ai_browser.types.PageState`，
其中包含：
- ``outline``：缩进语义大纲，可交互元素内嵌 ``[编号]``
- ``menu``：扁平化编号操作菜单
- ``mapping``：``{编号(int) -> NodeInfo}``，供 ActionExecutor 定位元素

本模块不直接导入 playwright，``page`` 参数以鸭子类型使用（仅需 ``url`` 属性、
``title()`` 方法与 ``accessibility.snapshot()`` 方法），因此在 playwright 未安装时
仍可被成功导入。
"""
from __future__ import annotations

from typing import Any, Optional

from ai_browser.types import NodeInfo, PageState


# 可交互角色：分配编号
INTERACTIVE_ROLES = {
    "button", "link", "textbox", "searchbox", "combobox", "checkbox", "radio",
    "menuitem", "option", "tab", "slider", "switch", "spinbutton", "menuitemcheckbox",
    "menuitemradio", "treeitem", "textbox",
}

# 语义角色：出现在大纲中但不分配编号（除非同时在 INTERACTIVE_ROLES）
SEMANTIC_ROLES = {
    "heading", "dialog", "alert", "form", "navigation", "main", "banner",
    "contentinfo", "complementary", "list", "listitem", "region", "article",
    "section", "search", "group", "tablist", "tablist", "menubar", "menu",
    "tree", "treegrid", "table", "row", "cell", "columnheader", "rowheader",
    "status", "log", "marquee", "timer", "application",
}

# 值类输入角色：状态后缀中显示当前值（空值显示"空"）
_VALUE_ROLES = {"textbox", "searchbox", "spinbutton"}
# 勾选类角色：状态后缀中显示"已选中/未选中"
_CHECKED_ROLES = {"checkbox", "radio", "switch", "menuitemcheckbox", "menuitemradio"}
# 弹窗角色：置顶处理
_DIALOG_ROLES = {"dialog", "alert"}

# 文本截断阈值
_MAX_TEXT_LEN = 100


def _truncate(text: Any, max_len: int = _MAX_TEXT_LEN) -> str:
    """截断文本：超过 ``max_len`` 字符时保留前 ``max_len-3`` 字符并追加 ``"..."``。

    ``None`` 或非字符串输入返回空字符串。
    """
    if text is None:
        return ""
    s = str(text)
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


def _state_suffix(node: dict, role: str) -> str:
    """生成节点状态后缀，如 ``(空)``、``(未选中)``、``(已选中, disabled)``。

    无可显示状态时返回空字符串。
    """
    parts = []
    if role in _VALUE_ROLES:
        value = node.get("value")
        if value is None or value == "":
            parts.append("空")
        else:
            parts.append(_truncate(value))
    elif role in _CHECKED_ROLES:
        parts.append("已选中" if node.get("checked") else "未选中")
    if node.get("disabled"):
        parts.append("disabled")
    if not parts:
        return ""
    return "(" + ", ".join(parts) + ")"


def _format_node(node: dict, role: str, name: str, node_id: Optional[int]) -> str:
    """格式化 outline 单行核心部分（不含缩进与 ``"- "`` 前缀）。

    - 可交互且有编号：``role [id] "name" (state)``
    - 可交互但禁用（无编号）：``role "name" (state)``
    - 语义角色：``role "name"``（name 非空时才追加）
    """
    parts = [role]
    if node_id is not None:
        parts.append(f"[{node_id}]")
    if name:
        parts.append(f'"{_truncate(name)}"')
    state = _state_suffix(node, role)
    if state:
        parts.append(state)
    return " ".join(parts)


def _walk(
    node: dict,
    depth: int,
    lines_outline: list,
    lines_menu: list,
    mapping: dict,
    counters: dict,
) -> None:
    """递归遍历 snapshot 节点，填充 outline / menu / mapping。

    Parameters
    ----------
    node:
        当前 snapshot 节点 dict。
    depth:
        当前缩进深度（每层 2 空格）。
    lines_outline / lines_menu:
        大纲行、菜单行的累加列表。
    mapping:
        ``{编号 -> NodeInfo}`` 映射表。
    counters:
        ``{"next_id": int, "name_counter": {role|name: count}}``，跨递归共享。
    """
    if not isinstance(node, dict):
        return

    role = node.get("role", "") or ""
    name = node.get("name", "") or ""
    disabled = bool(node.get("disabled"))
    indent = "  " * depth

    is_interactive = role in INTERACTIVE_ROLES
    is_semantic = role in SEMANTIC_ROLES

    # 产生输出的节点会令其子节点缩进一层；被跳过的"其他角色"保持当前深度
    produces_line = False

    if is_interactive:
        produces_line = True
        if disabled:
            # 禁用元素：仅出现在大纲中提示存在，不分配编号、不进入菜单与映射，
            # 也不计入 name_counter（避免影响可定位元素的 index 消歧义）
            lines_outline.append(f"{indent}- {_format_node(node, role, name, None)}")
        else:
            counters["next_id"] += 1
            node_id = counters["next_id"]

            key = f"{role}|{name}"
            name_count = counters["name_counter"].get(key, 0) + 1
            counters["name_counter"][key] = name_count

            info = NodeInfo(
                role=role,
                name=name,
                value=node.get("value"),
                description=node.get("description"),
                checked=node.get("checked"),
                disabled=disabled,
                index=name_count - 1,  # 0 基，用于消歧义定位
                raw=node,
            )
            mapping[node_id] = info

            lines_outline.append(f"{indent}- {_format_node(node, role, name, node_id)}")

            # 菜单行格式：[id] role "name" (state)
            menu_parts = [f"[{node_id}]", role]
            if name:
                menu_parts.append(f'"{_truncate(name)}"')
            state = _state_suffix(node, role)
            if state:
                menu_parts.append(state)
            lines_menu.append(" ".join(menu_parts))
    elif is_semantic:
        produces_line = True
        lines_outline.append(f"{indent}- {_format_node(node, role, name, None)}")
    # 其他角色（WebArea / text / generic / none / paragraph ...）：
    # 跳过本节点不输出行，但仍递归遍历其子节点，深度不变。

    # 递归子节点
    children = node.get("children") or []
    child_depth = depth + 1 if produces_line else depth
    for child in children:
        _walk(child, child_depth, lines_outline, lines_menu, mapping, counters)


def extract_page_state(page) -> PageState:
    """提取页面状态，返回 :class:`PageState`。

    将 ``page.accessibility.snapshot()`` 的可访问性树转换为带编号的文本表示：

    - 弹窗（``dialog``/``alert``）子树**置顶**输出并优先分配编号；
    - 可交互角色（非禁用）分配从 1 递增的编号并进入 ``mapping``；
    - 文本超过 100 字符被截断为前 97 字符 + ``"..."``。

    当 ``snapshot`` 为 ``None``（页面未加载）时，``outline``/``menu`` 为空字符串、
    ``mapping`` 为 ``{}``。
    """
    url = page.url
    title = page.title()
    snapshot = page.accessibility.snapshot()

    lines_outline: list = []
    lines_menu: list = []
    mapping: dict = {}

    if snapshot:
        counters = {"next_id": 0, "name_counter": {}}

        # 弹窗优先：根节点 children 分为 dialog/alert 与其它两组，
        # 先处理弹窗（其子树内的可交互元素先编号），再处理其余节点。
        children = snapshot.get("children") or []
        dialogs = [c for c in children if (c.get("role") or "") in _DIALOG_ROLES]
        others = [c for c in children if (c.get("role") or "") not in _DIALOG_ROLES]

        for child in dialogs:
            _walk(child, 0, lines_outline, lines_menu, mapping, counters)
        for child in others:
            _walk(child, 0, lines_outline, lines_menu, mapping, counters)

    outline = "\n".join(lines_outline)
    menu = "\n".join(lines_menu)

    menu_section = menu if menu else "(无可操作元素)"
    text = (
        f"URL: {url}\n标题: {title}\n\n"
        f"[页面区域]\n{outline}\n\n"
        f"[可操作元素]\n{menu_section}"
    )

    return PageState(
        url=url,
        title=title,
        outline=outline,
        menu=menu,
        text=text,
        mapping=mapping,
    )
