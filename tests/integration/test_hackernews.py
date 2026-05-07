"""Integration tests for the Hacker News adapter — read-only workflow."""
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from anbm.adapter.base import (
    BaseAdapter,
    ExtractResult,
    ActResult,
    SelectorFailedError,
)
from anbm.engine.fsm import FSMEngine
from tests.fixtures.mock_pages import FakePage, FakeElement, FakeElement

HN_URL = "https://news.ycombinator.com/news"
ITEM_URL = "https://news.ycombinator.com/item?id=47936347"

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
    def __init__(self):
        self._fail_extract = 0

    def fail_n_times(self, n):
        self._fail_extract = n

    async def extract(self, page, state):
        if self._fail_extract > 0:
            self._fail_extract -= 1
            raise SelectorFailedError("mock failure", selector="tr.athing")

        if state == "news_list":
            return ExtractResult(
                data={
                    "stories": [
                        {
                            "id": "123",
                            "title": "Test Story",
                            "url": "https://example.com",
                            "site": "example.com",
                            "score": "42",
                            "author": "testuser",
                            "comments_count": "5",
                        }
                        for _ in range(20)
                    ],
                    "pagination": {"current_page": "1", "has_next": True},
                    "is_logged_in": False,
                },
                state="news_list",
            )
        elif state == "item_detail":
            return ExtractResult(
                data={
                    "title": "Test Story",
                    "url": "https://example.com",
                    "comments": [
                        {"author": "user1", "text": "Comment 0", "indent_level": 0},
                        {"author": "user2", "text": "Reply 1", "indent_level": 1},
                        {"author": "user3", "text": "Reply 2", "indent_level": 2},
                        {"author": "user4", "text": "Reply 3", "indent_level": 3},
                    ],
                    "is_logged_in": False,
                },
                state="item_detail",
            )
        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action, params):
        if action == "paginate":
            page.url = "https://news.ycombinator.com/news?p=2"
            return ActResult(success=True, next_state="news_list")
        elif action == "open_item":
            page.url = params.get("url", ITEM_URL)
            return ActResult(success=True, next_state="item_detail")
        raise ValueError(f"act() 不支持操作: {action}")


def _mock_fsm(fsm, page, adapter):
    stack = ExitStack()
    stack.enter_context(patch.object(fsm.browser, "get_page", return_value=page))
    stack.enter_context(
        patch.object(fsm.adapter_loader, "load_manifest", return_value=HN_MANIFEST)
    )
    stack.enter_context(
        patch.object(fsm.adapter_loader, "load_handler", return_value=adapter)
    )
    return stack


def _page_news_list():
    page = FakePage(url=HN_URL)
    page.add_element("tr.athing", FakeElement())
    return page


def _page_item_detail():
    return FakePage(url=ITEM_URL)


@pytest.mark.asyncio
async def test_browse_news_list():
    fsm = FSMEngine()
    page = _page_news_list()
    adapter = MockHackerNewsAdapter()

    with _mock_fsm(fsm, page, adapter):
        created = await fsm.create_session(HN_URL, adapter_hint="hackernews")
        sid = created.session_id
        # create_session 占位状态为 dict 第一个 key，当前为 item_detail
        # browse() 会通过 detect_state 覆盖为实际状态
        assert created.current_state in ("news_list", "item_detail")

        br = await fsm.browse(sid, HN_URL)
        assert br["execution_path"] == "deterministic"
        assert len(br["data"]["stories"]) >= 20
        story = br["data"]["stories"][0]
        assert "title" in story
        assert "url" in story
        assert "score" in story
        assert "author" in story


@pytest.mark.asyncio
async def test_browse_item_with_comments():
    fsm = FSMEngine()
    page = _page_item_detail()
    adapter = MockHackerNewsAdapter()

    with _mock_fsm(fsm, page, adapter):
        created = await fsm.create_session(ITEM_URL, adapter_hint="hackernews")
        sid = created.session_id

        br = await fsm.browse(sid, ITEM_URL)
        assert br["execution_path"] == "deterministic"
        assert br["data"]["title"] == "Test Story"
        comments = br["data"]["comments"]
        assert len(comments) == 4
        assert comments[-1]["indent_level"] == 3


@pytest.mark.asyncio
async def test_paginate():
    fsm = FSMEngine()
    page = _page_news_list()
    adapter = MockHackerNewsAdapter()

    with _mock_fsm(fsm, page, adapter):
        created = await fsm.create_session(HN_URL, adapter_hint="hackernews")
        sid = created.session_id

        result = await fsm.act(sid, "paginate", {"direction": "next"})
        assert result["execution_path"] == "deterministic"
        assert result["next_state"] == "news_list"
        assert result["session_suspended"] is False


@pytest.mark.asyncio
async def test_unknown_tolerance_on_news():
    fsm = FSMEngine()
    page = _page_news_list()
    adapter = MockHackerNewsAdapter()

    with _mock_fsm(fsm, page, adapter):
        from unittest.mock import AsyncMock

        mock_detect = AsyncMock()
        mock_detect.side_effect = [
            ("news_list", None),
            ("news_list", None),
            ("unknown", None),
        ]

        with patch.object(fsm.validator, "detect_state", mock_detect):
            adapter.fail_n_times(1)
            created = await fsm.create_session(HN_URL, adapter_hint="hackernews")
            sid = created.session_id

            br = await fsm.browse(sid, HN_URL)
            assert br["execution_path"] == "deterministic"
            assert br["retry"]["succeeded"] is True
