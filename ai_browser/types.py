"""共享数据类型。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class NodeInfo:
    """可访问性节点的定位信息，供 ActionExecutor 定位元素。

    Attributes:
        role: ARIA 角色（button, link, textbox, ...），来自 snapshot。
        name: 节点可访问名称（来自 snapshot 的 name 字段）。
        value: 节点当前值（如 textbox 的文本），可选。
        description: 描述文本，可选。
        checked: 复选框/单选框状态，可选。
        disabled: 是否禁用。
        index: 同 role+name 出现次序（0 基），用于消歧义定位。
    """
    role: str
    name: str
    value: Optional[str] = None
    description: Optional[str] = None
    checked: Optional[bool] = None
    disabled: bool = False
    index: int = 0
    raw: Optional[dict] = None  # 原始 snapshot 节点 dict


@dataclass
class Action:
    """解析后的指令。"""
    command: str  # click/type/select/check/uncheck/scroll/press/navigate/wait/finish
    args: list = field(default_factory=list)
    raw: str = ""  # 原始用户/LLM 输入文本


@dataclass
class PageState:
    """页面状态提取结果。

    Attributes:
        url: 当前页面 URL。
        title: 页面标题。
        outline: 语义大纲文本（缩进树，可交互元素内嵌编号）。
        menu: 扁平化编号操作菜单文本。
        text: 完整文本表示（URL+标题+大纲+菜单）。
        mapping: {编号(int) -> NodeInfo} 映射表。
    """
    url: str
    title: str
    outline: str
    menu: str
    text: str
    mapping: dict


class MaxStepsExceeded(Exception):
    """Agent 循环达到最大步数仍未完成。"""


class ActionError(Exception):
    """动作执行或解析错误，携带结构化信息供 Agent 读取。"""
