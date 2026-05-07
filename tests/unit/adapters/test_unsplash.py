"""Unit tests for Unsplash adapter handler.

Covers extract/act dispatch, photo grid extraction, photo detail extraction,
search/open_photo/paginate actions, and extract boundary compliance
(type/alt/extractable field structure).
"""
import pytest

from adapters.unsplash.handler import Handler
from anbm.adapter.base import SelectorFailedError
from tests.fixtures.mock_pages import FakePage


@pytest.fixture
def handler():
    return Handler()


# ── extract: photo_grid ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_photo_grid_returns_photos(handler):
    """photo_grid 提取照片列表，每项含 type/src/alt/extractable。"""
    page = FakePage.from_html(
        open(
            "tests/fixtures/html_snapshots/unsplash/photo_grid.html",
            encoding="utf-8",
        ).read(),
        url="https://unsplash.com",
    )
    result = await handler.extract(page, "photo_grid")
    assert result.state == "photo_grid"
    assert len(result.data["photos"]) == 3
    assert result.data["has_more"] is True

    first = result.data["photos"][0]
    assert first["type"] == "image"
    assert "photo-1" in first["src"]
    assert "mountain" in first["alt"]
    assert first["extractable"] is True


@pytest.mark.asyncio
async def test_extract_photo_grid_missing_alt_is_not_extractable(handler):
    """没有 alt 的照片 extractable=False。"""
    page = FakePage.from_html(
        open(
            "tests/fixtures/html_snapshots/unsplash/photo_grid.html",
            encoding="utf-8",
        ).read(),
        url="https://unsplash.com",
    )
    result = await handler.extract(page, "photo_grid")
    third = result.data["photos"][2]
    assert third["alt"] == ""
    assert third["extractable"] is False


@pytest.mark.asyncio
async def test_extract_photo_grid_all_fields_present(handler):
    """每条照片记录包含所有必需字段，类型正确。"""
    page = FakePage.from_html(
        open(
            "tests/fixtures/html_snapshots/unsplash/photo_grid.html",
            encoding="utf-8",
        ).read(),
        url="https://unsplash.com",
    )
    result = await handler.extract(page, "photo_grid")

    for photo in result.data["photos"]:
        assert set(photo.keys()) >= {"type", "src", "alt", "extractable", "photo_url"}
        assert photo["type"] == "image"
        assert isinstance(photo["src"], str)
        assert isinstance(photo["alt"], str)
        assert isinstance(photo["extractable"], bool)


@pytest.mark.asyncio
async def test_extract_photo_grid_no_figures_raises(handler):
    """网格中没有 figure → 抛 SelectorFailedError。"""
    page = FakePage.from_html(
        "<html><body><div>empty page</div></body></html>",
        url="https://unsplash.com",
    )
    with pytest.raises(SelectorFailedError):
        await handler.extract(page, "photo_grid")


# ── extract: photo_detail ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_photo_detail(handler):
    """photo_detail 返回 type/src/alt/extractable/author。"""
    html = """<html><body>
      <img src="https://images.unsplash.com/photo-1?w=1200" alt="a mountain">
      <div data-testid="non-sponsored-photo-download-button">Download</div>
      <div data-testid="user-avatar"><img alt="John Doe"></div>
    </body></html>"""
    page = FakePage.from_html(html, url="https://unsplash.com/photos/abc123")
    result = await handler.extract(page, "photo_detail")
    assert result.state == "photo_detail"
    assert result.data["type"] == "image"
    assert "photo-1" in result.data["src"]
    assert result.data["alt"] == "a mountain"
    assert result.data["extractable"] is True
    assert result.data["author"] == "John Doe"


# ── act ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_act_search_returns_photo_grid(handler):
    """search 动作返回 photo_grid 状态。"""
    page = FakePage(url="https://unsplash.com")
    result = await handler.act(page, "search", {"keyword": "nature"})
    assert result.success is True
    assert result.next_state == "photo_grid"


@pytest.mark.asyncio
async def test_act_search_missing_keyword_raises(handler):
    """search 缺少 keyword 抛 SelectorFailedError。"""
    page = FakePage(url="https://unsplash.com")
    with pytest.raises(SelectorFailedError):
        await handler.act(page, "search", {})


@pytest.mark.asyncio
async def test_act_open_photo_returns_photo_detail(handler):
    """open_photo 返回 photo_detail 状态。"""
    page = FakePage(url="https://unsplash.com")
    result = await handler.act(
        page, "open_photo", {"url": "https://unsplash.com/photos/abc123"}
    )
    assert result.success is True
    assert result.next_state == "photo_detail"


@pytest.mark.asyncio
async def test_act_paginate_returns_photo_grid(handler):
    """paginate 返回 photo_grid 状态。"""
    page = FakePage(url="https://unsplash.com")
    result = await handler.act(page, "paginate", {})
    assert result.success is True
    assert result.next_state == "photo_grid"


@pytest.mark.asyncio
async def test_act_extract_content_returns_photo_detail(handler):
    """extract_content act 返回 photo_detail（内容在 extract 中处理）。"""
    page = FakePage(url="https://unsplash.com/photos/abc123")
    result = await handler.act(page, "extract_content", {})
    assert result.success is True
    assert result.next_state == "photo_detail"


@pytest.mark.asyncio
async def test_act_unknown_action_raises(handler):
    """未知操作抛 ValueError。"""
    page = FakePage(url="https://unsplash.com")
    with pytest.raises(ValueError, match="不支持操作"):
        await handler.act(page, "unknown", {})


@pytest.mark.asyncio
async def test_extract_unknown_state_raises(handler):
    """未知状态抛 ValueError。"""
    page = FakePage(url="https://unsplash.com")
    with pytest.raises(ValueError, match="不支持状态"):
        await handler.extract(page, "invalid_state")


# ── extract boundary compliance ──────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_boundary_no_inference(handler):
    """extract 不生成 DOM 中不存在的信息 — alt 为空时不补全。"""
    page = FakePage.from_html(
        """<html><body>
          <figure data-testid="asset-grid-masonry-figure">
            <img data-testid="asset-grid-masonry-img" src="https://images.unsplash.com/photo-1" alt="">
          </figure>
        </body></html>""",
        url="https://unsplash.com",
    )
    result = await handler.extract(page, "photo_grid")
    photo = result.data["photos"][0]
    assert photo["alt"] == ""  # 不补全语义
    assert photo["extractable"] is False  # 无可提取文本
