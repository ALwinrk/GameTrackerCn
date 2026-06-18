"""全局浏览器管理器 — Playwright 单例复用 + asyncio.Semaphore 并发控制.

用于 TapTap 等动态加载页面的渲染。全局只启动一个持久化浏览器实例，所有任务复用。
"""

from __future__ import annotations

import asyncio
import os
import random as _random

from backend.config import get_settings
from backend.logging_setup import get_logger

logger = get_logger()


class BrowserManager:
    """Playwright 浏览器单例管理器."""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._semaphore: asyncio.Semaphore | None = None
        self._started = False
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self._started and self._browser is not None

    async def start(self) -> bool:
        """启动浏览器。失败返回 False（降级到静态提取）."""
        async with self._lock:
            if self._started:
                return True
            try:
                from patchright.async_api import async_playwright

                settings = get_settings()
                concurrency = getattr(settings, "playwright_concurrency", 2)
                self._semaphore = asyncio.Semaphore(concurrency)

                # Step 1: 启动 Node.js 驱动
                try:
                    self._playwright = await async_playwright().start()
                except Exception as e:
                    logger.warning("Patchright 驱动启动失败: {} — 浏览器功能不可用", e)
                    self._playwright = None
                    self._started = False
                    return False

                chrome_exe = self._find_chromium()
                if not chrome_exe:
                    logger.warning("未找到 Chromium 可执行文件 — 浏览器功能不可用")
                    await self._playwright.stop()
                    self._playwright = None
                    self._started = False
                    return False

                # 国内系统: Playwright 永远直连, 不走代理
                proxy_config = None

                _ua = _random.choice([
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                ])
                _vw = _random.randint(1280, 1920)
                _vh = _random.randint(768, 1080)

                # Step 2: 启动浏览器 (限时 15s, 不使用 persistent context)
                try:
                    self._browser = await asyncio.wait_for(
                        self._playwright.chromium.launch(
                            headless=True,
                            executable_path=chrome_exe,
                            args=[
                                "--no-sandbox", "--disable-setuid-sandbox",
                                "--disable-dev-shm-usage",
                                "--disable-blink-features=AutomationControlled",
                                "--disable-extensions",
                            ],
                        ),
                        timeout=15.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning("浏览器启动超时 (15s)")
                    await self._playwright.stop()
                    self._playwright = None
                    self._started = False
                    return False
                except Exception as e:
                    logger.warning("浏览器启动失败: {}", e)
                    await self._playwright.stop()
                    self._playwright = None
                    self._started = False
                    return False

                self._started = True
                logger.info("Playwright 浏览器已启动 (并发={}, vp={}x{}, chrome={})",
                            concurrency, _vw, _vh,
                            os.path.basename(chrome_exe) if chrome_exe else "?")
                return True

            except Exception as e:
                logger.warning("Playwright 初始化异常: {} — 浏览器功能不可用", e)
                if self._playwright:
                    try:
                        await self._playwright.stop()
                    except Exception:
                        pass
                self._playwright = None
                self._started = False
                return False

    @staticmethod
    def _find_chromium() -> str | None:
        """查找 Chromium 可执行文件."""
        import shutil
        import sys

        # 1. 优先用 Playwright/Patchright 自带的
        try:
            from patchright.async_api import async_playwright
            # 尝试常见路径
            candidates = []
            if sys.platform == "win32":
                import os as _os
                local_app = _os.environ.get("LOCALAPPDATA", "")
                candidates = [
                    _os.path.join(local_app, "ms-playwright", "chromium-*", "chrome-win", "chrome.exe"),
                    _os.path.join(local_app, "patchright", "chromium-*", "chrome-win", "chrome.exe"),
                ]
                from glob import glob as _glob
                for pattern in candidates:
                    matches = sorted(_glob(pattern))
                    if matches:
                        return matches[-1]
        except Exception:
            pass

        # 2. 系统 Chrome
        for browser in ["google-chrome", "chrome", "chromium", "chromium-browser"]:
            path = shutil.which(browser)
            if path:
                return path

        # 3. Windows 常见安装路径
        if sys.platform == "win32":
            import os as _os
            for pfx in [_os.environ.get("PROGRAMFILES", "C:\\Program Files"),
                         _os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
                         _os.environ.get("LOCALAPPDATA", "")]:
                for sub in ["Google\\Chrome\\Application\\chrome.exe",
                            "Chromium\\Application\\chrome.exe"]:
                    p = _os.path.join(pfx, sub)
                    if _os.path.exists(p):
                        return p
        return None

    async def stop(self):
        """关闭浏览器."""
        async with self._lock:
            if not self._started:
                return
            try:
                if self._browser:
                    await self._browser.close()
                if self._playwright:
                    await self._playwright.stop()
                logger.info("Playwright 浏览器已关闭")
            except Exception as e:
                logger.warning("关闭浏览器出错: {}", e)
            finally:
                self._browser = None
                self._context = None
                self._playwright = None
                self._started = False

    async def new_page(self):
        """创建新页面（每次新建 context，受信号量控制），返回 (page, sem)."""
        if not self.available:
            raise RuntimeError("浏览器未启动")
        await self._semaphore.acquire()
        try:
            # 每次新建 context (避免 persistent 带来的缓存问题)
            _ua = _random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            ])
            _vw = _random.randint(1280, 1920)
            _vh = _random.randint(768, 1080)
            context = await self._browser.new_context(
                viewport={"width": _vw, "height": _vh},
                user_agent=_ua,
                proxy=None,
            )
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)
            page = await context.new_page()
            # 把 context 挂到 page 上，close_page 时一起关
            page._china_context = context
            return page, self._semaphore
        except Exception:
            self._semaphore.release()
            raise

    async def close_page(self, page, semaphore: asyncio.Semaphore):
        """关闭页面和 context，释放信号量."""
        try:
            ctx = getattr(page, '_china_context', None)
            try:
                await page.close()
            except Exception:
                pass
            if ctx:
                try:
                    await ctx.close()
                except Exception:
                    pass
        finally:
            semaphore.release()


# 全局单例
_browser_manager: BrowserManager | None = None


def get_browser_manager() -> BrowserManager:
    global _browser_manager
    if _browser_manager is None:
        _browser_manager = BrowserManager()
    return _browser_manager
