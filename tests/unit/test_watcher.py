"""Unit tests for AdapterWatcher and loader.reload()."""
import os
import sys

import pytest

from anbm.adapter.loader import AdapterLoader, ADAPTERS_DIR
from anbm.adapter.watcher import AdapterWatcher


@pytest.fixture
def loader():
    return AdapterLoader()


def _abs(adapter_id: str, filename: str) -> str:
    """Build absolute path within adapters directory."""
    return os.path.join(ADAPTERS_DIR, adapter_id, filename)


@pytest.mark.asyncio
async def test_reload_clears_module_cache(loader):
    """reload() 清除 sys.modules 缓存后重新加载 handler，返回新实例。"""
    h1 = loader.load_handler("douban_movie")
    module_name = "adapters.douban_movie.handler"

    assert module_name in sys.modules, "首次加载后 module 应缓存"

    h2 = loader.reload("douban_movie")
    assert h2 is not None
    assert h2 is not h1, "reload 应返回新实例"
    # reload 后 module 应重新缓存
    assert module_name in sys.modules, "reload 后 module 应重新存在"


@pytest.mark.asyncio
async def test_get_last_reload_time(loader):
    """reload 前返回 None，reload 后返回时间字符串。"""
    assert loader.get_last_reload_time("douban_movie") is None

    loader.reload("douban_movie")
    result = loader.get_last_reload_time("douban_movie")
    assert result is not None
    assert "T" in result  # ISO 格式时间


@pytest.mark.asyncio
async def test_watcher_handle_change_triggers_reload(loader):
    """_handle_change 收到 handler.py 变更时调用 loader.reload()。"""
    watcher = AdapterWatcher(loader, ADAPTERS_DIR)
    await watcher.start()
    try:
        assert loader.get_last_reload_time("douban_movie") is None
        await watcher._handle_change(1, _abs("douban_movie", "handler.py"))
        result = loader.get_last_reload_time("douban_movie")
        assert result is not None, "handler.py 变更应触发 reload"
    finally:
        await watcher.stop()


@pytest.mark.asyncio
async def test_watcher_manifest_change_no_reload(loader):
    """manifest.json 变更不应触发 reload（不更新 last_reload）。"""
    watcher = AdapterWatcher(loader, ADAPTERS_DIR)
    await watcher.start()
    try:
        assert loader.get_last_reload_time("douban_movie") is None
        await watcher._handle_change(1, _abs("douban_movie", "manifest.json"))
        assert loader.get_last_reload_time("douban_movie") is None
    finally:
        await watcher.stop()
