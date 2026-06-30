"""Agent 会话模块。

:class:`AgentSession` 串联状态提取、LLM 推理与动作执行，构成 Agent 循环：
每一步提取页面状态 → 构造提示词 → 调用 LLM → 解析并执行指令，
直到 LLM 输出 ``finish`` 或达到最大步数。
"""
from __future__ import annotations

from typing import Callable, Optional

from .state import extract_page_state
from .actions import parse_action, execute_action
from .llm import LLMClient, LLMConfigError
from .types import MaxStepsExceeded, ActionError, PageState


# 系统提示词：定义 Agent 角色、可用指令、输出格式与示例
SYSTEM_PROMPT = """你是一个浏览器操作 Agent，通过编号指令操作网页以完成用户的任务。

你会看到当前页面的文本状态，依次包含：
- URL 与标题
- [页面区域] 语义大纲（缩进树，可交互元素内嵌 [编号]）
- [可操作元素] 编号操作菜单，形如 [1] button "搜索"

编号规则：编号仅对当前这一步的状态有效，每一步都会重新提取并刷新编号，绝不能跨步骤记忆或复用上一步的编号。

每一步你只能输出一条指令。可用指令如下：
- click <id>            点击编号对应的元素
- type <id> <text>      在元素中输入文本（会自动清空原内容；文本含空格时用双引号包裹，如 type 1 "hello world"）
- select <id> <option>  在下拉框中选择选项
- check <id>            勾选复选框
- uncheck <id>          取消勾选复选框
- scroll down           向下滚动页面
- scroll up             向上滚动页面
- press <key>           按键，如 press Enter、press Escape、press Tab
- navigate <url>        跳转到指定 URL
- wait <seconds>        等待若干秒（如 wait 2）
- finish                任务完成，可后接说明，如 finish 已完成搜索

输出格式：单独一行指令，可在指令后用 ` // ` 接简短推理。例如：
    click 4 // 提交表单
    type 1 "GPT-5" // 输入搜索词

操作准则：
- 优先使用编号操作菜单中的元素，编号必须来自当前状态。
- 遇到弹窗（dialog/alert）时先处理弹窗，再做其他操作。
- 只输出一条指令行，不要输出多余内容。

示例：
任务：搜索 GPT-5
状态：
URL: https://example.com
标题: 示例搜索
[可操作元素]
[1] searchbox "搜索" (空)
[2] button "搜索"
输出：type 1 "GPT-5" // 输入搜索词
"""


# 历史摘要最多保留的步数（控制 token）
_HISTORY_LIMIT = 5


def build_prompt(task: str, history: list, state: PageState) -> str:
    """构造用户提示词。

    为控制 token，历史只保留最近 5 步，且每步仅摘要 ``动作 -> 结果``
    （不重复完整状态文本）。由于 Agent 循环每一步最多追加一条历史，
    history 的第 i 项即对应第 i+1 步，据此推算展示用的步号。

    Args:
        task: 用户任务描述。
        history: :class:`AgentSession.history`，每项含 state_text/action/result。
        state: 当前页面状态。
    Returns:
        拼接好的用户提示词字符串。
    """
    recent = history[-_HISTORY_LIMIT:]
    start_step = len(history) - len(recent) + 1
    if recent:
        lines = []
        for offset, item in enumerate(recent):
            step_num = start_step + offset
            lines.append(f"步骤{step_num}: {item['action']} -> {item['result']}")
        history_section = "\n".join(lines)
    else:
        history_section = "(暂无)"

    return (
        f"任务: {task}\n\n"
        f"[最近操作]\n{history_section}\n\n"
        f"[当前页面状态]\n{state.text}\n\n"
        f"请输出下一步动作（仅一行指令，可选用 // 后接推理）："
    )


class AgentSession:
    """Agent 会话，协调状态提取、LLM 推理与动作执行。"""

    def __init__(self, page, llm_client: LLMClient, on_step: Optional[Callable] = None):
        """
        Args:
            page: Playwright Page 对象。
            llm_client: LLMClient 实例。
            on_step: 可选回调 fn(step:int, state:PageState, action_text:str, result:str)，
                     用于外部（如 CLI）打印进度。回调异常被忽略。
        """
        self.page = page
        self.llm = llm_client
        self.on_step = on_step
        self.history = []  # 每项: {"state_text": str, "action": str, "result": str}

    def _notify(self, step: int, state: PageState, action_text: str, result: str) -> None:
        """安全调用 on_step 回调，回调异常被忽略，不影响主循环。"""
        if self.on_step is None:
            return
        try:
            self.on_step(step, state, action_text, result)
        except Exception:
            pass

    def run(self, task: str, max_steps: int = 50) -> str:
        """执行任务直到 finish 或达到 max_steps。

        Args:
            task: 用户任务描述。
            max_steps: 最大步数上限。
        Returns:
            完成时的结果摘要字符串。
        Raises:
            MaxStepsExceeded: 达到 max_steps 仍未 finish。
            LLMConfigError: LLM 未配置（由 llm.generate 抛出并透传）。
        """
        for step in range(1, max_steps + 1):
            state = extract_page_state(self.page)
            prompt = build_prompt(task, self.history, state)
            response = self.llm.generate(prompt, system=SYSTEM_PROMPT)

            # 解析指令：失败则记录并让 LLM 在下一步看到错误重试
            try:
                action = parse_action(response)
            except ActionError as e:
                result = f"解析失败: {e}"
                self.history.append({
                    "state_text": state.text,
                    "action": response.strip(),
                    "result": result,
                })
                self._notify(step, state, response.strip(), result)
                continue

            # 任务完成
            if action.command == "finish":
                result_summary = f"任务完成（第 {step} 步）: {response.strip()}"
                self.history.append({
                    "state_text": state.text,
                    "action": response.strip(),
                    "result": result_summary,
                })
                self._notify(step, state, response.strip(), result_summary)
                return result_summary

            # 执行动作：ActionError 与意外异常都转为结果字符串，不中断循环
            try:
                result = execute_action(self.page, action, state.mapping)
            except ActionError as e:
                result = f"错误: {e}"
            except Exception as e:
                result = f"意外错误: {e}"

            self.history.append({
                "state_text": state.text,
                "action": response.strip(),
                "result": result,
            })
            self._notify(step, state, response.strip(), result)

        raise MaxStepsExceeded(f"达到最大步数 {max_steps} 未完成")
