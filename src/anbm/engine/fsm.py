import asyncio
import logging
import os
from datetime import datetime, timezone

from anbm.adapter.base import ActionNotAllowedError, AdapterNotFoundError
from anbm.adapter.loader import AdapterLoader
from anbm.engine.router import RetryOrchestrator, DecisionRouter
from anbm.engine.session_store import Session, SessionStore
from anbm.engine.session_store_sqlite import SQLiteSessionStore
from anbm.engine.validator import StateValidator
from anbm.engine.visual_client import VisualClient
from anbm.executor.browser import BrowserManager
from anbm.health.checker import HealthChecker
from anbm.health.monitor import AdapterMonitor
from anbm.logging_config import log_event

logger = logging.getLogger(__name__)


class FSMEngine:
    """
    状态机引擎，负责编排完整的三层执行路径。
    """

    def __init__(self, reaper_interval: int = 60, max_idle_seconds: int = None):
        if max_idle_seconds is None:
            max_idle_seconds = int(
                os.environ.get("ANBM_MAX_IDLE_SECONDS", "1800")
            )
        self.browser = BrowserManager(max_idle_seconds=max_idle_seconds)
        self.adapter_loader = AdapterLoader()
        self.validator = StateValidator()

        backend = os.environ.get("ANBM_SESSION_BACKEND", "memory").lower()
        if backend == "sqlite":
            db_path = os.environ.get("ANBM_SESSION_DB_PATH", "sessions.db")
            self.session_store = SQLiteSessionStore(db_path)
            logger.info("Using SQLite session backend: %s", db_path)
        else:
            self.session_store = SessionStore()
            logger.info("Using in-memory session backend")
        self.retry = RetryOrchestrator(self.validator)
        self._reaper_interval = reaper_interval
        self._reaper_task = asyncio.create_task(self._reaper_loop())

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        visual_client = VisualClient(api_key=api_key) if api_key else None
        self.router = DecisionRouter(
            retry=self.retry,
            session_store=self.session_store,
            visual_client=visual_client,
        )

        self.monitor = AdapterMonitor(
            checker=HealthChecker(self.browser, self.adapter_loader),
            loader=self.adapter_loader,
            interval_seconds=int(
                os.environ.get("ANBM_MONITOR_INTERVAL", "3600")
            ),
        )

    async def _reaper_loop(self):
        """后台任务：定期扫描并关闭超过 max_idle_seconds 未活跃的 browser context。"""
        while True:
            await asyncio.sleep(self._reaper_interval)
            idle_sessions = await self.session_store.get_idle_sessions(
                self.browser.max_idle_seconds
            )
            for sid in idle_sessions:
                await self.browser.close_context(sid)
                log_event(
                    logger, "INFO", "reaper_closed_context",
                    session_id=sid,
                    max_idle_seconds=self.browser.max_idle_seconds,
                )

    async def create_session(self, url: str, adapter_hint: str = None) -> Session:
        """分配新 session（不导航）。导航由 browse() 统一处理。"""
        if adapter_hint:
            adapter_id = adapter_hint
        else:
            adapter_id = self._match_url_to_adapter(url)

        manifest = self.adapter_loader.load_manifest(adapter_id)
        # 以第一个定义的状态作为初始状态占位，browse() 会做实际 detect
        initial_state = list(manifest.get("states", {}).keys())[0]

        session = await self.session_store.create(
            adapter_id=adapter_id,
            adapter_version=manifest.get("version", "0.0.0"),
            initial_state=initial_state,
        )

        log_event(
            logger, "INFO", "session_created",
            session_id=session.session_id,
            adapter=adapter_id,
            url=url,
            state=initial_state,
        )
        return session

    async def browse(self, session_id: str, url: str, options: dict = None, cookies: list[dict] | None = None) -> dict:
        session = await self.session_store.get(session_id)

        # 检查 adapter 一致性：复用 session 时 URL 必须匹配同一 adapter
        detected_adapter_id = self._match_url_to_adapter(url)
        if session.adapter_id != detected_adapter_id:
            return {
                "error": "adapter_mismatch",
                "message": (
                    f"session '{session_id}' 绑定到 adapter '{session.adapter_id}'，"
                    f"无法用于 adapter '{detected_adapter_id}'。请创建新 session。"
                ),
                "session_id": session_id,
                "bound_adapter": session.adapter_id,
                "requested_adapter": detected_adapter_id,
                "session_suspended": False,
            }

        acquired = await self.session_store.acquire_lock(session_id)
        if not acquired:
            return {
                "error": "session_busy",
                "message": "Session 正在执行其他操作，请稍后重试。",
            }

        try:
            session.session_suspended = False

            manifest = self.adapter_loader.load_manifest(session.adapter_id)
            adapter = self.adapter_loader.load_handler(session.adapter_id)
            page = await self.browser.get_page(session_id)

            # 恢复已有 cookie（跨服务重启及新 session 首次访问场景）
            await self.browser.restore_cookies_from_store(session_id, self.session_store)

            # AF-20260507：API 传入的 cookies（用于 verify 脚本传入 session cookie）
            if cookies:
                try:
                    context = self.browser._contexts.get(session_id)
                    if context:
                        await context.add_cookies(cookies)
                        logger.info("API 传入 %d 个 cookies 已添加到 session %s", len(cookies), session_id)
                except Exception as e:
                    logger.warning("添加 API 传入 cookies 失败: %s", e)

            # 两阶段导航等待（alpha.2）：domcontentloaded + 锚点元素
            # goto 超时不崩溃，继续走 detect_state 尝试恢复
            timeout = int(os.environ.get("ANBM_NAVIGATE_TIMEOUT", "90000"))
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            except Exception:
                logger.warning("goto(%s) 超时或失败，继续尝试 detect_state", url[:80])
            anchor = self._get_anchor_selector(manifest, session.current_state)
            if anchor:
                try:
                    await page.wait_for_selector(anchor, timeout=min(10000, timeout))
                except Exception:
                    pass  # 超时不报错，交给 detect_state 判断

            fp_cache = await self.session_store.get_fingerprint_cache(session_id)
            current_state, _ = await self.validator.detect_state(page, manifest, fp_cache)
            await self.session_store.update_state(session_id, current_state)

            # BF-20260506-3：状态未知时不进入 extract，直接返回错误响应
            if current_state == "unknown":
                await self.session_store.suspend(session_id)
                return {
                    "session_id": session_id,
                    "current_state": "unknown",
                    "execution_path": "state_unknown",
                    "retry": {"attempts": None, "succeeded": False},
                    "session_suspended": True,
                    "adapter": session.adapter_id,
                    "adapter_version": session.adapter_version,
                    "error": "state_not_recognized",
                    "message": (
                        f"导航到 {url} 后无法识别页面状态。"
                        "session 已挂起。"
                    ),
                    "url": url,
                }

            result = await self.router.execute_extract(page, session, adapter, manifest)

            if result.get("execution_path") == "visual_fallback":
                await self.session_store.suspend(session_id)

            # 保存 cookie
            await self.browser.save_cookies_to_store(session_id, self.session_store)

            result["session_id"] = session_id
            result["current_state"] = session.current_state
            result["adapter"] = session.adapter_id
            result["adapter_version"] = session.adapter_version

            return result

        finally:
            await self.session_store.release_lock(session_id)

    async def act(self, session_id: str, action: str, params: dict = None) -> dict:
        """在已存在的 session 上执行操作。

        失败语义（invariant）：
        - 任意步骤失败时，session.current_state 停留在最后一次执行成功的步骤所处的状态
        - 失败不回滚前序步骤产生的状态变更
        - 仅当 detect_state() 本身无法匹配任何已知状态时，current_state 才可能为 unknown
        - state_changed 不等于失败：状态跳转是 FSM 正常流转，current_state 更新为 new_state
        """
        if params is None:
            params = {}

        session = await self.session_store.get(session_id)

        if session.session_suspended:
            return {
                "session_id": session_id,
                "current_state": session.current_state,
                "error": "session_suspended",
                "message": "Session 已挂起，请先调用 /browse 重新同步。",
            }

        acquired = await self.session_store.acquire_lock(session_id)
        if not acquired:
            return {
                "session_id": session_id,
                "error": "session_busy",
                "message": "Session 正在执行其他操作，请稍后重试。",
            }

        try:
            manifest = self.adapter_loader.load_manifest(session.adapter_id)
            adapter = self.adapter_loader.load_handler(session.adapter_id)
            page = await self.browser.get_page(session_id)

            if not self.validator.check_action_allowed(
                manifest, session.current_state, action
            ):
                allowed = manifest.get("states", {}).get(
                    session.current_state, {}
                ).get("allowed_actions", [])
                return {
                    "session_id": session_id,
                    "current_state": session.current_state,
                    "action_rejected": True,
                    "reason": f"操作 '{action}' 在状态 '{session.current_state}' 下不被允许",
                    "allowed_actions": allowed,
                    "session_suspended": False,
                }

            is_idempotent = self.validator.get_idempotency(manifest, action)
            result = await self.router.execute_act(
                page, session, action, params, adapter, manifest, is_idempotent
            )

            if result.get("execution_path") == "deterministic" and result.get("success"):
                next_state = result.get("next_state")
                if next_state:
                    valid = await self.validator.validate_transition(
                        page, manifest, next_state
                    )
                    if not valid:
                        fp_cache = await self.session_store.get_fingerprint_cache(session_id)
                        actual, _ = await self.validator.detect_state(page, manifest, fp_cache)
                        result = {
                            "session_id": session_id,
                            "current_state": session.current_state,
                            "execution_path": "state_changed",
                            "success": False,
                            "previous_state": next_state,
                            "new_state": actual,
                            "retry": {"attempts": None, "succeeded": False},
                            "message": (
                                f"操作后状态验证失败：预期 '{next_state}'，"
                                f"实际 '{actual}'，请重新同步。"
                            ),
                            "session_suspended": False,
                        }
                        await self.session_store.update_state(session_id, actual)
                    else:
                        if next_state != session.current_state:
                            await self.session_store.clear_fingerprint_cache(session_id)
                        await self.session_store.update_state(session_id, next_state)
                        # 非幂等操作成功后保存 cookie
                        if not is_idempotent:
                            await self.browser.save_cookies_to_store(session_id, self.session_store)

            elif result.get("execution_path") == "state_changed":
                await self.session_store.update_state(
                    session_id, result.get("new_state")
                )

            elif result.get("execution_path") == "visual_fallback":
                await self.session_store.suspend(session_id)

            result["session_id"] = session_id
            result["current_state"] = session.current_state
            return result

        finally:
            await self.session_store.release_lock(session_id)

    def _match_url_to_adapter(self, url: str) -> str:
        """遍历 adapters 目录，匹配 URL 到适配器。匹配失败则抛 AdapterNotFoundError。"""
        import json
        import os

        adapters_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "adapters")
        )
        if not os.path.isdir(adapters_dir):
            raise AdapterNotFoundError("(no adapters directory)")

        for entry in sorted(os.listdir(adapters_dir)):
            manifest_path = os.path.join(adapters_dir, entry, "manifest.json")
            if not os.path.isfile(manifest_path):
                continue
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
            patterns = manifest.get("url_patterns", [])
            for pattern in patterns:
                if pattern.replace("*", "") in url:
                    return manifest["id"]

        raise AdapterNotFoundError(
            f"no adapter matched URL '{url}'"
        )

    @staticmethod
    def _get_anchor_selector(manifest: dict, state: str) -> str | None:
        """从 manifest 的指定状态中提取第一个 element_present 选择器，用于导航后锚点等待。"""
        state_def = manifest.get("states", {}).get(state, {})
        check = state_def.get("check", {})
        if check.get("type") == "element_present":
            return check.get("selector")
        also = state_def.get("also_check", {})
        if also.get("type") == "element_present":
            return also.get("selector")
        return None
