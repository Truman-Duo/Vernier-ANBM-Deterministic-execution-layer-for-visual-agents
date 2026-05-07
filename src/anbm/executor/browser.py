import json
import logging
import os

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from anbm.executor.stealth import stealth_config, apply_stealth_scripts

logger = logging.getLogger(__name__)


class BrowserManager:
    """
    一个 session 对应一个 browser context，Cookie 和存储相互隔离。
    """

    def __init__(self, max_idle_seconds: int = 1800):
        self._playwright = None
        self._browser: Browser | None = None
        self._contexts: dict[str, BrowserContext] = {}
        self.max_idle_seconds = max_idle_seconds

    async def _ensure_browser(self):
        if self._browser is None:
            self._playwright = await async_playwright().start()
            # 使用系统 Chrome（channel="chrome"）而非 Playwright 内置 Chromium，
            # 以减少 Reddit 等站点的 headless 检测
            launch_options = {"headless": True}
            if os.name == "nt":  # Windows
                launch_options["channel"] = "chrome"
            self._browser = await self._playwright.chromium.launch(**launch_options)
            logger.info("Browser launched (channel=%s)", launch_options.get("channel", "chromium"))

    async def create_context(self, session_id: str) -> BrowserContext:
        await self._ensure_browser()
        config = stealth_config()
        context = await self._browser.new_context(
            user_agent=config["user_agent"],
            viewport=config["viewport"],
            locale=config["locale"],
            timezone_id=config["timezone_id"],
        )

        default_path = os.path.join(".cookies", f"{session_id}.json")
        if os.path.isfile(default_path):
            try:
                with open(default_path, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
                await context.add_cookies(cookies)
                logger.info(f"Auto-loaded cookies from {default_path}")
            except Exception as e:
                logger.warning(f"Failed to auto-load cookies: {e}")

        page = await context.new_page()
        await apply_stealth_scripts(page)
        self._contexts[session_id] = context
        logger.info(f"Browser context created for session {session_id}")
        return context

    async def get_page(self, session_id: str) -> Page:
        context = self._contexts.get(session_id)
        if context is None:
            context = await self.create_context(session_id)
        pages = context.pages
        if pages:
            return pages[0]
        return await context.new_page()

    async def save_cookies(self, session_id: str, path: str):
        """Save the session's browser context cookies to a JSON file."""
        context = self._contexts.get(session_id)
        if context is None:
            logger.warning(f"No context for session {session_id}, cannot save cookies")
            return
        cookies = await context.cookies()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        logger.info(f"Cookies saved to {path} for session {session_id}")

    async def load_cookies(self, session_id: str, path: str):
        """Load cookies from a JSON file into the session's browser context."""
        context = self._contexts.get(session_id)
        if context is None:
            logger.warning(f"No context for session {session_id}, cannot load cookies")
            return
        if not os.path.isfile(path):
            logger.warning(f"Cookie file not found: {path}")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            await context.add_cookies(cookies)
            logger.info(f"Cookies loaded from {path} for session {session_id}")
        except Exception as e:
            logger.warning(f"Failed to load cookies: {e}")

    async def save_cookies_to_store(self, session_id: str, session_store):
        """Save the session's cookies to a session store (session_store_sqlite or memory)."""
        context = self._contexts.get(session_id)
        if context is None:
            logger.warning(f"No context for session {session_id}, cannot save cookies")
            return
        try:
            storage = await context.storage_state()
            cookie_data = json.dumps(storage, ensure_ascii=False)
            await session_store.update_cookie_data(session_id, cookie_data)
            logger.info(f"Cookies saved to store for session {session_id}")
        except Exception as e:
            logger.warning(f"Failed to save cookies to store: {e}")

    async def restore_cookies_from_store(self, session_id: str, session_store):
        """Restore cookies from a session store into the session's browser context."""
        context = self._contexts.get(session_id)
        if context is None:
            logger.warning(f"No context for session {session_id}, cannot restore cookies")
            return
        try:
            cookie_data = await session_store.get_cookie_data(session_id)
            if not cookie_data:
                return
            storage = json.loads(cookie_data)
            cookies = storage.get("cookies", [])
            if cookies:
                await context.add_cookies(cookies)
                logger.info(f"Cookies restored from store for session {session_id}")
        except Exception as e:
            logger.warning(f"Failed to restore cookies from store: {e}")

    async def close_context(self, session_id: str):
        context = self._contexts.pop(session_id, None)
        if context:
            await context.close()
            logger.info(f"Browser context closed for session {session_id}")

    async def close_all(self):
        for sid, ctx in list(self._contexts.items()):
            await ctx.close()
        self._contexts.clear()
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("All browser resources closed")
