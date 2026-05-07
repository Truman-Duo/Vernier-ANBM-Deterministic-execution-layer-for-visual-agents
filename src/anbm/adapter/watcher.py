import asyncio
import logging
import os

from watchfiles import awatch

from anbm.logging_config import log_event

logger = logging.getLogger(__name__)


class AdapterWatcher:
    """
    监听 adapters/ 目录的文件变更，自动重载对应 adapter。

    - handler.py 变更 → 调用 loader.reload() + 清理该 adapter 所有 session 的 fingerprint 缓存
    - manifest.json 变更 → 记录日志，不自动重载（load_manifest 每次读磁盘）
    - 其他文件变更 → 忽略
    """

    def __init__(self, loader, adapters_dir: str, fsm_engine=None):
        self._loader = loader
        self._adapters_dir = adapters_dir
        self._fsm = fsm_engine
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self):
        if not os.path.isdir(self._adapters_dir):
            logger.warning("Adapters directory not found, hot-reload disabled: %s", self._adapters_dir)
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._watch_loop())
        log_event(logger, "INFO", "hot_reload_started", path=self._adapters_dir)

    async def stop(self):
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log_event(logger, "INFO", "hot_reload_stopped")

    async def _watch_loop(self):
        try:
            async for changes in awatch(self._adapters_dir, stop_signal=self._stop_event):
                for change_type, path in changes:
                    await self._handle_change(change_type, path)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log_event(logger, "ERROR", "hot_reload_watch_error", error=str(e))

    async def _handle_change(self, change_type: int, path: str):
        # 提取 adapter_id 和文件名
        rel = os.path.relpath(path, self._adapters_dir)
        parts = rel.replace("\\", "/").split("/")
        if len(parts) < 2:
            return
        adapter_id = parts[0]
        filename = parts[-1]

        if filename == "handler.py":
            await self._reload_adapter(adapter_id)
        elif filename == "manifest.json":
            log_event(
                logger, "INFO", "manifest_changed",
                adapter_id=adapter_id,
                path=rel,
            )

    async def _reload_adapter(self, adapter_id: str):
        try:
            self._loader.reload(adapter_id)
            log_event(logger, "INFO", "adapter_reloaded", adapter_id=adapter_id)

            # 清理该 adapter 所有 session 的 fingerprint 缓存
            if self._fsm is not None:
                await self._fsm.session_store.clear_all_fingerprints_for_adapter(adapter_id)
        except Exception as e:
            log_event(
                logger, "ERROR", "adapter_reload_failed",
                adapter_id=adapter_id,
                error=str(e),
            )
