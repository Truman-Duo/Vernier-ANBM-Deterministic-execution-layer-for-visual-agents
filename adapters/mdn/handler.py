"""
MDN Web Docs Adapter
选择器选择理由：
- article state: h1 — MDN 文档页始终有 server-rendered 的 h1 标题
- search_results state: URL /search — MDN 搜索页的固定路径格式
- 代码块: pre[class*="brush:"] — Mozilla 长期维护的语法高亮标记
- 交互示例: iframe — MDN 的内联交互式示例
- MDN 使用 Web Components（mdn-*）和 React，核心内容在 <main> 中
- 所有提取使用 Playwright DOM API，不依赖 evaluate
"""
from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError


class Handler(BaseAdapter):

    async def extract(self, page, state: str) -> ExtractResult:
        if state == "article":
            return await self._extract_article(page)
        if state == "search_results":
            return await self._extract_search_results(page)
        if state == "not_found":
            return ExtractResult(data={"content_blocks": []}, state="not_found")
        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action: str, params: dict) -> ActResult:
        if action == "extract_content":
            return ActResult(success=True, next_state="article")
        if action == "open_section":
            return await self._act_open_section(page, params)
        raise ValueError(f"act() 不支持操作: {action}")

    async def _extract_article(self, page):
        await page.wait_for_selector("h1", timeout=10000)

        title_el = await page.query_selector("h1")
        title = (await title_el.text_content()).strip() if title_el else ""
        blocks = []

        # 1. Code blocks — pre[class*="brush:"]
        for pre in await page.query_selector_all('pre[class*="brush:"]'):
            text = (await pre.text_content()).strip()
            if text:
                blocks.append({
                    "type": "code",
                    "content": text,
                    "extractable": True,
                })

        # 2. Interactive examples — iframe
        for iframe in await page.query_selector_all("iframe"):
            src = await iframe.get_attribute("src") or ""
            if src:
                blocks.append({
                    "type": "interactive_viz",
                    "src": src,
                    "extractable": False,
                })

        # 3. Images — img with src
        for img in await page.query_selector_all("img"):
            src = await img.get_attribute("src") or ""
            if src:
                alt = await img.get_attribute("alt") or ""
                blocks.append({
                    "type": "image",
                    "src": src,
                    "alt": alt,
                    "extractable": bool(alt.strip()),
                })

        # 4. Text — <p> paragraphs
        for p in await page.query_selector_all("p"):
            text = (await p.text_content()).strip()
            if text:
                blocks.append({
                    "type": "text",
                    "content": text,
                })

        # 5. Headings — h2, h3, h4
        for tag in ("h2", "h3", "h4"):
            for h in await page.query_selector_all(tag):
                text = (await h.text_content()).strip()
                if text:
                    blocks.append({
                        "type": "text",
                        "content": text,
                        "heading_level": int(tag[1]),
                    })

        return ExtractResult(
            data={"title": title, "content_blocks": blocks},
            state="article",
        )

    async def _extract_search_results(self, page):
        blocks = []
        for container in await page.query_selector_all("main, article"):
            for el in await container.query_selector_all("h2, p, a"):
                text = (await el.text_content()).strip()
                if text:
                    blocks.append({"type": "text", "content": text})
        return ExtractResult(data={"content_blocks": blocks}, state="search_results")

    async def _act_open_section(self, page, params: dict) -> ActResult:
        section_id = params.get("section_id", "")
        if not section_id:
            raise SelectorFailedError(
                "open_section 需要 section_id 参数", selector=None
            )
        anchor = await page.query_selector(f"#{section_id}, [href='#{section_id}']")
        if anchor:
            await anchor.click()
            await page.wait_for_timeout(500)
        return ActResult(success=True, next_state="article")
