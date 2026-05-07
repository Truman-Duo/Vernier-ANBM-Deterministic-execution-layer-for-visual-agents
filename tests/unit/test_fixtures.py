import pytest
from tests.fixtures.mock_pages import FakePage, FakeElement


class TestFakePageFromHtml:

    @pytest.mark.asyncio
    async def test_from_html_basic_selectors(self):
        html = """<div id="main">
            <p class="intro">Hello World</p>
            <a href="/wiki/Test" class="link">Test Link</a>
            <span class="item"><span class="title">Item 1</span></span>
        </div>"""
        page = FakePage.from_html(html, "https://example.com")

        el = await page.query_selector("#main")
        assert el is not None
        text = await el.text_content()
        assert "Hello World" in text

        el = await page.query_selector(".intro")
        assert el is not None

        el = await page.query_selector("p")
        assert el is not None

        el = await page.query_selector('[href^="/wiki/"]')
        assert el is not None
        assert await el.get_attribute("href") == "/wiki/Test"

    @pytest.mark.asyncio
    async def test_from_html_hn_news_list(self):
        with open("tests/fixtures/html_snapshots/hackernews/news_list.html",
                  encoding="utf-8") as f:
            html = f.read()
        page = FakePage.from_html(html, "https://news.ycombinator.com/news")

        athing_rows = await page.query_selector_all("tr.athing")
        assert len(athing_rows) == 3

        first = athing_rows[0]
        title_el = await first.query_selector("span.titleline > a")
        assert title_el is not None
        title = await title_el.text_content()
        assert "AISLE" in title

        subtexts = await page.query_selector_all("td.subtext")
        assert len(subtexts) == 3

        score_el = await subtexts[0].query_selector("span.score")
        score = await score_el.text_content()
        assert "128" in score

        author_el = await subtexts[0].query_selector("a.hnuser")
        author = await author_el.text_content()
        assert "mmsc" in author

        more_link = await page.query_selector("a.morelink")
        assert more_link is not None

    @pytest.mark.asyncio
    async def test_from_html_hn_nested_comments(self):
        """HN nested comment extraction — must pass via from_html() snapshot."""
        with open("tests/fixtures/html_snapshots/hackernews/item_detail.html",
                  encoding="utf-8") as f:
            html = f.read()
        page = FakePage.from_html(html, "https://news.ycombinator.com/item?id=1")

        comtrs = await page.query_selector_all("tr.comtr")
        assert len(comtrs) == 5

        indent_levels = []
        for row in comtrs:
            indent_img = await row.query_selector("td.ind > img[width]")
            level = 0
            if indent_img:
                width_str = await indent_img.get_attribute("width") or "0"
                level = int(width_str) // 40
            indent_levels.append(level)

            author_el = await row.query_selector("a.hnuser")
            body_el = await row.query_selector("div.commtext")

            if author_el:
                author = await author_el.text_content()
                assert author

            if body_el:
                text = await body_el.text_content()
                assert text

        assert indent_levels == [0, 0, 1, 2, 3]
