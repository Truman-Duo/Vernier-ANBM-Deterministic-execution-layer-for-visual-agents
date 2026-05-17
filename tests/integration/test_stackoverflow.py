"""Integration tests for the Stack Overflow adapter."""
from contextlib import ExitStack
from unittest.mock import patch, AsyncMock

import pytest

from anbm.adapter.base import (
    BaseAdapter,
    ExtractResult,
    ActResult,
    SelectorFailedError,
)
from anbm.engine.fsm import FSMEngine
from tests.fixtures.mock_pages import FakeLocator, FakePage

SO_LIST_URL = "https://stackoverflow.com/questions"
SO_DETAIL_URL = "https://stackoverflow.com/questions/1/how-to-write-a-python-decorator"

SO_MANIFEST = {
    "id": "stackoverflow",
    "name": "Stack Overflow",
    "version": "1.0.0",
    "states": {
        "question_list": {
            "check": {"type": "url_matches", "pattern": "/questions$"},
            "also_check": {
                "type": "element_present",
                "selector": ".s-post-summary",
            },
            "allowed_actions": ["paginate", "open_question", "search"],
        },
        "question_detail": {
            "check": {"type": "url_matches", "pattern": "/questions/\\d+/"},
            "allowed_actions": ["upvote", "extract_content"],
        },
        "search_results": {
            "check": {"type": "url_contains", "value": "/search?"},
            "allowed_actions": ["paginate", "open_question"],
        },
        "not_found": {
            "check": {
                "type": "element_absent",
                "selector": ".s-post-summary",
            },
            "allowed_actions": [],
        },
    },
    "transitions": {
        "question_list": {
            "open_question": "question_detail",
            "paginate": "question_list",
            "search": "search_results",
        },
        "question_detail": {"upvote": "question_detail"},
        "search_results": {
            "open_question": "question_detail",
            "paginate": "search_results",
        },
    },
    "action_idempotency": {
        "paginate": True,
        "open_question": True,
        "search": True,
        "extract_content": True,
        "upvote": False,
    },
}


class MockStackOverflowAdapter(BaseAdapter):
    def __init__(self):
        self._call_count = 0

    async def extract(self, page, state):
        if state in ("question_list", "search_results"):
            return ExtractResult(
                data={
                    "questions": [
                        {
                            "title": "How to write a Python decorator?",
                            "url": "/questions/1",
                            "vote_count": "42",
                            "answer_count": "3",
                            "tags": ["python", "decorator"],
                        },
                        {
                            "title": "How does async/await work?",
                            "url": "/questions/2",
                            "vote_count": "128",
                            "answer_count": "5",
                            "tags": ["python", "async"],
                        },
                    ]
                },
                state=state,
            )
        elif state == "question_detail":
            return ExtractResult(
                data={
                    "title": "How to write a Python decorator?",
                    "body_text": "I want to write a decorator...",
                    "vote_count": "42",
                    "tags": ["python", "decorator"],
                    "answer_count": "3",
                },
                state="question_detail",
            )
        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action, params):
        self._call_count += 1
        if action == "paginate":
            page.url = SO_LIST_URL + "?tab=votes"
            return ActResult(success=True, next_state="question_list")
        elif action == "open_question":
            url = params.get("url", "")
            page.url = url if url else SO_DETAIL_URL
            return ActResult(success=True, next_state="question_detail")
        elif action == "search":
            page.url = "https://stackoverflow.com/search?q=" + params.get("query", "")
            return ActResult(success=True, next_state="search_results")
        elif action == "upvote":
            page.url = SO_DETAIL_URL
            return ActResult(success=True, next_state="question_detail")
        raise ValueError(f"act() 不支持操作: {action}")

    async def extract_content(self, page):
        return await self.extract(page, "question_detail")


def _mock_fsm(fsm, page, adapter):
    stack = ExitStack()
    stack.enter_context(patch.object(fsm.browser, "get_page", return_value=page))
    stack.enter_context(
        patch.object(fsm.adapter_loader, "load_manifest", return_value=SO_MANIFEST)
    )
    stack.enter_context(
        patch.object(fsm.adapter_loader, "load_handler", return_value=adapter)
    )
    return stack


@pytest.mark.asyncio
async def test_browse_question_list():
    """提取问题列表，验证 title/vote_count/tags 字段完整。"""
    fsm = FSMEngine()
    page = FakePage(
        url=SO_LIST_URL,
        locators={".s-post-summary": FakeLocator(count=1)},
    )
    adapter = MockStackOverflowAdapter()

    with _mock_fsm(fsm, page, adapter):
        created = await fsm.create_session(SO_LIST_URL, adapter_hint="stackoverflow")
        sid = created.session_id
        assert created.current_state == "question_list"

        br = await fsm.browse(sid, SO_LIST_URL)
        assert br["execution_path"] == "deterministic"
        assert len(br["data"]["questions"]) == 2
        assert br["data"]["questions"][0]["title"] == "How to write a Python decorator?"
        assert br["data"]["questions"][0]["vote_count"] == "42"
        assert br["data"]["questions"][0]["tags"] == ["python", "decorator"]


@pytest.mark.asyncio
async def test_selector_priority():
    """用 from_html() 加载 fixture，验证新版 Stacks 选择器命中。"""
    from tests.fixtures.mock_pages import FakePage as HTMLPage

    page = HTMLPage.from_html(
        open(
            "tests/fixtures/html_snapshots/stackoverflow/question_list.html",
            encoding="utf-8",
        ).read(),
        url=SO_LIST_URL,
    )

    el = await page.query_selector('.s-post-summary')
    assert el is not None, ".s-post-summary 选择器应命中问题卡片容器"

    el = await page.query_selector('.s-post-summary--stats-item__emphasized .s-post-summary--stats-item-number')
    assert el is not None, "emphasized stats item number 选择器应命中投票数"

    el = await page.query_selector('.s-post-summary--stats-item.has-answers .s-post-summary--stats-item-number')
    assert el is not None, "has-answers stats item number 选择器应命中回答数"

    el = await page.query_selector('[rel="tag"]')
    assert el is not None, "[rel='tag'] 选择器应命中标签"


@pytest.mark.asyncio
async def test_search():
    """搜索关键词，返回 search_results 状态。"""
    fsm = FSMEngine()
    page = FakePage(
        url=SO_LIST_URL,
        locators={".s-post-summary": FakeLocator(count=1)},
    )
    adapter = MockStackOverflowAdapter()

    with _mock_fsm(fsm, page, adapter):
        created = await fsm.create_session(SO_LIST_URL, adapter_hint="stackoverflow")
        sid = created.session_id

        result = await fsm.act(sid, "search", {"query": "python decorator"})
        assert result["execution_path"] == "deterministic"
        assert result["success"] is True
        assert result["next_state"] == "search_results"
        assert result["session_suspended"] is False


@pytest.mark.asyncio
async def test_upvote_non_idempotent_failure():
    """upvote 失败返回 requires_human_decision，不进 fallback。"""
    fsm = FSMEngine()
    page = FakePage(url=SO_DETAIL_URL)
    adapter = MockStackOverflowAdapter()

    # 让 adapter.act 抛出 SelectorFailedError 模拟 upvote 失败
    original_act = adapter.act

    async def failing_act(page, action, params):
        if action == "upvote":
            raise SelectorFailedError(
                "找不到 upvote 按钮",
                selector='[aria-label="Up vote"]',
            )
        return await original_act(page, action, params)

    adapter.act = failing_act

    with _mock_fsm(fsm, page, adapter):
        created = await fsm.create_session(
            SO_DETAIL_URL, adapter_hint="stackoverflow"
        )
        sid = created.session_id

        result = await fsm.act(sid, "upvote")
        assert result["execution_path"] == "deterministic"
        assert result["success"] is False
        assert result["error"] == "non_idempotent_action_failed"
        assert result["requires_human_decision"] is True
        assert result["session_suspended"] is False


@pytest.mark.asyncio
async def test_also_check_question_list():
    """question_list 的 also_check 条件（[role='article'] 存在）未满足时，不误判为 question_list。"""
    from anbm.engine.validator import StateValidator

    page = FakePage(
        url=SO_LIST_URL,
        elements={},
    )
    validator = StateValidator()
    state, _ = await validator.detect_state(page, SO_MANIFEST)
    # question_list 要求 .s-post-summary 存在，空 elements 不满足条件
    assert state != "question_list", "also_check 未满足时不应识别为 question_list"
