import re
from urllib.parse import quote, urlparse, parse_qs

from anbm.adapter.base import BaseAdapter, ExtractResult, ActResult, SelectorFailedError


class Handler(BaseAdapter):

    async def extract(self, page, state: str) -> ExtractResult:
        if state == "search_results":
            return await self._extract_search_results(page)
        elif state == "paper_detail":
            return await self._extract_paper_detail(page)
        raise ValueError(f"extract() 不支持状态: {state}")

    async def act(self, page, action: str, params: dict) -> ActResult:
        if action == "search":
            return await self._act_search(page, params)
        elif action == "paginate":
            return await self._act_paginate(page, params)
        elif action == "open_paper":
            return await self._act_open_paper(page, params)
        raise ValueError(f"act() 不支持操作: {action}")

    async def _extract_search_results(self, page):
        items = await page.query_selector_all(".arxiv-result")
        if not items:
            raise SelectorFailedError(
                "找不到搜索结果条目",
                selector=".arxiv-result",
            )

        results = []
        for item in items:
            pid = await item.get_attribute("data-paper-id")

            title_el = await item.query_selector(".title")
            title = (await title_el.text_content()).strip() if title_el else ""

            href = ""
            link_el = await item.query_selector("a[href^='/abs/']")
            if link_el:
                href = await link_el.get_attribute("href") or ""
            url = f"https://arxiv.org{href}" if href else ""

            if not pid and href:
                pid = href.split("/abs/")[-1].split("?")[0]

            authors_el = await item.query_selector(".authors")
            authors = []
            if authors_el:
                text = (await authors_el.text_content()).strip()
                authors = [a.strip() for a in text.replace("Authors:", "").split(",") if a.strip()]

            abstract_el = await item.query_selector(".abstract")
            abstract = ""
            if abstract_el:
                abstract = (await abstract_el.text_content()).strip()
                abstract = abstract[:200]

            results.append({
                "id": pid or "",
                "title": title,
                "authors": authors,
                "abstract_short": abstract,
                "url": url,
            })

        total_results = await self._parse_total_results(page)
        page_start = self._parse_start_from_url(page.url)

        return ExtractResult(
            data={
                "results": results,
                "total_results": total_results,
                "page_start": page_start,
            },
            state="search_results",
        )

    async def _extract_paper_detail(self, page):
        title_el = await page.query_selector("h1.title")
        if not title_el:
            raise SelectorFailedError(
                "找不到论文标题",
                selector="h1.title",
            )
        title = (await title_el.text_content()).strip()

        abstract_el = await page.query_selector(".abstract")
        abstract = ""
        if abstract_el:
            abstract = (await abstract_el.text_content()).strip()

        return ExtractResult(
            data={
                "title": title,
                "abstract": abstract,
            },
            state="paper_detail",
        )

    async def _act_search(self, page, params: dict) -> ActResult:
        query = params.get("query", "")
        searchtype = params.get("searchtype", "all")
        search_url = (
            f"https://arxiv.org/search/"
            f"?query={quote(query)}&searchtype={searchtype}&start=0"
        )
        await page.goto(search_url)
        await page.wait_for_load_state("networkidle", timeout=15000)
        return ActResult(success=True, next_state="search_results")

    async def _act_paginate(self, page, params: dict) -> ActResult:
        start = params.get("start")
        if start is None:
            current = self._parse_start_from_url(page.url)
            start = current + 25

        query = params.get("query", "")
        searchtype = params.get("searchtype", "all")
        if not query:
            parsed = urlparse(page.url)
            qs = parse_qs(parsed.query)
            query = qs.get("query", [""])[0]
            searchtype = qs.get("searchtype", ["all"])[0]

        search_url = (
            f"https://arxiv.org/search/"
            f"?query={quote(query)}&searchtype={searchtype}&start={start}"
        )
        await page.goto(search_url)
        await page.wait_for_load_state("networkidle", timeout=15000)
        return ActResult(success=True, next_state="search_results")

    async def _act_open_paper(self, page, params: dict) -> ActResult:
        url = params.get("url", "")
        if not url:
            raise SelectorFailedError(
                "缺少 url 参数",
                selector="params.url",
            )
        await page.goto(url)
        await page.wait_for_load_state("networkidle", timeout=15000)
        return ActResult(success=True, next_state="paper_detail")

    async def _parse_total_results(self, page) -> int:
        try:
            text = await page.evaluate(
                "() => document.querySelector('h1')?.textContent || ''"
            )
            match = re.search(r"of\s+([\d,]+)", text)
            if match:
                return int(match.group(1).replace(",", ""))
        except Exception:
            pass
        return 0

    @staticmethod
    def _parse_start_from_url(url: str) -> int:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        return int(qs.get("start", ["0"])[0])
