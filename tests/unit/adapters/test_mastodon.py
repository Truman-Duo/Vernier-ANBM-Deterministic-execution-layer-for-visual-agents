"""Unit tests for Mastodon adapter handler.

Covers extract() and act() dispatch, _extract_feed() field extraction,
and the SelectorFailedError path when no articles are found.
"""
import pytest

from adapters.mastodon.handler import Handler
from anbm.adapter.base import SelectorFailedError
from tests.fixtures.mock_pages import FakePage


@pytest.fixture
def handler():
    return Handler()


@pytest.mark.asyncio
async def test_extract_feed_partial_returns_statuses(handler):
    """_extract_feed 返回 statuses 列表，每项包含 id/author/content/url/created_at。"""
    page = FakePage.from_html(
        open(
            "tests/fixtures/html_snapshots/mastodon/feed_partial.html",
            encoding="utf-8",
        ).read(),
        url="https://hachyderm.io/public/local",
    )
    result = await handler.extract(page, "feed_partial")
    assert result.state == "feed_partial"
    assert len(result.data["statuses"]) == 3
    assert result.data["has_more"] is True

    first = result.data["statuses"][0]
    assert first["id"] == "114567890123456789"
    assert "testuser1" in first["author"]
    assert "open source" in first["content"]
    assert first["url"] == "https://hachyderm.io/@testuser1/114567890123456789"
    assert first["created_at"] == "2026-04-30T10:00:00Z"


@pytest.mark.asyncio
async def test_extract_feed_partial_all_fields(handler):
    """每条 status 的字段类型正确，无缺失。"""
    page = FakePage.from_html(
        open(
            "tests/fixtures/html_snapshots/mastodon/feed_partial.html",
            encoding="utf-8",
        ).read(),
        url="https://hachyderm.io/public/local",
    )
    result = await handler.extract(page, "feed_partial")

    for status in result.data["statuses"]:
        assert isinstance(status["id"], str) and len(status["id"]) > 0
        assert isinstance(status["author"], str) and len(status["author"]) > 0
        assert isinstance(status["content"], str) and len(status["content"]) > 0
        assert isinstance(status["url"], str) and status["url"].startswith("https://")
        assert isinstance(status["created_at"], str) and len(status["created_at"]) > 0


@pytest.mark.asyncio
async def test_extract_no_articles_raises_error(handler):
    """feed 中没有文章 → 抛 SelectorFailedError。"""
    page = FakePage.from_html(
        "<html><body><div>empty feed</div></body></html>",
        url="https://hachyderm.io/public/local",
    )
    with pytest.raises(SelectorFailedError) as exc:
        await handler.extract(page, "feed_partial")
    assert exc.value.selector == "article[data-id]"


@pytest.mark.asyncio
async def test_extract_feed_exhausted(handler):
    """feed_exhausted 状态返回空列表和 has_more=False。"""
    page = FakePage(url="https://hachyderm.io/public/local")
    result = await handler.extract(page, "feed_exhausted")
    assert result.state == "feed_exhausted"
    assert result.data["statuses"] == []
    assert result.data["has_more"] is False


@pytest.mark.asyncio
async def test_act_scroll_load_more_dispatches(handler):
    """act() 正确路由到 scroll_load_more 实现（不抛异常）。"""
    page = FakePage(url="https://hachyderm.io/public/local")
    result = await handler.act(page, "scroll_load_more", {})
    assert result.success is True
    assert result.next_state == "feed_partial"
    assert isinstance(result.data, dict)
    assert "loaded_count" in result.data
    assert "has_more" in result.data


@pytest.mark.asyncio
async def test_act_unknown_action_raises(handler):
    """未知操作抛 ValueError。"""
    page = FakePage(url="https://hachyderm.io/public/local")
    with pytest.raises(ValueError, match="不支持操作"):
        await handler.act(page, "unknown_action", {})


@pytest.mark.asyncio
async def test_extract_unknown_state_raises(handler):
    """未知状态抛 ValueError。"""
    page = FakePage(url="https://hachyderm.io/public/local")
    with pytest.raises(ValueError, match="不支持状态"):
        await handler.extract(page, "invalid_state")
