# ai-browser 🤖🌐

**AI 友好的终端浏览器** — 基于 Playwright 将网页可访问性树转换为带编号的文本界面，让 LLM 或用户通过 `click 3`、`type 2 "hello"` 等简单指令精确操作浏览器。

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## ✨ 核心特性

- **🧠 文本化网页表示** — 将网页可访问性树（Accessibility Tree）转化为带编号的语义大纲，显著降低 LLM 的 token 消耗与理解难度
- **🎯 精确编号操作** — 无需坐标或复杂选择器，通过元素编号即可完成点击、输入、选择等操作
- **🤖 LLM Agent 模式** — 给定任务描述，由 LLM 自动循环操作浏览器直到完成
- **💻 交互 REPL 模式** — 手动输入指令实时操作浏览器，适合调试和探索
- **📊 TUI 仪表盘模式** — 可视化监控 Agent 执行进度
- **🔧 多模式 CLI** — 支持命令执行、文件批量执行、管道输入等多种使用方式

---

## 🚀 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/shqhsgqjsuugs/aibrowser.git
cd aibrowser

# 安装项目（含 LLM 可选依赖）
pip install -e ".[llm]"

# 安装 Playwright 浏览器内核
playwright install chromium
```

> 💡 若仅使用交互模式而不调用 LLM，也可以执行 `pip install -e .` 跳过 `openai` 依赖。

### 环境配置（Agent 模式需要）

```bash
# 设置 OpenAI API Key
export OPENAI_API_KEY="sk-..."
```

Windows:
```cmd
set OPENAI_API_KEY=sk-...
```

---

## 🎮 使用方式

### 1. 自动 Agent 模式

给定任务描述，由 LLM 自动循环操作浏览器直到完成：

```bash
ai_browser --task "搜索 Playwright 文档并打开快速入门页面" --url https://www.google.com
```

### 2. 交互 REPL 模式

手动输入指令操作浏览器：

```bash
ai_browser --url https://www.google.com
```

进入 REPL 后可输入指令，例如 `click 3`、`type 2 "hello"`、`finish` 等。

### 3. TUI 仪表盘模式

```bash
ai_browser --tui --task "在示例页面输入用户名 admin 并点击登录"
```

### 4. 命令执行模式

```bash
# 单条命令
ai_browser --url "https://example.com" --exec "click 3"

# 多条命令
ai_browser --url "https://example.com" -e "click 1" -e "type 2 'hello'" -e "click 3"

# 从文件读取命令
ai_browser --url "https://example.com" --file commands.txt
```

---

## 📋 指令集

| 指令 | 语法 | 说明 |
|------|------|------|
| `click` | `click <编号>` | 点击编号对应的可交互元素 |
| `type` | `type <编号> "<文本>"` | 在编号对应的输入框中输入文本（自动清空） |
| `select` | `select <编号> "<选项>"` | 选择下拉框中的选项 |
| `check` | `check <编号>` | 勾选复选框 |
| `uncheck` | `uncheck <编号>` | 取消勾选复选框 |
| `scroll` | `scroll <up\|down> [步数]` | 上下滚动页面 |
| `press` | `press <键名>` | 模拟按键，如 `press Enter` |
| `navigate` | `navigate <url>` | 导航到指定 URL |
| `wait` | `wait <秒数>` | 等待指定秒数 |
| `finish` | `finish [说明]` | 结束当前任务 |

编号来自页面状态提取后输出的带编号菜单，每个编号对应一个可访问性节点。编号仅对当前步骤有效，每一步都会重新提取并刷新。

---

## 🏗️ 系统架构

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

---

## 📁 项目结构

```
aibrowser/
├── ai_browser/          # 核心包
│   ├── __init__.py      # 包入口与公开 API
│   ├── browser.py       # Playwright 浏览器控制器
│   ├── state.py         # 页面状态提取器（可访问性树 → 文本）
│   ├── actions.py       # 动作解析与执行器
│   ├── agent.py         # LLM Agent 循环驱动
│   ├── llm.py           # LLM 客户端封装
│   ├── repl.py          # 交互式 REPL
│   ├── tui.py           # TUI 仪表盘界面
│   ├── cli.py           # 命令行入口
│   └── types.py         # 共享数据类型
├── examples/
│   ├── demo_task.py     # 示例脚本
│   └── sample.html      # 示例页面
├── tests/
│   └── test_state_and_actions.py  # 单元测试
├── pyproject.toml       # 项目配置
├── README.md            # 本文件
└── LICENSE              # MIT 开源协议
```

---

## 🧪 开发

### 运行测试

```bash
pytest tests/
```

### 本地开发安装

```bash
pip install -e ".[llm]"
playwright install chromium
```

---

## 📝 示例交互流

```
[状态] 搜索页，输入框[1]空，按钮[2]"搜索"
LLM: type 1 "GPT-5"
[执行] 输入框填入了 GPT-5

[新状态] 输入框[1]值"GPT-5"，按钮[2]，建议项[3]"GPT-5 release"
LLM: click 2
[执行] 页面跳转至搜索结果
[任务完成]
```

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

## 📄 License

本项目基于 [MIT License](LICENSE) 开源。

---

## 🌟 致谢

- [Playwright](https://playwright.dev/) — 强大的浏览器自动化框架
- [Rich](https://github.com/Textualize/rich) — 终端美化库
- 灵感来源于 [Textualize](https://www.textualize.io/) 和 [Playwright](https://playwright.dev/) 的社区实践
