"""Unit tests for MDN Web Docs adapter handler.

Covers extract/act dispatch, article content extraction with code blocks,
interactive examples, images, text, and extract boundary compliance
(iframe/canvas marked extractable=False).
"""
import pytest

from adapters.mdn.handler import Handler
from anbm.adapter.base import SelectorFailedError
from tests.fixtures.mock_pages import FakePage


@pytest.fixture
def handler():
    return Handler()


# ── extract: article ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_article_returns_title_and_blocks(handler):
    """文章提取返回 title 和 content_blocks 列表。"""
    page = FakePage.from_html(
        open(
            "tests/fixtures/html_snapshots/mdn/article.html",
            encoding="utf-8",
        ).read(),
        url="https://developer.mozilla.org/en-US/docs/Web/HTML/Element/a",
    )
    result = await handler.extract(page, "article")
    assert result.state == "article"
    assert result.data["title"] == "The Anchor element"
    assert len(result.data["content_blocks"]) > 0


@pytest.mark.asyncio
async def test_extract_code_blocks_preserved(handler):
    """代码块完整提取，保留换行和缩进。"""
    page = FakePage.from_html(
        open(
            "tests/fixtures/html_snapshots/mdn/article.html",
            encoding="utf-8",
        ).read(),
        url="https://developer.mozilla.org/en-US/docs/Web/HTML/Element/a",
    )
    result = await handler.extract(page, "article")
    code_blocks = [b for b in result.data["content_blocks"] if b["type"] == "code"]
    assert len(code_blocks) == 2
    assert all(b["extractable"] is True for b in code_blocks)
    assert "Visit Example" in code_blocks[0]["content"]
    assert "Jump to section" in code_blocks[1]["content"]


@pytest.mark.asyncio
async def test_extract_interactive_viz_marked_not_extractable(handler):
    """交互式 iframe 标记为 extractable=False，只记录 src。"""
    page = FakePage.from_html(
        open(
            "tests/fixtures/html_snapshots/mdn/article.html",
            encoding="utf-8",
        ).read(),
        url="https://developer.mozilla.org/en-US/docs/Web/HTML/Element/a",
    )
    result = await handler.extract(page, "article")
    viz_blocks = [b for b in result.data["content_blocks"] if b["type"] == "interactive_viz"]
    assert len(viz_blocks) == 1
    assert viz_blocks[0]["extractable"] is False
    assert "developer.mozilla.org" in viz_blocks[0]["src"]


@pytest.mark.asyncio
async def test_extract_images_src_and_alt_only(handler):
    """图片只返回 src 和 alt，不做语义描述。"""
    page = FakePage.from_html(
        open(
            "tests/fixtures/html_snapshots/mdn/article.html",
            encoding="utf-8",
        ).read(),
        url="https://developer.mozilla.org/en-US/docs/Web/HTML/Element/a",
    )
    result = await handler.extract(page, "article")
    image_blocks = [b for b in result.data["content_blocks"] if b["type"] == "image"]
    assert len(image_blocks) == 1
    img = image_blocks[0]
    assert set(img.keys()) >= {"type", "src", "alt", "extractable"}
    assert img["src"] != ""
    assert img["alt"] == "diagram of a hyperlink structure"
    assert img["extractable"] is True


@pytest.mark.asyncio
async def test_extract_text_blocks_content(handler):
    """文本块以 content 字段返回原始文本，不加工不推理。"""
    page = FakePage.from_html(
        open(
            "tests/fixtures/html_snapshots/mdn/article.html",
            encoding="utf-8",
        ).read(),
        url="https://developer.mozilla.org/en-US/docs/Web/HTML/Element/a",
    )
    result = await handler.extract(page, "article")
    text_blocks = [b for b in result.data["content_blocks"] if b["type"] == "text"]
    assert len(text_blocks) > 0
    for tb in text_blocks:
        assert "content" in tb
        assert isinstance(tb["content"], str)
        assert len(tb["content"]) > 0


# ── extract: search_results / not_found ─────────────────────────────

@pytest.mark.asyncio
async def test_extract_search_results(handler):
    """search_results 返回 content_blocks。"""
    page = FakePage(url="https://developer.mozilla.org/en-US/search?q=html")
    result = await handler.extract(page, "search_results")
    assert result.state == "search_results"
    assert "content_blocks" in result.data


@pytest.mark.asyncio
async def test_extract_not_found_returns_empty(handler):
    """not_found 返回空 content_blocks。"""
    page = FakePage(url="https://developer.mozilla.org/en-US/docs/nonexistent")
    result = await handler.extract(page, "not_found")
    assert result.state == "not_found"
    assert result.data["content_blocks"] == []


# ── act ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_act_open_section(handler):
    """open_section 返回 article 状态。"""
    page = FakePage(
        url="https://developer.mozilla.org/en-US/docs/Web/HTML/Element/a"
    )
    result = await handler.act(page, "open_section", {"section_id": "try-it"})
    assert result.success is True
    assert result.next_state == "article"


@pytest.mark.asyncio
async def test_act_open_section_missing_id_raises(handler):
    """open_section 缺少 section_id 抛 SelectorFailedError。"""
    page = FakePage(url="https://developer.mozilla.org/en-US/docs/Web/HTML")
    with pytest.raises(SelectorFailedError):
        await handler.act(page, "open_section", {})


@pytest.mark.asyncio
async def test_act_extract_content(handler):
    """extract_content act 返回 article（内容在 extract 中处理）。"""
    page = FakePage(
        url="https://developer.mozilla.org/en-US/docs/Web/HTML/Element/a"
    )
    result = await handler.act(page, "extract_content", {})
    assert result.success is True
    assert result.next_state == "article"


@pytest.mark.asyncio
async def test_act_unknown_action_raises(handler):
    """未知操作抛 ValueError。"""
    page = FakePage(url="https://developer.mozilla.org/en-US/docs/Web/HTML")
    with pytest.raises(ValueError, match="不支持操作"):
        await handler.act(page, "unknown", {})


@pytest.mark.asyncio
async def test_extract_unknown_state_raises(handler):
    """未知状态抛 ValueError。"""
    page = FakePage(url="https://developer.mozilla.org/en-US/docs/Web/HTML")
    with pytest.raises(ValueError, match="不支持状态"):
        await handler.extract(page, "invalid_state")


# ── extract boundary compliance ──────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_boundary_no_iframe_penetration(handler):
    """iframe 只记录 src，不穿透提取内部内容。"""
    html = """<html><body>
      <main>
        <h1>Test</h1>
        <iframe src="https://example.com/interactive"></iframe>
      </main>
    </body></html>"""
    page = FakePage.from_html(html, url="https://developer.mozilla.org/en-US/docs/Test")
    result = await handler.extract(page, "article")
    viz_blocks = [b for b in result.data["content_blocks"] if b["type"] == "interactive_viz"]
    assert len(viz_blocks) == 1
    assert viz_blocks[0]["src"] == "https://example.com/interactive"
    assert "content" not in viz_blocks[0]


@pytest.mark.asyncio
async def test_extract_boundary_no_semantic_inference(handler):
    """extract 返回的文本与 DOM 中的原始内容一致，不增删改。"""
    html = """<html><body>
      <main>
        <h1>Test</h1>
        <p>The quick brown fox.</p>
        <p>   Extra whitespace   </p>
      </main>
    </body></html>"""
    page = FakePage.from_html(html, url="https://developer.mozilla.org/en-US/docs/Test")
    result = await handler.extract(page, "article")
    text_blocks = [b for b in result.data["content_blocks"] if b["type"] == "text"]
    contents = [b["content"] for b in text_blocks]
    assert "The quick brown fox." in contents
    assert "Extra whitespace" in contents  # stripped but not altered
