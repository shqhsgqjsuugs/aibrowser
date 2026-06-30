"""ai_browser 状态提取与动作解析的单元测试。

不依赖真实浏览器：
- state 测试使用 FakePage（鸭子类型，仅实现 url / title() / accessibility.snapshot()）；
- actions 测试仅覆盖 parse_action（纯解析，不导入 playwright）。

运行：
    python -m unittest tests.test_state_and_actions -v
"""
import unittest

from ai_browser.state import extract_page_state
from ai_browser.actions import parse_action
from ai_browser.types import ActionError


class FakePage:
    """模拟 Playwright Page，仅实现 state 提取所需接口（鸭子类型）。"""

    def __init__(self, snapshot, url="https://example.com", title="示例"):
        self.url = url
        self._title = title
        self._snapshot = snapshot
        # accessibility.snapshot() 返回构造时传入的 snapshot
        self.accessibility = type("A", (), {"snapshot": lambda self: snapshot})()

    def title(self):
        return self._title


class TestStateExtractor(unittest.TestCase):
    """extract_page_state 的核心语义测试（用 fake page，不连真实浏览器）。"""

    def test_numbering_unique_and_increasing(self):
        """3 个可交互元素应分配唯一递增编号 1/2/3，菜单包含 [1][2][3]。"""
        snapshot = {
            "role": "WebArea",
            "name": "",
            "children": [
                {"role": "button", "name": "按钮"},
                {"role": "textbox", "name": "输入框"},
                {"role": "link", "name": "链接"},
            ],
        }
        state = extract_page_state(FakePage(snapshot))
        self.assertEqual(set(state.mapping.keys()), {1, 2, 3})
        self.assertIn("[1]", state.menu)
        self.assertIn("[2]", state.menu)
        self.assertIn("[3]", state.menu)

    def test_filter_non_interactive(self):
        """heading 是语义角色：进入大纲但不分配编号、不进入 mapping。"""
        snapshot = {
            "role": "WebArea",
            "name": "",
            "children": [
                {"role": "heading", "name": "主标题", "level": 1},
                {"role": "button", "name": "确认"},
            ],
        }
        state = extract_page_state(FakePage(snapshot))
        self.assertIn("主标题", state.outline)
        # 仅 button 进入 mapping，编号为 1
        self.assertEqual(set(state.mapping.keys()), {1})
        self.assertEqual(state.mapping[1].role, "button")

    def test_text_truncation(self):
        """超过 100 字符的 name 在显示时截断为前 97 字符 + "..."（共 100）。

        注意：实际实现中 NodeInfo.name 保留原始（未截断）name，
        只有 outline / menu 的显示文本经过截断。本测试按真实行为断言。
        """
        long_name = "a" * 150
        snapshot = {
            "role": "WebArea",
            "name": "",
            "children": [
                {"role": "button", "name": long_name},
            ],
        }
        state = extract_page_state(FakePage(snapshot))
        truncated = "a" * 97 + "..."
        self.assertEqual(len(truncated), 100)
        # 显示文本被截断
        self.assertIn(truncated, state.outline)
        self.assertIn(truncated, state.menu)
        # NodeInfo.name 保留原始值（反映实际实现）
        self.assertEqual(state.mapping[1].name, long_name)

    def test_disabled_not_in_mapping(self):
        """禁用元素在大纲中提示存在，但不分配编号、不进入 mapping。"""
        snapshot = {
            "role": "WebArea",
            "name": "",
            "children": [
                {"role": "button", "name": "禁用按钮", "disabled": True},
            ],
        }
        state = extract_page_state(FakePage(snapshot))
        self.assertEqual(state.mapping, {})
        # 大纲中仍提示存在并标注 disabled
        self.assertIn("禁用按钮", state.outline)
        self.assertIn("disabled", state.outline)

    def test_dialog_pinned_top(self):
        """弹窗（dialog）子树置顶输出并优先分配编号。"""
        snapshot = {
            "role": "WebArea",
            "name": "",
            "children": [
                {"role": "button", "name": "A"},
                {"role": "dialog", "name": "弹窗", "children": [
                    {"role": "button", "name": "B"},
                ]},
            ],
        }
        state = extract_page_state(FakePage(snapshot))
        lines = state.outline.split("\n")
        # dialog 行应在外部 button A 行之前
        dialog_idx = next(i for i, ln in enumerate(lines) if "dialog" in ln)
        a_idx = next(i for i, ln in enumerate(lines) if "[2]" in ln and '"A"' in ln)
        self.assertLess(dialog_idx, a_idx)
        # dialog 内的 button B 编号为 1，外部 button A 编号为 2
        self.assertEqual(state.mapping[1].name, "B")
        self.assertEqual(state.mapping[2].name, "A")

    def test_empty_snapshot(self):
        """snapshot 为 None 时 mapping 为空、menu 为空字符串。"""
        state = extract_page_state(FakePage(None))
        self.assertEqual(state.mapping, {})
        # menu 为空字符串（"无可操作元素" 出现在 text 中而非 menu 字段）
        self.assertEqual(state.menu, "")


class TestActionParsing(unittest.TestCase):
    """parse_action 纯解析测试，不涉及 page。"""

    def test_click(self):
        a = parse_action("click 4")
        self.assertEqual(a.command, "click")
        self.assertEqual(a.args, [4])

    def test_type_quoted(self):
        a = parse_action('type 1 "Hello World"')
        self.assertEqual(a.command, "type")
        self.assertEqual(a.args, [1, "Hello World"])

    def test_type_unquoted(self):
        a = parse_action("type 1 Hello")
        self.assertEqual(a.command, "type")
        self.assertEqual(a.args, [1, "Hello"])

    def test_select_quoted(self):
        a = parse_action('select 2 "选项A"')
        self.assertEqual(a.command, "select")
        self.assertEqual(a.args, [2, "选项A"])

    def test_scroll(self):
        a = parse_action("scroll down")
        self.assertEqual(a.command, "scroll")
        self.assertEqual(a.args, ["down"])

    def test_press(self):
        a = parse_action("press Enter")
        self.assertEqual(a.command, "press")
        self.assertEqual(a.args, ["Enter"])

    def test_navigate(self):
        # URL 中的 // 不应被当作注释分隔符
        a = parse_action("navigate https://x.com")
        self.assertEqual(a.command, "navigate")
        self.assertEqual(a.args, ["https://x.com"])

    def test_wait(self):
        a = parse_action("wait 2")
        self.assertEqual(a.command, "wait")
        self.assertEqual(a.args, [2.0])

    def test_finish(self):
        a = parse_action("finish")
        self.assertEqual(a.command, "finish")
        self.assertEqual(a.args, [])

    def test_finish_with_reason(self):
        a = parse_action("finish 任务完成")
        self.assertEqual(a.command, "finish")
        self.assertEqual(a.args, [])

    def test_case_insensitive(self):
        a = parse_action("CLICK 4")
        self.assertEqual(a.command, "click")
        self.assertEqual(a.args, [4])

    def test_reason_separator(self):
        # " //" 前带空格，应作为原因分隔符被剥离
        a = parse_action("click 4 // 因为要点击")
        self.assertEqual(a.command, "click")
        self.assertEqual(a.args, [4])

    def test_invalid_raises(self):
        with self.assertRaises(ActionError):
            parse_action("foo 1")
        with self.assertRaises(ActionError):
            parse_action("")


if __name__ == "__main__":
    unittest.main()
