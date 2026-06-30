"""AI 浏览器示例：演示自动模式与交互模式的最小用法。

运行前请先安装：
    pip install -e ".[llm]"
    playwright install chromium

注意：--url 接受的是 Playwright ``page.goto()`` 的目标地址。
若要打开本仓库的本地静态页面 ``examples/sample.html``，必须使用绝对路径的
``file://`` URL，相对路径无法被 Playwright 直接加载。例如（Windows）：

    --url "file:///C:/Users/Lenovo/Desktop/aibrowser/examples/sample.html"

自动模式（需配置 OPENAI_API_KEY）：

    set OPENAI_API_KEY=sk-...
    python examples/demo_task.py --task "在示例页面输入用户名 admin 并点击登录" --url "file:///C:/Users/Lenovo/Desktop/aibrowser/examples/sample.html"

交互模式：

    python examples/demo_task.py --url "file:///C:/Users/Lenovo/Desktop/aibrowser/examples/sample.html"
"""
# 直接复用项目的 CLI 入口
from ai_browser.cli import main

if __name__ == "__main__":
    import sys
    sys.exit(main())
