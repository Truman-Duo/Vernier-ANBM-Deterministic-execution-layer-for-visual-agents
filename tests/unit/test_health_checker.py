"""Unit tests for HealthChecker.

Extends FakeElement with `.evaluate()` support for candidate finding.
"""
from unittest.mock import MagicMock

import pytest

from anbm.health.checker import HealthChecker
from anbm.health.models import (
    AdapterHealthStatus,
    DegradationReason,
    SelectorCandidate,
    SelectorCheckResult,
)
from tests.fixtures.mock_pages import FakePage, FakeElement


class MockBrowser:
    """Mock BrowserManager that returns FakePages."""

    def __init__(self, page: FakePage | None = None):
        self._page = page or FakePage()

    async def get_page(self, session_id: str) -> FakePage:
        return self._page

    async def close_context(self, session_id: str):
        pass


class RedirectPage(FakePage):
    """A FakePage that after goto() keeps the original URL (simulates redirect)."""

    async def goto(self, url, **kwargs):
        pass  # Keep self.url as-is


class TimeoutPage(FakePage):
    """A FakePage that raises TimeoutError on goto()."""

    async def goto(self, url, **kwargs):
        raise TimeoutError("Navigation timeout of 15000 ms exceeded")


@pytest.mark.asyncio
async def test_check_healthy():
    """所有选择器命中，返回 HEALTHY。"""
    page = FakePage.from_html(
        '<html><body><ol class="grid_view"><li class="item">Hello</li></ol></body></html>',
        url="https://movie.douban.com/top250",
    )
    browser = MockBrowser(page)
    loader = MagicMock()
    loader.load_manifest.return_value = {
        "id": "douban_movie",
        "version": "1.0.0",
        "test_url": "https://movie.douban.com/top250",
        "url_patterns": ["https://movie.douban.com/top250"],
        "states": {
            "movie_list": {
                "check": {"type": "element_present", "selector": "ol.grid_view"},
                "also_check": {"type": "url_contains", "value": "top250"},
                "allowed_actions": ["paginate"],
            },
        },
        "transitions": {},
        "action_idempotency": {"paginate": True},
    }

    checker = HealthChecker(browser, loader)
    report = await checker.check("douban_movie")

    assert report.status == AdapterHealthStatus.HEALTHY
    assert report.reason is None
    assert report.adapter_id == "douban_movie"
    assert report.detected_state == "movie_list"
    assert report.response_time_ms >= 0
    assert len(report.selector_results) == 1
    assert report.selector_results[0].found is True


@pytest.mark.asyncio
async def test_check_degraded_selector_changed():
    """部分选择器失效且 detected_state=unknown（少于一半失败），返回 DEGRADED/SELECTOR_CHANGED。"""
    page = FakePage.from_html(
        '<html><body><div class="new_list"><span>Item</span></div></body></html>',
        url="https://movie.douban.com/top250",
    )
    browser = MockBrowser(page)
    loader = MagicMock()
    # All state checks fail (url_contains won't match) → detected_state "unknown"
    # 4 element selectors total, only 1 fails → less than half → DEGRADED
    loader.load_manifest.return_value = {
        "id": "douban_movie",
        "version": "1.0.0",
        "test_url": "https://movie.douban.com/top250",
        "url_patterns": ["https://movie.douban.com/top250"],
        "states": {
            "list": {
                "check": {"type": "url_contains", "value": "not_in_url"},
                "also_check": {"type": "element_present", "selector": "div.new_list"},
                "allowed_actions": [],
            },
            "detail": {
                "check": {"type": "url_contains", "value": "also_not_in_url"},
                "also_check": {"type": "element_present", "selector": "span"},
                "allowed_actions": [],
            },
            "extra": {
                "check": {"type": "element_present", "selector": "ol.grid_view"},
                "also_check": {"type": "element_present", "selector": "html"},
                "allowed_actions": [],
            },
        },
        "transitions": {},
        "action_idempotency": {},
    }

    checker = HealthChecker(browser, loader)
    report = await checker.check("douban_movie")

    assert report.status == AdapterHealthStatus.DEGRADED
    assert report.reason == DegradationReason.SELECTOR_CHANGED
    assert report.detected_state == "unknown"
    assert len(report.selector_results) == 4
    failed = [r for r in report.selector_results if not r.found]
    assert len(failed) == 1
    assert failed[0].selector == "ol.grid_view"


@pytest.mark.asyncio
async def test_check_broken_url_moved():
    """final_url 不匹配任何 pattern，返回 BROKEN/URL_MOVED。"""
    page = RedirectPage(url="https://new-site.com/something")
    browser = MockBrowser(page)
    loader = MagicMock()
    loader.load_manifest.return_value = {
        "id": "hackernews",
        "version": "1.0.0",
        "test_url": "https://old-site.com/page",
        "url_patterns": ["https://old-site.com/page"],
        "states": {
            "list": {
                "check": {"type": "url_contains", "value": "old-site"},
                "allowed_actions": [],
            },
        },
        "transitions": {},
        "action_idempotency": {},
    }

    checker = HealthChecker(browser, loader)
    report = await checker.check("hackernews")

    assert report.status == AdapterHealthStatus.BROKEN
    assert report.reason == DegradationReason.URL_MOVED
    assert report.selector_results == []
    assert report.detected_state == "unknown"


@pytest.mark.asyncio
async def test_check_auth_required():
    """final_url 含 login 关键字，返回 BROKEN/AUTH_REQUIRED。"""
    page = RedirectPage(url="https://accounts.example.com/signin?redirect=/data")
    browser = MockBrowser(page)
    loader = MagicMock()
    loader.load_manifest.return_value = {
        "id": "some_adapter",
        "version": "1.0.0",
        "test_url": "https://example.com/data",
        "url_patterns": ["https://example.com/data"],
        "states": {
            "list": {
                "check": {"type": "url_contains", "value": "example.com"},
                "allowed_actions": [],
            },
        },
        "transitions": {},
        "action_idempotency": {},
    }

    checker = HealthChecker(browser, loader)
    report = await checker.check("some_adapter")

    assert report.status == AdapterHealthStatus.BROKEN
    assert report.reason == DegradationReason.AUTH_REQUIRED
    assert report.final_url == "https://accounts.example.com/signin?redirect=/data"
    assert report.selector_results == []


@pytest.mark.asyncio
async def test_check_unreachable():
    """page.goto 超时，返回 UNREACHABLE。"""
    page = TimeoutPage(url="https://down-site.example.com")
    browser = MockBrowser(page)
    loader = MagicMock()
    loader.load_manifest.return_value = {
        "id": "down_site",
        "version": "1.0.0",
        "test_url": "https://down-site.example.com",
        "url_patterns": ["https://down-site.example.com"],
        "states": {},
        "transitions": {},
        "action_idempotency": {},
    }

    checker = HealthChecker(browser, loader)
    report = await checker.check("down_site")

    assert report.status == AdapterHealthStatus.UNREACHABLE
    assert report.reason == DegradationReason.SERVICE_DOWN
    assert report.raw_error is not None
    assert "timeout" in report.raw_error.lower()


class MockVisualClient:
    """Mock VisualClient for testing."""

    def __init__(self, analyze_text_return: str = ""):
        self.analyze_text_return = analyze_text_return
        self.analyze_text_calls = []

    async def analyze_text(self, prompt: str) -> str:
        self.analyze_text_calls.append(prompt)
        return self.analyze_text_return


SIMPLE_AX_SNAPSHOT = {
    "role": "WebArea",
    "name": "Example Page",
    "children": [
        {"role": "list", "name": "电影列表", "children": [
            {"role": "listitem", "name": "电影1"},
            {"role": "listitem", "name": "电影2"},
        ]},
    ],
}

SIMPLE_HTML = """
<html><body>
<ol class="grid_view">
  <li class="item">Item 1</li>
  <li class="item">Item 2</li>
</ol>
<div class="new_list">New</div>
</body></html>
"""


def _make_page_with_ax(html: str, url: str, ax_snapshot: dict | None):
    """创建带 HTML 树和 accessibility snapshot 的 FakePage。"""
    from tests.fixtures.mock_pages import _SimpleHTMLParser

    parser = _SimpleHTMLParser()
    parser.feed(html)
    return FakePage(url=url, html_root=parser.root, ax_snapshot=ax_snapshot)


@pytest.mark.asyncio
async def test_find_candidates_css_only():
    """fallback_description=None，visual_client=None — 只返回 css_similar 候选。"""
    page = FakePage.from_html(SIMPLE_HTML, url="https://example.com")
    browser = MagicMock()
    loader = MagicMock()

    checker = HealthChecker(browser, loader, visual_client=None)

    candidates = await checker._find_candidates(page, "ol.grid_view", fallback_description=None)

    assert len(candidates) > 0
    for c in candidates:
        assert c.source == "css_similar"
        assert c.similarity is not None


@pytest.mark.asyncio
async def test_find_candidates_with_llm():
    """
    fallback_description 存在，mock visual_client.analyze_text 返回 "div.mock-selector"。
    断言结果包含一个 source="llm_suggested" 的候选，且排在列表第一位。
    """
    mock_vc = MockVisualClient(analyze_text_return="div.mock-selector")
    page = _make_page_with_ax(SIMPLE_HTML, "https://example.com", SIMPLE_AX_SNAPSHOT)
    browser = MagicMock()
    loader = MagicMock()

    checker = HealthChecker(browser, loader, visual_client=mock_vc)

    candidates = await checker._find_candidates(
        page, "ol.grid_view", fallback_description="电影列表中的条目"
    )

    assert len(candidates) > 0
    assert candidates[0].source == "llm_suggested"
    assert candidates[0].selector == "div.mock-selector"
    assert candidates[0].similarity is None
    assert mock_vc.analyze_text_calls, "analyze_text 应被调用"


@pytest.mark.asyncio
async def test_find_candidates_llm_unavailable():
    """
    fallback_description 存在，但 visual_client=None。
    断言不抛异常，降级为纯 css_similar 候选。
    """
    page = FakePage.from_html(SIMPLE_HTML, url="https://example.com")
    browser = MagicMock()
    loader = MagicMock()

    checker = HealthChecker(browser, loader, visual_client=None)

    # 不应抛异常
    candidates = await checker._find_candidates(
        page, "ol.grid_view", fallback_description="电影列表中的条目"
    )

    assert len(candidates) > 0
    for c in candidates:
        assert c.source != "llm_suggested"


@pytest.mark.asyncio
async def test_candidates_dedup_and_limit():
    """
    mock 三条路径各返回若干重叠候选，总数超过 5。
    断言最终结果不含重复 selector，且长度 <= 5。
    """
    mock_vc = MockVisualClient(analyze_text_return="ol.grid_view")
    page = _make_page_with_ax(SIMPLE_HTML, "https://example.com", SIMPLE_AX_SNAPSHOT)
    browser = MagicMock()
    loader = MagicMock()

    checker = HealthChecker(browser, loader, visual_client=mock_vc)

    candidates = await checker._find_candidates(
        page, "ol.grid_view", fallback_description="电影列表中的条目"
    )

    assert len(candidates) <= 5
    # 验证去重：所有 selector 唯一
    selectors = [c.selector for c in candidates]
    assert len(selectors) == len(set(selectors)), "应无重复 selector"


@pytest.mark.asyncio
async def test_llm_suggested_priority():
    """
    llm_suggested 和 css_similar 候选同时存在。
    断言 llm_suggested 在列表索引 0。
    """
    mock_vc = MockVisualClient(analyze_text_return="div.new_list")
    page = _make_page_with_ax(SIMPLE_HTML, "https://example.com", SIMPLE_AX_SNAPSHOT)
    browser = MagicMock()
    loader = MagicMock()

    checker = HealthChecker(browser, loader, visual_client=mock_vc)

    candidates = await checker._find_candidates(
        page, "ol.grid_view", fallback_description="电影列表中的条目"
    )

    llm_sources = [c for c in candidates if c.source == "llm_suggested"]
    assert len(llm_sources) > 0, "应包含 llm_suggested 候选"
    assert candidates[0].source == "llm_suggested"


class _BrokenAccessibility:
    """模拟 accessibility.snapshot() 抛出异常的情况。"""

    async def snapshot(self):
        raise RuntimeError("Accessibility snapshot not available")


@pytest.mark.asyncio
async def test_find_aria_candidates_returns_get_by_role_strings():
    """
    验证 _find_aria_candidates() 返回的候选包含 get_by_role 格式的字符串、
    similarity 分值、数量不超过 3 个。
    同时测试 snapshot 抛异常时静默返回空列表。
    """
    ax_snapshot = {
        "role": "WebArea",
        "name": "Stack Overflow",
        "children": [
            {"role": "list", "name": "问题列表", "children": [
                {"role": "listitem", "name": "How to write a decorator?"},
                {"role": "listitem", "name": "What is async/await?"},
            ]},
            {"role": "searchbox", "name": "Search"},
            {"role": "navigation", "name": "顶部导航"},
        ],
    }
    page = FakePage(url="https://stackoverflow.com/questions", ax_snapshot=ax_snapshot)
    browser = MagicMock()
    loader = MagicMock()
    checker = HealthChecker(browser, loader)

    result = await checker._find_aria_candidates(page, "ol.grid_view li.item")

    # 返回不为空
    assert len(result) > 0, "应有 aria 候选返回"

    # 包含 get_by_role 格式字符串
    all_selectors = [r[0] for r in result]
    assert any("get_by_role('listitem'" in s for s in all_selectors), \
        "应包含 get_by_role('listitem') 候选"
    assert any("get_by_role('list'" in s for s in all_selectors), \
        "应包含 get_by_role('list') 候选"

    # 每个候选包含 similarity 分值（float，0 到 1 之间）
    for _, score in result:
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    # 返回数量不超过 3 个
    assert len(result) <= 3

    # 边界：snapshot 抛出异常时静默返回空列表
    broken_page = FakePage(url="https://example.com")
    broken_page.accessibility = _BrokenAccessibility()
    empty_result = await checker._find_aria_candidates(broken_page, "ol.grid_view")
    assert empty_result == [], "snapshot 抛异常时应返回空列表"
