"""Integration tests for the Wikipedia adapter — read-only workflow."""
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
from tests.fixtures.mock_pages import FakePage, FakeElement

WIKI_URL = "https://en.wikipedia.org/wiki/Web_scraping"

WIKI_MANIFEST = {
    "id": "wikipedia",
    "name": "Wikipedia",
    "version": "1.0.0",
    "states": {
        "article": {
            "check": {
                "type": "url_matches",
                "pattern": "/wiki/(?!Special:|File:|Talk:|User:|Wikipedia:|Help:)",
            },
            "allowed_actions": ["navigate_link"],
        },
        "special_page": {
            "check": {"type": "url_contains", "value": "/wiki/Special:"},
            "allowed_actions": [],
        },
    },
    "transitions": {
        "article": {"navigate_link": "article"},
    },
    "action_idempotency": {
        "navigate_link": True,
    },
}


class MockWikipediaAdapter(BaseAdapter):
    def __init__(self):
        self._fail_extract = 0

    def fail_n_times(self, n):
        self._fail_extract = n

    async def extract(self, page, state):
        if self._fail_extract > 0:
            self._fail_extract -= 1
            raise SelectorFailedError("mock failure", selector="h1#firstHeading")

        if state == "article":
            return ExtractResult(
                data={
                    "title": "Web scraping",
                    "summary": "Web scraping is data scraping used for extracting data from websites.",
                    "sections": [
                        {"level": 2, "title": "History"},
                        {"level": 2, "title": "Techniques"},
                    ],
                    "infobox": {},
                    "language_links": [
                        {"lang": "fr", "title": "Francais", "url": "https://fr.wikipedia.org/"}
                    ],
                },
                state="article",
            )
        elif state == "special_page":
            return ExtractResult(data={}, state="special_page")
        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action, params):
        if action == "navigate_link":
            href = params.get("href", "/wiki/Web_scraping")
            url = f"https://en.wikipedia.org{href}"
            await page.goto(url)
            page.url = url
            return ActResult(success=True, next_state="article")
        raise ValueError(f"act() 不支持操作: {action}")


def _mock_fsm(fsm, page, adapter):
    stack = ExitStack()
    stack.enter_context(patch.object(fsm.browser, "get_page", return_value=page))
    stack.enter_context(
        patch.object(fsm.adapter_loader, "load_manifest", return_value=WIKI_MANIFEST)
    )
    stack.enter_context(
        patch.object(fsm.adapter_loader, "load_handler", return_value=adapter)
    )
    return stack


@pytest.mark.asyncio
async def test_browse_article():
    fsm = FSMEngine()
    page = FakePage(url=WIKI_URL)
    adapter = MockWikipediaAdapter()

    with _mock_fsm(fsm, page, adapter):
        created = await fsm.create_session(WIKI_URL, adapter_hint="wikipedia")
        sid = created.session_id
        assert created.current_state == "article"

        br = await fsm.browse(sid, WIKI_URL)
        assert br["execution_path"] == "deterministic"
        assert br["data"]["title"] == "Web scraping"
        assert len(br["data"]["sections"]) == 2


@pytest.mark.asyncio
async def test_anchor_navigation_no_state_change():
    fsm = FSMEngine()
    page = FakePage(url=WIKI_URL)
    adapter = MockWikipediaAdapter()

    with _mock_fsm(fsm, page, adapter):
        created = await fsm.create_session(WIKI_URL, adapter_hint="wikipedia")
        sid = created.session_id

        result = await fsm.act(sid, "navigate_link", {"href": "/wiki/Web_scraping#History"})
        assert result["execution_path"] == "deterministic"
        assert result["next_state"] == "article"


@pytest.mark.asyncio
async def test_unknown_tolerance():
    fsm = FSMEngine()
    page = FakePage(url=WIKI_URL)
    adapter = MockWikipediaAdapter()

    with _mock_fsm(fsm, page, adapter):
        from unittest.mock import AsyncMock

        mock_detect = AsyncMock()
        mock_detect.side_effect = [
            ("article", None),
            ("article", None),
            ("unknown", None),
        ]

        with patch.object(fsm.validator, "detect_state", mock_detect):
            adapter.fail_n_times(1)
            created = await fsm.create_session(WIKI_URL, adapter_hint="wikipedia")
            sid = created.session_id

            br = await fsm.browse(sid, WIKI_URL)
            assert br["execution_path"] == "deterministic"
            assert br["retry"]["succeeded"] is True


@pytest.mark.asyncio
async def test_detect_state_performance():
    fsm = FSMEngine()
    page = FakePage(url=WIKI_URL)
    adapter = MockWikipediaAdapter()

    with _mock_fsm(fsm, page, adapter):
        created = await fsm.create_session(WIKI_URL, adapter_hint="wikipedia")
        sid = created.session_id

        br = await fsm.browse(sid, WIKI_URL)
        assert br["execution_path"] == "deterministic"
        assert "retry" in br


@pytest.mark.asyncio
async def test_navigate_link_follows_internal_link():
    """navigate_link 使用 href 参数完成真实页面跳转，next_state 为 article。"""
    from unittest.mock import AsyncMock

    fsm = FSMEngine()
    page = FakePage(url="https://en.wikipedia.org/wiki/Web_scraping")
    adapter = MockWikipediaAdapter()

    mock_goto = AsyncMock()
    original_goto = page.goto
    page.goto = mock_goto

    with _mock_fsm(fsm, page, adapter):
        created = await fsm.create_session(WIKI_URL, adapter_hint="wikipedia")
        sid = created.session_id
        mock_goto.reset_mock()

        result = await fsm.act(sid, "navigate_link", {"href": "/wiki/Turing_machine"})

        assert result["execution_path"] == "deterministic"
        assert result["next_state"] == "article"
        mock_goto.assert_called_once_with(
            "https://en.wikipedia.org/wiki/Turing_machine"
        )

    page.goto = original_goto
