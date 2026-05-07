"""BF-20260506-3：detect_state 返回 unknown 后 /browse 不应 500。

覆盖场景：
1. detect_state 返回 "unknown" → browse 应返回 state_unknown 而非抛异常
2. 正常 URL (/news) → 回归测试，行为不变
3. 使用真实 detect_state + FakePage 无路径 URL → 验证 URL 匹配不到状态时的完整链路
"""
from contextlib import ExitStack
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult
from anbm.engine.fsm import FSMEngine
from tests.fixtures.mock_pages import FakePage, FakeElement

HN_URL = "https://news.ycombinator.com/news"         # 正常 URL（匹配 news_list）
HN_URL_NO_PATH = "https://news.ycombinator.com"       # 无路径 URL（不匹配任何状态）

HN_MANIFEST = {
    "id": "hackernews",
    "name": "Hacker News",
    "version": "1.0.0",
    "states": {
        "item_detail": {
            "check": {"type": "url_matches", "pattern": "/item\\?id=\\d+"},
            "allowed_actions": ["open_item"],
        },
        "news_list": {
            "check": {"type": "element_present", "selector": "tr.athing"},
            "allowed_actions": ["paginate", "open_item"],
        },
    },
    "transitions": {
        "news_list": {
            "paginate": "news_list",
            "open_item": "item_detail",
        },
        "item_detail": {
            "open_item": "item_detail",
        },
    },
    "action_idempotency": {
        "paginate": True,
        "open_item": True,
    },
}


class MockHackerNewsAdapter(BaseAdapter):
    async def extract(self, page, state):
        if state == "news_list":
            return ExtractResult(
                data={
                    "stories": [{"title": "Test", "url": "https://x.com", "score": "1"}],
                    "pagination": {"current_page": "1", "has_next": False},
                    "is_logged_in": False,
                },
                state="news_list",
            )
        elif state == "item_detail":
            return ExtractResult(
                data={"title": "Test", "url": "", "comments": [], "is_logged_in": False},
                state="item_detail",
            )
        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action, params):
        raise ValueError("act() not used in browse tests")


def _mock_fsm(fsm, page, adapter):
    """Mock browser.get_page and adapter_loader for browse() testing."""
    stack = ExitStack()
    stack.enter_context(
        patch.object(fsm.browser, "get_page", return_value=page)
    )
    stack.enter_context(
        patch.object(fsm.browser, "restore_cookies_from_store", AsyncMock())
    )
    stack.enter_context(
        patch.object(fsm.browser, "save_cookies_to_store", AsyncMock())
    )
    stack.enter_context(
        patch.object(fsm.adapter_loader, "load_manifest", return_value=HN_MANIFEST)
    )
    stack.enter_context(
        patch.object(fsm.adapter_loader, "load_handler", return_value=adapter)
    )
    return stack


@pytest.mark.asyncio
async def test_browse_unknown_state_returns_graceful_response():
    """
    场景 1：detect_state 返回 "unknown" 时，browse 返回 state_unknown 而非抛异常。
    """
    fsm = FSMEngine(reaper_interval=999999)
    page = FakePage(url=HN_URL)
    adapter = MockHackerNewsAdapter()

    try:
        with _mock_fsm(fsm, page, adapter):
            # Mock detect_state to return unknown (模拟 URL 不匹配场景)
            fsm.validator.detect_state = AsyncMock(return_value=("unknown", None))

            created = await fsm.create_session(HN_URL, adapter_hint="hackernews")
            sid = created.session_id

            # browse() 不应抛异常
            result = await fsm.browse(sid, HN_URL)

            # 验证优雅降级
            assert result["execution_path"] == "state_unknown", (
                f"期望 state_unknown，实际 {result.get('execution_path')}"
            )
            assert result["session_suspended"] is True, "状态未知时应标记 session 为挂起"
            assert result["current_state"] == "unknown"
            assert "error" in result, "响应应包含 error 字段"
            assert "message" in result, "响应应包含 message 字段"
            # 验证必含字段（API 规范）
            assert "retry" in result
            assert "adapter" in result
            assert "adapter_version" in result
            assert "session_id" in result
    finally:
        fsm._reaper_task.cancel()
        try:
            await fsm._reaper_task
        except BaseException:
            pass


@pytest.mark.asyncio
async def test_browse_normal_url_still_works():
    """
    场景 2：正常 URL（匹配 news_list）不受影响——回归测试。
    """
    fsm = FSMEngine(reaper_interval=999999)
    page = FakePage(url=HN_URL)
    page.add_element("tr.athing", FakeElement())
    adapter = MockHackerNewsAdapter()

    try:
        with _mock_fsm(fsm, page, adapter):
            created = await fsm.create_session(HN_URL, adapter_hint="hackernews")
            sid = created.session_id

            result = await fsm.browse(sid, HN_URL)
            assert result["execution_path"] == "deterministic", (
                f"期望 deterministic，实际 {result.get('execution_path')}"
            )
            assert result["session_suspended"] is False
            assert "data" in result
            assert len(result["data"]["stories"]) > 0
    finally:
        fsm._reaper_task.cancel()
        try:
            await fsm._reaper_task
        except BaseException:
            pass


@pytest.mark.asyncio
async def test_browse_no_path_url_triggers_unknown():
    """
    场景 3：使用真实 detect_state，FakePage URL 为 https://news.ycombinator.com（无路径），
    验证真实 URL 匹配下状态识别为 unknown。
    """
    fsm = FSMEngine(reaper_interval=999999)
    # URL 不带路径，不匹配任何 url_matches pattern
    page = FakePage(url=HN_URL_NO_PATH)
    adapter = MockHackerNewsAdapter()

    try:
        with _mock_fsm(fsm, page, adapter):
            created = await fsm.create_session(HN_URL_NO_PATH, adapter_hint="hackernews")
            sid = created.session_id

            # 用真实 detect_state
            result = await fsm.browse(sid, HN_URL_NO_PATH)

            # 期望 state_unknown（无路径 URL 不匹配任何 pattern）
            assert result["execution_path"] == "state_unknown", (
                f"期望 state_unknown，实际 {result.get('execution_path')}"
            )
            assert result["session_suspended"] is True
    finally:
        fsm._reaper_task.cancel()
        try:
            await fsm._reaper_task
        except BaseException:
            pass
