"""浏览器控制层：封装 Playwright 启动/上下文/页面/导航/截图/关闭。"""
from __future__ import annotations
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page


class BrowserController:
    """Playwright 浏览器控制器，支持上下文管理。

    用法:
        with BrowserController(headless=False) as bc:
            bc.navigate("https://example.com")
            page = bc.page
            ...
    """

    def __init__(self, headless: bool = True, viewport: dict | None = None):
        self.headless = headless
        self.viewport = viewport or {"width": 1280, "height": 800}
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None

    def start(self) -> "BrowserController":
        """启动 Playwright、浏览器、上下文、页面。返回 self。"""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(viewport=self.viewport)
        self.page = self._context.new_page()
        self.page.set_default_timeout(30000)  # 30s
        return self

    def navigate(self, url: str, wait_until: str = "load"):
        """导航到 URL，等待加载完成。"""
        self.page.goto(url, wait_until=wait_until)

    def screenshot(self, path: str | None = None, full_page: bool = False) -> bytes:
        """截图，返回 bytes。path 不为 None 时同时写入文件。"""
        return self.page.screenshot(path=path, full_page=full_page)

    def close(self):
        """按 page -> context -> browser -> playwright 顺序关闭。需幂等（重复调用不报错）。"""
        # page 无需显式关闭，关闭 context 时会自动关闭页面
        # 每一步都判断非 None，关闭后置 None，并用 try/except 包裹避免级联失败
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
            finally:
                self._context = None
                self.page = None  # 页面随 context 一起失效
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            finally:
                self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            finally:
                self._playwright = None

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
