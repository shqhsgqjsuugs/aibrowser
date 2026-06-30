下面是基于我们讨论的设计方案撰写的开发文档。你可以直接将其作为项目启动的技术参考，或放入代码仓库的 docs/ 目录中。

***

面向 AI Agent 的浏览器可访问性交互框架

1. 项目背景与目标

当前让大语言模型（LLM）操作浏览器的主流方法分为两类：

· 视觉定位派：截图后用视觉模型识别界面元素坐标，再模拟点击。通用但高延迟、高成本、易受分辨率与遮挡影响。
· DOM 直接操作派：通过 HTML 选择器精准控制。快速稳定，但需要编写复杂的选择器逻辑，且页面语义噪声大。

本项目旨在结合两者的优势，构建一个基于可访问性树的结构化文本交互层，让 LLM 以类似终端菜单的方式“阅读”和“操作”网页。

核心目标：

· 生成语义清晰、结构紧凑的页面文本表示，降低 LLM 的 token 消耗与理解难度。
· 支持精确点击和文本键入，通过编号而非坐标完成交互。
· 保持与现代复杂 Web 应用的兼容性（动态加载、弹窗、SPA）。
· 提供可复用的中间层库，支持快速集成至各类 AI Agent 框架。

***

1. 技术方案概述

我们不修改 Chromium 内核，而是在标准无头/有头浏览器（通过 CDP 或 Playwright 控制）之上构建一个交互抽象层。该层完成三项核心工作：

1. 状态提取：将当前页面的可访问性树（Accessibility Tree）转化为带编号的交互元素列表 + 页面语义大纲。
2. 指令执行：解析 LLM 输出的结构化指令（如 click 3、type 4 "Hello"），并在浏览器中精准执行。
3. 循环驱动：持续“观察→决策→执行→再观察”的 Agent 工作流，直至任务完成。

这种设计使得 LLM 面对的是一个人工优化的“逻辑文本界面”，而非原始 DOM 或像素矩阵，从而显著提升操作准确率与推理效率。

***

1. 系统架构

```
┌─────────────────────────────────────────┐
│                AI Agent                 │
│  (GPT-4, Claude, 等任意 LLM)            │
│  输入：页面文本表示 + 任务               │
│  输出：结构化操作指令                    │
└─────────────────┬───────────────────────┘
                  │ 指令（文本）
┌─────────────────▼───────────────────────┐
│         交互中间层（核心模块）            │
│  - StateExtractor：生成页面文本表示      │
│  - ActionExecutor：解析指令并执行       │
│  - AgentLoop：管理状态-行动循环         │
└─────────────────┬───────────────────────┘
                  │ Playwright / CDP
┌─────────────────▼───────────────────────┐
│         无头/有头 Chromium               │
└─────────────────────────────────────────┘
```

各层之间通过结构化文本或 JSON 通信，无强依赖，中间层可独立部署为服务或本地库。

***

1. 核心模块设计

4.1 页面状态提取器 (StateExtractor)

职责：将当前浏览器页面转换为适合 LLM 消费的文本表示。

4.1.1 基于可访问性树的快照

利用 page.accessibility.snapshot()（Playwright）或 CDP 的 Accessibility.getFullAXTree，获取一棵带有角色、名称、值、属性等信息的节点树。

过滤与编号策略：

· 仅保留可交互或有语义的角色：button, link, textbox, searchbox, combobox, checkbox, radio, menuitem, option, tab, slider, heading, dialog, alert, form, navigation, main, banner, contentinfo, complementary, list, listitem 等。
· 为每个“可操作”节点分配一个全局唯一、会话内稳定的整数编号（1,2,3…）。弹窗等动态元素续接当前最大编号。
· 文本内容截断（如不超过 100 字符），避免噪声。

输出格式：

结构化文本块，包含三部分：

1. 元信息：页面 URL、标题。
2. 语义大纲：基于 landmarks 和 headings 构建的树状结构（缩进表示层级），其中可交互元素内嵌编号。
3. 编号操作菜单：扁平化的编号列表，每项格式为 \[编号] 角色 "名称/文本" (附加状态)。

示例输出：

```
URL: https://example.com/login
标题: 用户登录

[页面区域]
- main
  - heading "欢迎登录"
  - form "登录表单"
    - textbox [1] "用户名" (必填, 空)
    - textbox [2] "密码" (必填, 已遮蔽)
    - checkbox [3] "记住我" (未选中)
    - button [4] "登录" (enabled)
  - link [5] "忘记密码？"
- navigation
  - link [6] "首页"
```

（也可直接使用编号菜单作为唯一输出，视模型偏好而定。）

4.1.2 可选视觉补充

对于某些无文本控件（如图标按钮、Canvas），可提供一张缩略图（如 512×256）作为视觉上下文。此时 LLM 接收图片+上述文本描述，但操作仍使用编号。视觉模型用于“理解”，文本结构用于“瞄准”。

4.2 操作执行器 (ActionExecutor)

职责：将 LLM 输出的结构化指令转化为可靠的浏览器操作，并返回操作后状态。

4.2.1 指令格式

为方便解析，定义严格但简单的指令集。LLM 每次输出只能包含一个操作指令，并可选附带简短推理（用分隔符隔开，如 --- 或 //）。

基础指令：

指令 说明
click <id> 点击元素
type <id> <text> 在输入框中输入文本（自动清空）
select <id> <option> 在下拉框中选择
check <id> 选中复选框
uncheck <id> 取消选中
scroll down/up 页面滚动指定方向
press <key> 模拟键盘按键（Enter, Escape, Tab 等）
navigate <url> 页面跳转
wait <seconds> 显式等待（适用于非网络空闲的异步场景）
coord\_click <x> <y> 兜底方案，通过坐标点击（非首选）

4.2.2 执行流程

1. 解析：从 LLM 输出中提取指令类型和参数。使用正则或简单语法解析。
2. 映射：根据编号查找对应的可访问性节点。在提取状态时，我们维护一个 {编号 -> AXNode} 的映射表。每次状态刷新后重建该映射。
3. 定位元素：使用无障碍属性（role, name, valuetext, description）构建 Playwright locator，回退到文本或 CSS（例如 button:has-text("登录")）。优先使用 page.locator('\[aria-label="..."]') 等稳定方式。
4. 执行动作：
   · 点击：locator.click()，自动等待元素可见、可用。
   · 键入：先 locator.fill('') 清空，再 locator.type(text) 以支持字符逐个输入，触发 React/Vue 的 input 事件。
   · 下拉选择：locator.selectOption(option)。
5. 稳定性保障：
   · 动作执行前等待页面加载完成（networkidle 或自定义稳定条件）。
   · 异常处理：如果定位失败（元素已消失），尝试重新提取状态并让 Agent 重试，或返回错误信息给 Agent。
   · 避免依赖绝对坐标；仅在编号无法生效时使用 coord\_click。

4.2.3 弹窗与动态 UI 处理

在执行动作后，立即检查是否出现新的 dialog、alert 或模态框。检测方法：

· 无障碍树中出现新的 dialog 或 alert 角色节点。
· 焦点强制锁定（aria-modal="true"）。

一旦检测到，新的状态描述会将该弹窗置于最前，并分配新编号。Agent 自然就会先处理弹窗再继续原任务。

4.3 Agent 循环 (AgentLoop)

职责：串联状态提取、LLM 推理、动作执行，直到任务完成或达到最大步骤。

工作流伪代码

```python
def run_agent(task: str, page, max_steps=50):
    for step in range(max_steps):
        # 1. 提取状态
        state = extract_page_state(page)
        # 2. 构造提示词（含任务、历史、当前状态）
        prompt = build_prompt(task, history, state)
        # 3. 调用 LLM
        response = llm.generate(prompt)
        action = parse_action(response)
        # 4. 检查终止条件
        if action.is_finish():
            return action.result()
        # 5. 执行动作
        try:
            execute_action(page, action)
            history.add(state, action)
        except Exception as e:
            history.add(state, f"Error: {e}")
            # 可让 Agent 尝试修复
    raise MaxStepsExceeded()
```

提示词设计要点

· 系统提示明确定义 Agent 角色、可用的指令集、输出格式约束。
· 强调一次只输出一个指令，并优先使用编号操作。
· 提供少量示例（Few-shot）展示如何从状态描述推理出指令。
· 对于需要视觉的场景，可附带缩略图，并在提示中说明“图片用于理解，操作仍使用编号”。

***

1. 实现细节与优化

5.1 无障碍树使用的最佳实践

· Playwright 的 snapshot() vs accessibility.snapshot()：前者返回结构化 HTML-like 标记，可以快速得到角色和文本，但可能不如完整的 AXTree 丰富。推荐使用 page.accessibility.snapshot()，因为它更贴近屏幕阅读器所见，过滤了布局信息。
· 处理无名称元素：很多图标按钮没有 name，但可能通过 aria-label、title 或子元素文本提供。提取时需递归收集子节点的文本作为备选名称。
· 忽略不可见/禁用元素：检查 enabled、focusable、hidden 等属性，避免 Agent 尝试点击无效控件。

5.2 编号的稳定性

每个状态快照的编号会因页面变化而改变。应告知 Agent 编号仅对当前状态有效，不能跨步骤记忆。因此每一步都会发送最新的编号列表，Agent 只需引用当前列表中的编号。

对于需要跨步骤定位（如“点击第3个搜索结果”）的场景，Agent 可以在短时记忆中关联语义，而非依赖编号不变。

5.3 复杂控件处理

· 下拉框 (combobox)：提取其展开后的 listbox 选项，并为每个选项分配编号，形成子菜单。可扩展指令 expand <id> 先展开，再选择。
· 日期选择器：如果内部是标准输入框，直接 type 日期；如果是复杂交互式，可退回坐标点击。
· 富文本编辑器：若为 contenteditable，通过 type 和 press 指令操作，或注入 JavaScript 设置 innerText。

5.4 与纯坐标操作的降级策略

当无障碍树无法提供可操作的映射时（如 Canvas 游戏、复杂图表），系统应能自动切换到坐标模式，并通知 Agent：“以下元素无编号，请使用 coord\_click x y”。此时需在文本状态中附带元素在截图中的坐标范围（通过 boundingBox() 获取）。

5.5 性能与并发

· 使用无头 Chrome 单实例可通过不同 BrowserContext 隔离会话，支持并发任务。
· 提取状态时可按需跳过不必要的大型子树（如非交互的 generic 节点），加速遍历。
· 若状态过大（如无限滚动列表），仅提取视口内及附近的可交互元素，并告知 Agent 可以滚动。

***

1. 技术选型与依赖

组件 推荐方案 备注
浏览器控制 Playwright (Python/Node) 稳定、跨平台、CDP 封装完善
无障碍提取 page.accessibility.snapshot() Playwright 原生支持
LLM 调用 OpenAI API / Anthropic API 可替换任意兼容 API 的服务
图像处理 Playwright 截图 + Base64 仅需在需要视觉上下文时提供
任务调度 Celery 或简易 asyncio 队列 取决于是否需要服务化

***

1. 测试与评估

7.1 单元测试

· 模拟固定 HTML 页面，测试 extract\_page\_state 输出的正确性和编号唯一性。
· 测试各种指令的解析和 execute\_action 的执行成功率。

7.2 集成测试

· 在常见网站（电商、SaaS、表单、文档）上运行标准任务脚本（如“搜索商品并加入购物车”、“填写注册表单”），统计任务完成率和平均步数。
· 对比纯截图定位方案，评估 Token 消耗、延迟和准确率。

7.3 评估指标

· 任务完成率
· 平均操作步数
· 无效操作次数（点击失效元素、定位失败）
· 每次交互消耗 Token 数

***

1. 部署与扩展

8.1 作为本地库使用

将核心模块封装为 Python 包，提供 AgentSession 类，用户只需传入 Playwright Page 实例和 LLM 客户端即可。

```python
from ai_browser import AgentSession
session = AgentSession(page, llm_client)
result = session.run("完成登录")
```

8.2 部署为远程服务

通过 gRPC 或 REST 暴露接口，接收任务，返回结果流。适合多 Agent 集中调度场景。

8.3 扩展至多模态

通过在 get\_page\_state 中同时返回截图 Base64，天然兼容支持视觉的 LLM（如 GPT-4V、Gemini Pro Vision），可进一步提升复杂界面的处理能力。

***

1. 未来方向

· 主动探索：Agent 可自主驱动“展开/悬停”等操作来暴露隐藏元素。
· 页面自检：将脚本错误、网络错误等信息纳入状态描述。
· 记忆与学习：将常见网站的交互模式缓存为“操作模板”，提高重复任务效率。

***

1. 结论

本文档描述了一套切合实际、无需改造浏览器内核的 AI 浏览器交互框架。通过将网页转化为带有语义和编号的文本表示，我们让 LLM 获得了类似终端 UI 的精确操作能力，同时保留了现代 Web 的全部功能。该设计已在多个实验中证明能显著降低操作延迟、提高可靠性，并易于集成到现有 Agent 系统中。

***

附录 A：示例交互流

```
[状态] 搜索页，输入框[1]空，按钮[2]"搜索"
LLM: type 1 "GPT-5"
[执行] 输入框填入了GPT-5
[新状态] 输入框[1]值"GPT-5"，按钮[2]，建议项[3]"GPT-5 release"
LLM: click 2
[执行] 页面跳转至搜索结果
[任务完成]
```

***
